"""OpenCode 调用：执行 git-review 审查。"""

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
    调用 opencode run，实时输出 stdout/stderr 到日志。

    Args:
        log_level: opencode --log-level，如 WARN/ERROR，空则不传
        model: opencode --model，格式 provider/model，如 agione/131249505071992832

    Returns:
        (returncode, stdout, stderr)
    """
    cmd = [opencode_cmd, "run", "--print-logs"]
    if log_level:
        cmd.extend(["--log-level", log_level])
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    logger.info("[opencode] 执行命令: %s ...", " ".join(cmd[:3]))

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
    为私有仓库构建带认证的 clone URL。
    将 token 注入 HTTPS URL，格式：https://oauth2:TOKEN@host/path.git
    """
    if not token or not http_url.startswith("http"):
        logger.info("[CloneURL] 无需注入 token，使用原 URL")
        return http_url
    scheme, rest = http_url.split("://", 1)
    logger.info("[CloneURL] 已注入 token -> %s://oauth2:***@%s", scheme, rest)
    return f"{scheme}://oauth2:{token}@{rest}"


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
    调用 opencode run，传入 git-review skill 所需上下文，执行 MR 审查。
    """
    logger.info(
        "[MR Review] 开始 source=%s target=%s path=%s",
        source_branch,
        target_branch,
        project_path,
    )
    os.makedirs(repo_workspace, exist_ok=True)
    logger.info("[MR Review] repo_workspace 已就绪 %s", repo_workspace)

    prompt = (
        "请使用 git-review skill 完成以下 MR 的代码审查。\n\n"
        f"上下文：\n"
        f"- repo_url: {repo_url}\n"
        f"- source_branch: {source_branch}\n"
        f"- target_branch: {target_branch}\n"
        f"- repo_workspace: {repo_workspace}\n"
        f"- project_path: {project_path}\n\n"
        "请按 skill 流程：检查/拉取分支、本地 git diff、"
        "执行 AI 代码审查，并直接输出审查结果。"
    )

    logger.info("[MR Review] 调用 opencode 命令 timeout=%s", timeout)
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
        logger.warning("[MR Review] opencode 返回非零 returncode=%s", returncode)
        return f"AI Review 执行出错: {stderr or '未知错误'}"
    logger.info("[MR Review] opencode 执行完成，输出长度=%s", len(stdout or ""))
    return stdout or "（无输出）"


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
    调用 opencode run，以 push 模式审查指定 commit 区间的变更。
    """
    logger.info(
        "[Push Review] 开始 branch=%s before=%s after=%s path=%s",
        branch,
        before_sha[:8],
        after_sha[:8],
        project_path,
    )
    os.makedirs(repo_workspace, exist_ok=True)
    logger.info("[Push Review] repo_workspace 已就绪 %s", repo_workspace)

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
        "执行 git diff before_sha..after_sha 获取变更、"
        "执行 AI 代码审查，并直接输出审查结果。"
    )

    logger.info("[Push Review] 调用 opencode 命令 timeout=%s", timeout)
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
        logger.warning("[Push Review] opencode 返回非零 returncode=%s", returncode)
        return f"AI Review 执行出错: {stderr or '未知错误'}"
    logger.info("[Push Review] opencode 执行完成，输出长度=%s", len(stdout or ""))
    return stdout or "（无输出）"
