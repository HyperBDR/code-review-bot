"""Claude Code integration: prepare git diff and run read-only review."""

import logging
import os
import re
import shutil
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

_CLAUDE_TOOLS = "Read,Grep,Glob,LS"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FALLBACK_NOTE_TEMPLATE = (
    "\n\n> 备注：主模型失败，本次使用备用模型 {model} 完成审查。"
)
_DEFAULT_SKILLS_ROOT = "claude-skills"
_MIRROR_LOCKS: dict[str, threading.Lock] = {}
_MIRROR_LOCKS_LOCK = threading.Lock()


def _redact(text: str, secrets: list[str]) -> str:
    """Redact known secrets from command output before logging or raising."""
    redacted = text
    sorted_secrets = sorted(
        (secret for secret in secrets if secret),
        key=len,
        reverse=True,
    )
    for secret in sorted_secrets:
        redacted = redacted.replace(secret, "***")
    return redacted


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


def _safe_child_path(root: str, *parts: str) -> str:
    """Resolve a child path under root and reject traversal."""
    root_path = os.path.abspath(root)
    child_path = os.path.abspath(os.path.join(root_path, *parts))
    if child_path != root_path and child_path.startswith(root_path + os.sep):
        return child_path
    raise ValueError("Invalid path")


def _safe_repo_path(repo_workspace: str, project_path: str) -> str:
    """Resolve a project path under repo_workspace and reject traversal."""
    return _safe_child_path(repo_workspace, project_path)


def _slug(value: object) -> str:
    """Return a filesystem-safe short label."""
    label = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-")
    return (label or "review")[:120]


def _mirror_lock(project_id: object) -> threading.Lock:
    """Return the per-project mirror lock."""
    key = str(project_id)
    with _MIRROR_LOCKS_LOCK:
        return _MIRROR_LOCKS.setdefault(key, threading.Lock())


def _mirror_path(repo_workspace: str, project_id: object) -> str:
    """Return the bare mirror path for a project."""
    return _safe_child_path(repo_workspace, "mirrors", f"{_slug(project_id)}.git")


def _task_workspace_path(
    repo_workspace: str,
    project_id: object,
    workspace_key: str,
) -> str:
    """Return the isolated workspace path for one review task."""
    return _safe_child_path(
        repo_workspace,
        "workspaces",
        _slug(project_id),
        _slug(workspace_key),
    )


def _resolve_skills_root(skills_root: str) -> str:
    """Resolve Claude skills root relative to the review-bot project root."""
    root = skills_root or _DEFAULT_SKILLS_ROOT
    return root if os.path.isabs(root) else os.path.join(_PROJECT_ROOT, root)


def _validate_claude_skills(skills_root: str) -> str:
    """Validate Claude Code project skills are present and return absolute root."""
    resolved = _resolve_skills_root(skills_root)
    git_review_skill = os.path.join(
        resolved,
        ".claude",
        "skills",
        "git-review",
        "SKILL.md",
    )
    if not os.path.isfile(git_review_skill):
        raise RuntimeError(
            "Claude Code git-review skill not found: "
            f"{git_review_skill}. Check CLAUDE_SKILLS_ROOT."
        )
    return resolved


def _run_git(
    args: list[str],
    *,
    cwd: str | None = None,
    timeout: int,
    secrets: list[str],
) -> str:
    """Run a git command and return stdout; raise on failures."""
    safe_args = _redact(" ".join(args[:3]), secrets)
    logger.info("[git] running: git %s", safe_args)
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        stderr = _redact(result.stderr or result.stdout or "Unknown git error", secrets)
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {stderr.strip()}")
    return result.stdout or ""


def _prepare_mirror(
    repo_url: str,
    repo_workspace: str,
    project_id: object,
    *,
    timeout: int,
    secrets: list[str],
) -> str:
    """Clone or refresh the per-project bare mirror under a project lock."""
    mirror_path = _mirror_path(repo_workspace, project_id)
    os.makedirs(os.path.dirname(mirror_path), exist_ok=True)

    with _mirror_lock(project_id):
        if not os.path.isdir(mirror_path):
            if os.path.exists(mirror_path):
                shutil.rmtree(mirror_path)
            logger.info("[Mirror] cloning project_id=%s", project_id)
            _run_git(
                ["clone", "--mirror", repo_url, mirror_path],
                timeout=timeout,
                secrets=secrets,
            )
            return mirror_path

        logger.info("[Mirror] fetching project_id=%s", project_id)
        try:
            _run_git(
                ["remote", "set-url", "origin", repo_url],
                cwd=mirror_path,
                timeout=timeout,
                secrets=secrets,
            )
            _run_git(
                ["fetch", "origin", "--prune"],
                cwd=mirror_path,
                timeout=timeout,
                secrets=secrets,
            )
        except subprocess.TimeoutExpired:
            raise
        except Exception:
            logger.warning("[Mirror] refresh failed, recloning project_id=%s", project_id)
            shutil.rmtree(mirror_path, ignore_errors=True)
            _run_git(
                ["clone", "--mirror", repo_url, mirror_path],
                timeout=timeout,
                secrets=secrets,
            )

    return mirror_path


