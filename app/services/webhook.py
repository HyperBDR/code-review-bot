"""Webhook logic: Push / MR parsing and background review."""

import logging
import subprocess
import threading
from collections.abc import Callable

from app.config import PROJECT_ROOT, get_config, resolve_repo_workspace
from app.services import gitlab, opencode

logger = logging.getLogger(__name__)

# Per-project lock: one review per repo at a time, different repos can run concurrently
_repo_locks: dict[int, threading.Lock] = {}
_dict_lock = threading.Lock()


def _get_repo_lock(project_id: int) -> threading.Lock:
    """Get or create the lock for this project (dict access guarded by _dict_lock)."""
    with _dict_lock:
        return _repo_locks.setdefault(project_id, threading.Lock())


def _log_webhook_response(status: int, body: str) -> None:
    """Log webhook response at exit."""
    logger.info("webhook response -> status=%d body=%s", status, body)


def _get_webhook_config() -> tuple[dict, str, str, int, int] | None:
    """Return webhook config; None if token is not configured."""
    cfg = get_config()
    token = cfg.get("gitlab_token", "")
    if not token:
        return None
    gitlab_url = cfg.get("gitlab_url", "").rstrip("/")
    api_timeout = cfg.get("api_timeout", 10)
    review_timeout = cfg.get("review_timeout", 600)
    return (cfg, token, gitlab_url, api_timeout, review_timeout)


def _report_review_result(
    gitlab_url: str,
    token: str,
    project_id: int,
    commit_sha: str,
    success: bool,
    description: str,
    comment_body: str,
    api_timeout: int,
    *,
    mr_iid: int | None = None,
) -> None:
    """Report review result: set commit status and post comment (commit or MR)."""
    state = "success" if success else "failed"
    gitlab.set_commit_status(
        gitlab_url, token, project_id, commit_sha, state, description, api_timeout
    )
    if mr_iid is not None:
        gitlab.post_comment(
            gitlab_url, token, project_id, mr_iid, comment_body, api_timeout
        )
    else:
        gitlab.post_commit_comment(
            gitlab_url, token, project_id, commit_sha, comment_body, api_timeout
        )


def _run_review_under_lock(
    project_id: int,
    commit_sha: str,
    gitlab_url: str,
    token: str,
    api_timeout: int,
    run_review: Callable[[], str],
    comment_formatter: Callable[[str], str],
    *,
    mr_iid: int | None = None,
    review_type: str = "review",
) -> None:
    """
    Run review under repo lock and report result. run_review() returns review text;
    may raise TimeoutExpired or Exception. One repo at a time, different repos concurrent.
    """
    logger.info("[%s background] thread started, running review", review_type)
    lock = _get_repo_lock(project_id)
    with lock:
        try:
            result = run_review()
            desc = (
                "AI review passed (LGTM)"
                if "LGTM" in result.upper()
                else "AI review done"
            )
            _report_review_result(
                gitlab_url,
                token,
                project_id,
                commit_sha,
                success=True,
                description=desc,
                comment_body=comment_formatter(result),
                api_timeout=api_timeout,
                mr_iid=mr_iid,
            )
            logger.info("%s review done, status updated.", review_type)
        except subprocess.TimeoutExpired:
            _report_review_result(
                gitlab_url,
                token,
                project_id,
                commit_sha,
                success=False,
                description="AI review timeout",
                comment_body="❌ **System Error**: AI review execution timed out",
                api_timeout=api_timeout,
                mr_iid=mr_iid,
            )
            logger.warning("%s review timeout", review_type)
        except Exception as exc:
            logger.exception("%s webhook background error", review_type)
            _report_review_result(
                gitlab_url,
                token,
                project_id,
                commit_sha,
                success=False,
                description="Processing error",
                comment_body=f"❌ **System Error**: {exc}",
                api_timeout=api_timeout,
                mr_iid=mr_iid,
            )


def _run_push_review(
    gitlab_url: str,
    token: str,
    project_id: int,
    after_sha: str,
    branch: str,
    before_sha: str,
    repo_url: str,
    project_path: str,
    api_timeout: int,
    review_timeout: int,
) -> None:
    """Run push review in background thread. One repo at a time, different repos concurrent."""

    def _run() -> str:
        clone_url = opencode.build_clone_url(repo_url, token)
        cfg = get_config()
        repo_workspace = resolve_repo_workspace(cfg)
        return opencode.run_opencode_review_push(
            repo_url=clone_url,
            branch=branch,
            before_sha=before_sha,
            after_sha=after_sha,
            project_path=project_path,
            repo_workspace=repo_workspace,
            opencode_cmd=cfg.get("opencode_cmd", "opencode"),
            project_dir=PROJECT_ROOT,
            timeout=review_timeout,
            opencode_log_level=cfg.get("opencode_log_level", "WARN"),
            opencode_model=cfg.get("opencode_model", ""),
        )

    _run_review_under_lock(
        project_id,
        after_sha,
        gitlab_url,
        token,
        api_timeout,
        _run,
        lambda r: f"🤖 **Code Review Result** (push {branch}):\n\n{r}",
        mr_iid=None,
        review_type="Push",
    )


