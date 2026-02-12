"""OpenCode integration: run git-review."""

import logging
import os
import subprocess
import threading

logger = logging.getLogger(__name__)


def _run_opencode_cmd(
    opencode_cmd: str,
    prompt: str,
    project_dir: str,
    timeout: int,
    log_level: str = "",
    model: str = "",
) -> tuple[int, str, str]:
    """
    Run opencode run, stream stdout/stderr to log.

    Args:
        log_level: opencode --log-level, e.g. WARN/ERROR; empty to omit
        model: opencode --model, format provider/model, e.g. agione/131249505071992832

    Returns:
        (returncode, stdout, stderr)
    """
    cmd = [opencode_cmd, "run", "--print-logs"]
    if log_level:
        cmd.extend(["--log-level", log_level])
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    logger.info("[opencode] running: %s ...", " ".join(cmd[:3]))

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=project_dir,
        env=os.environ.copy(),
    )

    stdout_lines = []
    stderr_lines = []

    def read_stream(stream, lines: list, prefix: str) -> None:
        for line in iter(stream.readline, ""):
            line = line.rstrip()
            if line:
                lines.append(line)
                logger.info("[opencode] %s %s", prefix, line)

    t_stdout = threading.Thread(
        target=read_stream, args=(process.stdout, stdout_lines, "out:")
    )
    t_stderr = threading.Thread(
        target=read_stream, args=(process.stderr, stderr_lines, "err:")
    )
    t_stdout.daemon = True
    t_stderr.daemon = True
    t_stdout.start()
    t_stderr.start()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise

    t_stdout.join(timeout=1)
    t_stderr.join(timeout=1)

    stdout = "\n".join(stdout_lines)
    stderr = "\n".join(stderr_lines)
    return process.returncode or 0, stdout, stderr


def build_clone_url(http_url: str, token: str) -> str:
    """
    Build authenticated clone URL for private repo.
    Inject token into HTTPS URL: https://oauth2:TOKEN@host/path.git
    """
    if not token or not http_url.startswith("http"):
        logger.info("[CloneURL] no token to inject, using original URL")
        return http_url
    scheme, rest = http_url.split("://", 1)
    logger.info("[CloneURL] token injected -> %s://oauth2:***@%s", scheme, rest)
    return f"{scheme}://oauth2:{token}@{rest}"


def _run_review_common(
    prompt: str,
    repo_workspace: str,
    opencode_cmd: str,
    project_dir: str,
    timeout: int,
    opencode_log_level: str,
    opencode_model: str,
    log_prefix: str,
) -> str:
    """
    Common flow: create workspace, run opencode, parse result.
    Reraises subprocess.TimeoutExpired on timeout.
    """
    os.makedirs(repo_workspace, exist_ok=True)
    logger.info("[%s] repo_workspace ready %s", log_prefix, repo_workspace)
    logger.info("[%s] calling opencode timeout=%s", log_prefix, timeout)
    try:
        returncode, stdout, stderr = _run_opencode_cmd(
            opencode_cmd,
            prompt,
            project_dir,
            timeout,
            opencode_log_level,
            model=opencode_model,
        )
    except subprocess.TimeoutExpired:
        raise
    if returncode != 0:
        logger.warning("[%s] opencode non-zero returncode=%s", log_prefix, returncode)
        return f"AI Review failed: {stderr or 'Unknown error'}"
    logger.info("[%s] opencode done, output len=%s", log_prefix, len(stdout or ""))
    return stdout or "(no output)"


def run_opencode_review(
    repo_url: str,
    source_branch: str,
    target_branch: str,
    project_path: str,
    repo_workspace: str,
    opencode_cmd: str,
    project_dir: str,
    timeout: int = 300,
    opencode_log_level: str = "",
    opencode_model: str = "",
) -> str:
    """
    Run opencode with git-review skill context for MR review.
    """
    logger.info(
        "[MR Review] start source=%s target=%s path=%s",
        source_branch,
        target_branch,
        project_path,
    )
    prompt = (
        "请使用 git-review skill 完成以下 MR 的代码审查。\n\n"
        f"上下文：\n"
        f"- repo_url: {repo_url}\n"
        f"- source_branch: {source_branch}\n"
        f"- target_branch: {target_branch}\n"
        f"- repo_workspace: {repo_workspace}\n"
        f"- project_path: {project_path}\n\n"
        "请按 skill 流程：检查/拉取分支、本地 git diff、执行 AI 代码审查。\n"
        "审查时须同时兼顾两点：\n"
        "1) 对 diff 本身做逐行/逐文件审查（若含 .py 须采用 the-ai-engineer-python-code-review 标准；若含 .vue 须采用 vue-code-review 标准）；\n"
        "2) 从「合入后整体代码」的视角审查：本次变更合入后是否与现有逻辑冲突、是否可能产生意外影响或破坏调用关系/数据流/配置等，并在输出中体现（如单独小节「整体影响与风险」或并入「发现的问题」）。\n"
        "最终输出仍按 git-review 要求的格式（审查总结、发现的问题、建议、结论）用中文输出。"
    )
    return _run_review_common(
        prompt,
        repo_workspace,
        opencode_cmd,
        project_dir,
        timeout,
        opencode_log_level,
        opencode_model,
        "MR Review",
    )


def run_opencode_review_push(
    repo_url: str,
    branch: str,
    before_sha: str,
    after_sha: str,
    project_path: str,
    repo_workspace: str,
    opencode_cmd: str,
    project_dir: str,
    timeout: int = 300,
    opencode_log_level: str = "",
    opencode_model: str = "",
) -> str:
    """
    Run opencode in push mode to review changes in the given commit range.
    """
    logger.info(
        "[Push Review] start branch=%s before=%s after=%s path=%s",
        branch,
        before_sha[:8],
        after_sha[:8],
        project_path,
    )
    prompt = (
        "请使用 git-review skill 完成以下 push 的代码审查（push 模式）。\n\n"
        f"上下文：\n"
        f"- repo_url: {repo_url}\n"
        f"- branch: {branch}\n"
        f"- before_sha: {before_sha}\n"
        f"- after_sha: {after_sha}\n"
        f"- repo_workspace: {repo_workspace}\n"
        f"- project_path: {project_path}\n\n"
        "请按 skill 的 push 流程：检查/拉取仓库与分支、"
        "执行 git diff before_sha..after_sha 获取变更、执行 AI 代码审查。\n"
        "审查时须同时兼顾两点：\n"
        "1) 对 diff 本身做逐行/逐文件审查（若含 .py 须采用 the-ai-engineer-python-code-review 标准；若含 .vue 须采用 vue-code-review 标准）；\n"
        "2) 从「合入后整体代码」的视角审查：本次变更合入后是否与现有逻辑冲突、是否可能产生意外影响或破坏调用关系/数据流/配置等，并在输出中体现（如单独小节「整体影响与风险」或并入「发现的问题」）。\n"
        "最终输出仍按 git-review 要求的格式（审查总结、发现的问题、建议、结论）用中文输出。"
    )
    return _run_review_common(
        prompt,
        repo_workspace,
        opencode_cmd,
        project_dir,
        timeout,
        opencode_log_level,
        opencode_model,
        "Push Review",
    )