def _prepare_task_workspace(
    mirror_path: str,
    repo_workspace: str,
    project_id: object,
    workspace_key: str,
    checkout_branch: str,
    *,
    timeout: int,
    secrets: list[str],
) -> str:
    """Create an isolated workspace for one review task and checkout branch."""
    workspace_path = _task_workspace_path(repo_workspace, project_id, workspace_key)
    if os.path.exists(workspace_path):
        shutil.rmtree(workspace_path)
    os.makedirs(os.path.dirname(workspace_path), exist_ok=True)

    try:
        _run_git(
            ["clone", "--no-checkout", mirror_path, workspace_path],
            timeout=timeout,
            secrets=secrets,
        )
        _run_git(
            ["checkout", "--force", "-B", checkout_branch, f"origin/{checkout_branch}"],
            cwd=workspace_path,
            timeout=timeout,
            secrets=secrets,
        )
    except Exception:
        shutil.rmtree(workspace_path, ignore_errors=True)
        raise

    return workspace_path


def _git_diff(repo_path: str, diff_ref: str, *, timeout: int, secrets: list[str]) -> str:
    """Return a git diff for the supplied ref range."""
    return _run_git(
        ["diff", "--no-color", diff_ref],
        cwd=repo_path,
        timeout=timeout,
        secrets=secrets,
    )


def _review_prompt(review_context: str) -> str:
    """Build the stable Claude Code review prompt."""
    return (
        "请使用 Claude Code 的 git-review skill 完成本次中文代码审查。\n"
        "仓库准备、分支切换和 git diff 已由外部 Python 服务完成；你只负责基于 stdin 中的上下文、"
        "git diff 和当前工作目录中的只读文件进行审查。\n"
        "只允许读取和搜索文件；不要修改文件，不要执行写入操作，不要运行 git 命令。\n"
        "请遵循 git-review skill 的输出格式和问题分级；如变更含 Python、Vue、Go、C/C++ "
        "相关文件，同时应用对应语言 skill 中的规则。Python 审查需要先识别 Python 2、"
        "Python 3 或双版本兼容口径。\n\n"
        f"{review_context}"
    )