def handle_push_webhook(data: dict) -> tuple[str, int]:
    """
    Handle push event. Returns (body, status_code).
    """
    logger.info("[Push] parsing webhook data")
    ref = data.get("ref", "")
    if not ref.startswith("refs/heads/"):
        logger.info("[Push] skip: non-branch ref=%s", ref)
        _log_webhook_response(200, "Push to non-branch ref, ignored")
        return "Push to non-branch ref, ignored", 200

    branch = ref.replace("refs/heads/", "")
    before_sha = data.get("before", "")
    after_sha = data.get("checkout_sha") or data.get("after", "")

    project = data.get("project", {})
    project_id = project.get("id")
    project_path = project.get("path_with_namespace", str(project_id))
    repo_url = (
        project.get("http_url")
        or project.get("git_http_url")
        or data.get("repository", {}).get("git_http_url", "")
    )

    required = [project_id, repo_url, before_sha, after_sha]
    if not all(required):
        logger.warning("[Push] missing required fields required=%s", required)
        _log_webhook_response(400, "Missing push fields")
        return "Missing push fields", 400

    config = _get_webhook_config()
    if config is None:
        logger.error("[Push] gitlab_token not configured")
        _log_webhook_response(500, "gitlab_token not configured")
        return "gitlab_token not configured", 500
    cfg, token, gitlab_url, api_timeout, review_timeout = config
    logger.info("[Push] review_timeout=%s api_timeout=%s", review_timeout, api_timeout)
    logger.info(
        "[Push] push event branch=%s before=%s after=%s",
        branch,
        before_sha[:8],
        after_sha[:8],
    )

    gitlab.set_commit_status(
        gitlab_url,
        token,
        project_id,
        after_sha,
        "running",
        "AI code review in progress...",
        api_timeout,
    )

    thread = threading.Thread(
        target=_run_push_review,
        kwargs={
            "gitlab_url": gitlab_url,
            "token": token,
            "project_id": project_id,
            "after_sha": after_sha,
            "branch": branch,
            "before_sha": before_sha,
            "repo_url": repo_url,
            "project_path": project_path,
            "api_timeout": api_timeout,
            "review_timeout": review_timeout,
        },
        daemon=True,
    )
    logger.info("[Push] started background thread, returning 202")
    thread.start()

    _log_webhook_response(202, "Accepted, review in background")
    return "Accepted, review in background", 202


def handle_mr_webhook(data: dict) -> tuple[str, int]:
    """
    Handle Merge Request event. Returns (body, status_code).
    """
    attrs = data.get("object_attributes", {})
    action = attrs.get("action")
    logger.info("[MR] action=%s state=%s", action, attrs.get("state"))
    accepted_actions = ("open", "reopen", "update", "merge")
    if action is not None and action not in accepted_actions:
        logger.info("[MR] ignoring action=%s, only handle %s", action, accepted_actions)
        _log_webhook_response(200, "Action ignored")
        return "Action ignored", 200

    project = data.get("project", {})
    project_id = project.get("id")
    mr_iid = attrs.get("iid")
    source_branch = attrs.get("source_branch", "")
    target_branch = attrs.get("target_branch", "")
    last_commit = attrs.get("last_commit", {}) or {}
    last_commit_sha = last_commit.get("id", "")
    repo_url = (
        project.get("http_url_to_repo")
        or project.get("git_http_url")
        or project.get("http_url")
        or attrs.get("source", {}).get("git_http_url")
        or attrs.get("source", {}).get("http_url", "")
    )
    project_path = project.get("path_with_namespace", str(project_id))

    required = [
        project_id,
        mr_iid,
        repo_url,
        source_branch,
        target_branch,
        last_commit_sha,
    ]
    if not all(required):
        logger.warning("[MR] missing required fields required=%s", required)
        _log_webhook_response(400, "Missing MR fields")
        return "Missing MR fields", 400

    config = _get_webhook_config()
    if config is None:
        logger.error("[MR] gitlab_token not configured")
        _log_webhook_response(500, "gitlab_token not configured")
        return "gitlab_token not configured", 500
    cfg, token, gitlab_url, api_timeout, review_timeout = config
    logger.info(
        "[MR] MR #%s source=%s target=%s",
        mr_iid,
        source_branch,
        target_branch,
    )

    gitlab.set_commit_status(
        gitlab_url,
        token,
        project_id,
        last_commit_sha,
        "running",
        "AI code review in progress...",
        api_timeout,
    )

    def _run_mr_review() -> None:
        def _run() -> str:
            clone_url = opencode.build_clone_url(repo_url, token)
            repo_workspace = resolve_repo_workspace(cfg)
            return opencode.run_opencode_review(
                repo_url=clone_url,
                source_branch=source_branch,
                target_branch=target_branch,
                project_path=project_path,
                repo_workspace=repo_workspace,
                opencode_cmd=cfg.get("opencode_cmd", "opencode"),
                opencode_log_level=cfg.get("opencode_log_level", "WARN"),
                opencode_model=cfg.get("opencode_model", ""),
                project_dir=PROJECT_ROOT,
                timeout=review_timeout,
            )

        _run_review_under_lock(
            project_id,
            last_commit_sha,
            gitlab_url,
            token,
            api_timeout,
            _run,
            lambda r: f"🤖 **Code Review Result**:\n\n{r}",
            mr_iid=mr_iid,
            review_type="MR",
        )

    thread = threading.Thread(target=_run_mr_review, daemon=True)
    logger.info("[MR] started background thread, returning 202")
    thread.start()

    _log_webhook_response(202, "Accepted, review in background")
    return "Accepted, review in background", 202
