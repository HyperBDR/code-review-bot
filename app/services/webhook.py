"""Webhook logic: Push / MR parsing and background review."""

import logging
from collections.abc import Callable
from urllib.parse import urlparse

from app.config import get_config, resolve_claude_skills_root, resolve_repo_workspace
from app.services import claude_code, gitlab, review_queue

logger = logging.getLogger(__name__)

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


def _url_hostname(url: str) -> str:
    """Return normalized hostname from a URL, or empty string if invalid."""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_gitlab_repo_url(repo_url: str, gitlab_url: str) -> bool:
    """Check that webhook repo URL points to the configured GitLab host."""
    repo_host = _url_hostname(repo_url)
    gitlab_host = _url_hostname(gitlab_url)
    return bool(repo_host and gitlab_host and repo_host == gitlab_host)


def _reject_invalid_repo_url(repo_url: str, gitlab_url: str) -> tuple[str, int] | None:
    """Return an error response if repo_url does not match the GitLab host."""
    if _is_gitlab_repo_url(repo_url, gitlab_url):
        return None

    logger.warning(
        "[Webhook] invalid repository URL host repo_url=%s gitlab_url=%s",
        repo_url,
        gitlab_url,
    )
    _log_webhook_response(400, "Invalid repository URL")
    return "Invalid repository URL", 400


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


def _build_review_task(
    project_id: int,
    commit_sha: str,
    gitlab_url: str,
    token: str,
    api_timeout: int,
    run_review: Callable[[], str],
    comment_formatter: Callable[[str], str],
    *,
    mr_iid: int | None = None,
    dedupe_key: str = "",
    review_type: str = "review",
) -> review_queue.ReviewTask:
    """Build a queued task that owns GitLab status reporting."""

    def _on_start() -> None:
        gitlab.set_commit_status(
            gitlab_url,
            token,
            project_id,
            commit_sha,
            "running",
            "AI code review in progress...",
            api_timeout,
        )

    def _on_success(result: str) -> None:
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

    def _on_timeout() -> None:
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

    def _on_error(exc: Exception) -> None:
        logger.error("%s review failed: %s", review_type, exc)
        _report_review_result(
            gitlab_url,
            token,
            project_id,
            commit_sha,
            success=False,
            description="Processing error",
            comment_body="❌ **System Error**: AI review execution failed",
            api_timeout=api_timeout,
            mr_iid=mr_iid,
        )

    def _on_superseded() -> None:
        gitlab.set_commit_status(
            gitlab_url,
            token,
            project_id,
            commit_sha,
            "success",
            "AI review skipped: superseded by newer commit",
            api_timeout,
        )

    return review_queue.ReviewTask(
        project_id=project_id,
        commit_sha=commit_sha,
        run_review=run_review,
        on_start=_on_start,
        on_success=_on_success,
        on_timeout=_on_timeout,
        on_error=_on_error,
        on_superseded=_on_superseded,
        dedupe_key=dedupe_key,
        review_type=review_type,
        mr_iid=mr_iid,
    )


def _enqueue_review_task(
    task: review_queue.ReviewTask,
    queue_max: int,
    worker_count: int,
    project_concurrency: int,
    gitlab_url: str,
    token: str,
    project_id: int,
    commit_sha: str,
    api_timeout: int,
) -> tuple[str, int]:
    """Enqueue a task and set queued status after acceptance."""

    def _mark_queued() -> None:
        try:
            gitlab.set_commit_status(
                gitlab_url,
                token,
                project_id,
                commit_sha,
                "pending",
                "AI code review queued...",
                api_timeout,
            )
        except Exception:
            logger.exception("failed to set queued status")

    queue = review_queue.get_review_queue(
        queue_max,
        worker_count=worker_count,
        project_concurrency=project_concurrency,
    )
    if not queue.try_enqueue(task, on_accepted=_mark_queued):
        _log_webhook_response(429, "Queue full")
        return "Queue full", 429

    _log_webhook_response(202, "Accepted, review queued")
    return "Accepted, review queued", 202


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
    invalid_repo_response = _reject_invalid_repo_url(repo_url, gitlab_url)
    if invalid_repo_response is not None:
        return invalid_repo_response

    logger.info("[Push] review_timeout=%s api_timeout=%s", review_timeout, api_timeout)
    logger.info(
        "[Push] push event branch=%s before=%s after=%s",
        branch,
        before_sha[:8],
        after_sha[:8],
    )

    def _run() -> str:
        clone_url = claude_code.build_clone_url(repo_url, token)
        repo_workspace = resolve_repo_workspace(cfg)
        claude_skills_root = resolve_claude_skills_root(cfg)
        return claude_code.run_claude_review_push(
            repo_url=clone_url,
            branch=branch,
            before_sha=before_sha,
            after_sha=after_sha,
            project_path=project_path,
            repo_workspace=repo_workspace,
            claude_cmd=cfg.get("claude_cmd", "claude"),
            project_id=project_id,
            workspace_key=f"push-{branch}-{after_sha[:12]}",
            skills_root=claude_skills_root,
            timeout=review_timeout,
            token=token,
            model_fallbacks=cfg.get("claude_model_fallbacks"),
            retry_delay_seconds=cfg.get("claude_retry_delay_seconds", 2),
        )

    task = _build_review_task(
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

    return _enqueue_review_task(
        task,
        cfg.get("review_queue_max", 100),
        cfg.get("review_workers", 3),
        cfg.get("review_project_max_concurrency", 2),
        gitlab_url,
        token,
        project_id,
        after_sha,
        api_timeout,
    )


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
    invalid_repo_response = _reject_invalid_repo_url(repo_url, gitlab_url)
    if invalid_repo_response is not None:
        return invalid_repo_response

    logger.info(
        "[MR] MR #%s source=%s target=%s",
        mr_iid,
        source_branch,
        target_branch,
    )

    def _run() -> str:
        clone_url = claude_code.build_clone_url(repo_url, token)
        repo_workspace = resolve_repo_workspace(cfg)
        claude_skills_root = resolve_claude_skills_root(cfg)
        return claude_code.run_claude_review(
            repo_url=clone_url,
            source_branch=source_branch,
            target_branch=target_branch,
            project_path=project_path,
            repo_workspace=repo_workspace,
            claude_cmd=cfg.get("claude_cmd", "claude"),
            project_id=project_id,
            workspace_key=f"mr-{mr_iid}-{last_commit_sha[:12]}",
            skills_root=claude_skills_root,
            timeout=review_timeout,
            token=token,
            model_fallbacks=cfg.get("claude_model_fallbacks"),
            retry_delay_seconds=cfg.get("claude_retry_delay_seconds", 2),
        )

    task = _build_review_task(
        project_id,
        last_commit_sha,
        gitlab_url,
        token,
        api_timeout,
        _run,
        lambda r: f"🤖 **Code Review Result**:\n\n{r}",
        mr_iid=mr_iid,
        dedupe_key=f"mr:{project_id}:{mr_iid}",
        review_type="MR",
    )

    return _enqueue_review_task(
        task,
        cfg.get("review_queue_max", 100),
        cfg.get("review_workers", 3),
        cfg.get("review_project_max_concurrency", 2),
        gitlab_url,
        token,
        project_id,
        last_commit_sha,
        api_timeout,
    )