def _run_claude_cmd(
    claude_cmd: str,
    prompt: str,
    stdin_content: str,
    repo_path: str,
    timeout: int,
    *,
    secrets: list[str],
    skills_root: str = _DEFAULT_SKILLS_ROOT,
    model: str = "",
) -> str:
    """Run Claude Code in print mode and return review text."""
    resolved_skills_root = _validate_claude_skills(skills_root)
    cmd = [claude_cmd, "--add-dir", resolved_skills_root]
    if model:
        cmd.extend(["--model", model])
    cmd.extend([
        "-p",
        prompt,
        "--output-format",
        "text",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--tools",
        _CLAUDE_TOOLS,
    ])
    logger.info(
        "[claude] running: %s --add-dir %s%s -p ...",
        claude_cmd,
        resolved_skills_root,
        f" --model {model}" if model else "",
    )
    result = subprocess.run(
        cmd,
        input=stdin_content,
        cwd=repo_path,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=os.environ.copy(),
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if result.returncode != 0:
        detail = _redact(stderr or stdout or "Unknown Claude Code error", secrets)
        raise RuntimeError(f"Claude Code failed: {detail.strip()}")
    if not stdout.strip():
        detail = _redact(stderr, secrets)
        raise RuntimeError(f"Claude Code returned empty output: {detail.strip()}")
    logger.info("[claude] done, output len=%s", len(stdout))
    return stdout.strip()


def _model_label(model: str) -> str:
    return model or "default"


def _claude_error_detail(exc: Exception, secrets: list[str]) -> str:
    """Return a concise, redacted Claude execution failure detail."""
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"timed out after {exc.timeout}s"
    return _redact(str(exc), secrets)


def _run_claude_with_fallbacks(
    claude_cmd: str,
    prompt: str,
    stdin_content: str,
    repo_path: str,
    timeout: int,
    *,
    secrets: list[str],
    skills_root: str = _DEFAULT_SKILLS_ROOT,
    model_fallbacks: list[str] | None = None,
    retry_delay_seconds: int = 2,
) -> str:
    """Run Claude Code, retrying execution failures with fallback models."""
    models = [model.strip() for model in (model_fallbacks or []) if model.strip()]
    if not models:
        models = [""]

    failures: list[str] = []
    for index, model in enumerate(models):
        try:
            result = _run_claude_cmd(
                claude_cmd,
                prompt,
                stdin_content,
                repo_path,
                timeout,
                secrets=secrets,
                skills_root=skills_root,
                model=model,
            )
            if index > 0:
                result += _FALLBACK_NOTE_TEMPLATE.format(model=_model_label(model))
            return result
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            detail = _claude_error_detail(exc, secrets)
            failures.append(f"{_model_label(model)}: {detail}")
            if index == len(models) - 1:
                break

            next_model = _model_label(models[index + 1])
            logger.warning(
                "[claude] model %s failed, retrying with %s: %s",
                _model_label(model),
                next_model,
                detail,
            )
            if retry_delay_seconds > 0:
                time.sleep(retry_delay_seconds)

    raise RuntimeError(
        "Claude Code failed for all configured models: " + "; ".join(failures)
    )


def _run_review_common(
    *,
    repo_url: str,
    project_id: object,
    project_path: str,
    repo_workspace: str,
    workspace_key: str,
    checkout_branch: str,
    diff_ref: str,
    review_context: str,
    claude_cmd: str,
    timeout: int,
    secrets: list[str],
    skills_root: str = _DEFAULT_SKILLS_ROOT,
    model_fallbacks: list[str] | None = None,
    retry_delay_seconds: int = 2,
) -> str:
    """Prepare repository, collect diff, and run Claude Code review."""
    os.makedirs(repo_workspace, exist_ok=True)
    mirror_path = _prepare_mirror(
        repo_url,
        repo_workspace,
        project_id or project_path,
        timeout=timeout,
        secrets=secrets,
    )
    repo_path = _prepare_task_workspace(
        mirror_path,
        repo_workspace,
        project_id or project_path,
        workspace_key or diff_ref,
        checkout_branch,
        timeout=timeout,
        secrets=secrets,
    )
    try:
        diff = _git_diff(repo_path, diff_ref, timeout=timeout, secrets=secrets)
        stdin_content = (
            f"{review_context}\n\n"
            "以下是本次变更的 git diff：\n\n"
            "```diff\n"
            f"{diff or '(empty diff)'}\n"
            "```\n"
        )
        return _run_claude_with_fallbacks(
            claude_cmd,
            _review_prompt(review_context),
            stdin_content,
            repo_path,
            timeout,
            secrets=secrets,
            skills_root=skills_root,
            model_fallbacks=model_fallbacks,
            retry_delay_seconds=retry_delay_seconds,
        )
    finally:
        shutil.rmtree(repo_path, ignore_errors=True)


def run_claude_review(
    repo_url: str,
    source_branch: str,
    target_branch: str,
    project_path: str,
    repo_workspace: str,
    claude_cmd: str,
    project_id: object = "",
    workspace_key: str = "",
    skills_root: str = _DEFAULT_SKILLS_ROOT,
    timeout: int = 300,
    *,
    token: str = "",
    model_fallbacks: list[str] | None = None,
    retry_delay_seconds: int = 2,
) -> str:
    """Run Claude Code review for a merge request."""
    logger.info(
        "[MR Review] start source=%s target=%s path=%s",
        source_branch,
        target_branch,
        project_path,
    )
    review_context = (
        "审查类型：Merge Request\n"
        f"项目：{project_path}\n"
        f"源分支：{source_branch}\n"
        f"目标分支：{target_branch}\n"
        f"Diff 范围：origin/{target_branch}...origin/{source_branch}\n"
    )
    return _run_review_common(
        repo_url=repo_url,
        project_id=project_id or project_path,
        project_path=project_path,
        repo_workspace=repo_workspace,
        workspace_key=workspace_key or f"mr-{source_branch}-{target_branch}",
        checkout_branch=source_branch,
        diff_ref=f"origin/{target_branch}...origin/{source_branch}",
        review_context=review_context,
        claude_cmd=claude_cmd,
        timeout=timeout,
        secrets=[token, repo_url],
        skills_root=skills_root,
        model_fallbacks=model_fallbacks,
        retry_delay_seconds=retry_delay_seconds,
    )


def run_claude_review_push(
    repo_url: str,
    branch: str,
    before_sha: str,
    after_sha: str,
    project_path: str,
    repo_workspace: str,
    claude_cmd: str,
    project_id: object = "",
    workspace_key: str = "",
    skills_root: str = _DEFAULT_SKILLS_ROOT,
    timeout: int = 300,
    *,
    token: str = "",
    model_fallbacks: list[str] | None = None,
    retry_delay_seconds: int = 2,
) -> str:
    """Run Claude Code review for a push commit range."""
    logger.info(
        "[Push Review] start branch=%s before=%s after=%s path=%s",
        branch,
        before_sha[:8],
        after_sha[:8],
        project_path,
    )
    review_context = (
        "审查类型：Push\n"
        f"项目：{project_path}\n"
        f"分支：{branch}\n"
        f"Before SHA：{before_sha}\n"
        f"After SHA：{after_sha}\n"
        f"Diff 范围：{before_sha}..{after_sha}\n"
    )
    return _run_review_common(
        repo_url=repo_url,
        project_id=project_id or project_path,
        project_path=project_path,
        repo_workspace=repo_workspace,
        workspace_key=workspace_key or f"push-{branch}-{after_sha[:12]}",
        checkout_branch=branch,
        diff_ref=f"{before_sha}..{after_sha}",
        review_context=review_context,
        claude_cmd=claude_cmd,
        timeout=timeout,
        secrets=[token, repo_url],
        skills_root=skills_root,
        model_fallbacks=model_fallbacks,
        retry_delay_seconds=retry_delay_seconds,
    )
