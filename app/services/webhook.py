"""Webhook 业务逻辑：Push / MR 解析、后台审查。"""

import logging
import subprocess
import threading

from app.config import PROJECT_ROOT, get_config, resolve_repo_workspace
from app.services import gitlab, opencode

logger = logging.getLogger(__name__)


def _log_webhook_response(status: int, body: str) -> None:
    """统一记录 webhook 响应出口日志。"""
    logger.info("webhook 响应 -> status=%d body=%s", status, body)


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
    """在后台线程中执行 push 审查逻辑。"""
    logger.info("[Push 后台] 线程启动，开始执行 push 审查")
    try:
        clone_url = opencode.build_clone_url(repo_url, token)
        cfg = get_config()
        repo_workspace = resolve_repo_workspace(cfg)
        review_result = opencode.run_opencode_review_push(
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
        comment_body = (
            f"🤖 **Code Review Result** (push {branch}):\n\n{review_result}"
        )
        gitlab.post_commit_comment(
            gitlab_url, token, project_id, after_sha, comment_body, api_timeout
        )
        desc = (
            "AI 审查通过 (LGTM)" if "LGTM" in review_result.upper() else "AI 审查完成"
        )
        gitlab.set_commit_status(
            gitlab_url,
            token,
            project_id,
            after_sha,
            "success",
            desc,
            api_timeout,
        )
        logger.info("push 审查处理完成，状态已更新。")

    except subprocess.TimeoutExpired:
        gitlab.set_commit_status(
            gitlab_url,
            token,
            project_id,
            after_sha,
            "failed",
            "AI 审查超时",
            api_timeout,
        )
        gitlab.post_commit_comment(
            gitlab_url,
            token,
            project_id,
            after_sha,
            "❌ **System Error**: AI 审查执行超时",
            api_timeout,
        )
        logger.warning("push 审查超时")
    except Exception as exc:
        logger.exception("push webhook 后台处理异常")
        gitlab.set_commit_status(
            gitlab_url,
            token,
            project_id,
            after_sha,
            "failed",
            "处理异常",
            api_timeout,
        )
        gitlab.post_commit_comment(
            gitlab_url,
            token,
            project_id,
            after_sha,
            f"❌ **System Error**: {exc}",
            api_timeout,
        )


def handle_push_webhook(data: dict) -> tuple[str, int]:
    """
    处理 push 事件。返回 (body, status_code)。
    """
    logger.info("[Push] 解析 webhook 数据")
    ref = data.get("ref", "")
    if not ref.startswith("refs/heads/"):
        logger.info("[Push] 跳过：非分支 ref=%s", ref)
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
        logger.warning("[Push] 缺少必要字段 required=%s", required)
        _log_webhook_response(400, "Missing push fields")
        return "Missing push fields", 400

    cfg = get_config()
    token = cfg.get("gitlab_token", "")
    if not token:
        logger.error("[Push] gitlab_token 未配置")
        _log_webhook_response(500, "gitlab_token not configured")
        return "gitlab_token not configured", 500

    gitlab_url = cfg.get("gitlab_url", "").rstrip("/")
    api_timeout = cfg.get("api_timeout", 10)
    review_timeout = cfg.get("review_timeout", 600)
    logger.info("[Push] review_timeout=%s api_timeout=%s", review_timeout, api_timeout)
    logger.info(
        "[Push] 收到 push 事件 branch=%s before=%s after=%s",
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
        "正在进行 AI 代码审查...",
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
    logger.info("[Push] 启动后台线程，立即返回 202")
    thread.start()

    _log_webhook_response(202, "Accepted, review in background")
    return "Accepted, review in background", 202


def handle_mr_webhook(data: dict) -> tuple[str, int]:
    """
    处理 Merge Request 事件。返回 (body, status_code)。
    """
    attrs = data.get("object_attributes", {})
    action = attrs.get("action")
    logger.info("[MR] action=%s state=%s", action, attrs.get("state"))
    accepted_actions = ("open", "reopen", "update", "merge")
    if action is not None and action not in accepted_actions:
        logger.info("[MR] 忽略 action=%s，仅处理 %s", action, accepted_actions)
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
        logger.warning("[MR] 缺少必要字段 required=%s", required)
        _log_webhook_response(400, "Missing MR fields")
        return "Missing MR fields", 400

    cfg = get_config()
    token = cfg.get("gitlab_token", "")
    if not token:
        logger.error("[MR] gitlab_token 未配置")
        _log_webhook_response(500, "gitlab_token not configured")
        return "gitlab_token not configured", 500

    gitlab_url = cfg.get("gitlab_url", "").rstrip("/")
    api_timeout = cfg.get("api_timeout", 10)
    review_timeout = cfg.get("review_timeout", 600)
    logger.info(
        "[MR] 收到 MR #%s source=%s target=%s",
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
        "正在进行 AI 代码审查...",
        api_timeout,
    )

    def _run_mr_review() -> None:
        logger.info("[MR 后台] 线程启动，开始执行 MR 审查")
        try:
            clone_url = opencode.build_clone_url(repo_url, token)
            repo_workspace = resolve_repo_workspace(cfg)
            review_result = opencode.run_opencode_review(
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
            comment_body = f"🤖 **Code Review Result**:\n\n{review_result}"
            gitlab.post_comment(
                gitlab_url, token, project_id, mr_iid, comment_body, api_timeout
            )
            desc = (
                "AI 审查通过 (LGTM)"
                if "LGTM" in review_result.upper()
                else "AI 审查完成"
            )
            gitlab.set_commit_status(
                gitlab_url,
                token,
                project_id,
                last_commit_sha,
                "success",
                desc,
                api_timeout,
            )
            logger.info("MR 审查处理完成，状态已更新。")

        except subprocess.TimeoutExpired:
            gitlab.set_commit_status(
                gitlab_url,
                token,
                project_id,
                last_commit_sha,
                "failed",
                "AI 审查超时",
                api_timeout,
            )
            gitlab.post_comment(
                gitlab_url,
                token,
                project_id,
                mr_iid,
                "❌ **System Error**: AI 审查执行超时",
                api_timeout,
            )
            logger.warning("MR 审查超时")
        except Exception as exc:
            logger.exception("MR webhook 后台处理异常")
            gitlab.set_commit_status(
                gitlab_url,
                token,
                project_id,
                last_commit_sha,
                "failed",
                "处理异常",
                api_timeout,
            )
            gitlab.post_comment(
                gitlab_url,
                token,
                project_id,
                mr_iid,
                f"❌ **System Error**: {exc}",
                api_timeout,
            )

    thread = threading.Thread(target=_run_mr_review, daemon=True)
    logger.info("[MR] 启动后台线程，立即返回 202")
    thread.start()

    _log_webhook_response(202, "Accepted, review in background")
    return "Accepted, review in background", 202
