"""GitLab API：评论、Commit 状态。"""

import logging

import requests

logger = logging.getLogger(__name__)


def post_comment(
    gitlab_url: str,
    token: str,
    project_id: int,
    mr_iid: int,
    message: str,
    timeout: int = 10,
) -> None:
    """在指定 MR 下发表评论。"""
    base = gitlab_url.rstrip("/")
    url = f"{base}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes"
    headers = {"PRIVATE-TOKEN": token}
    logger.info("[MR] 发表评论 project_id=%s mr_iid=%s", project_id, mr_iid)
    resp = requests.post(url, json={"body": message}, headers=headers, timeout=timeout)
    logger.info("[MR] 评论结果 status=%s", resp.status_code)
    if not resp.ok:
        logger.warning("[MR] 评论失败 response=%s", resp.text[:500])


def post_commit_comment(
    gitlab_url: str,
    token: str,
    project_id: int,
    sha: str,
    message: str,
    timeout: int = 10,
) -> None:
    """在指定 Commit 下发表评论（用于 push 事件的审查结果）。"""
    base = gitlab_url.rstrip("/")
    url = f"{base}/api/v4/projects/{project_id}/repository/commits/{sha}/comments"
    headers = {"PRIVATE-TOKEN": token}
    logger.info("[Push] 发表 Commit 评论 project_id=%s sha=%s", project_id, sha[:8])
    resp = requests.post(url, json={"note": message}, headers=headers, timeout=timeout)
    logger.info("[Push] Commit 评论结果 status=%s", resp.status_code)
    if not resp.ok:
        logger.warning("[Push] 评论失败 response=%s", resp.text[:500])


def set_commit_status(
    gitlab_url: str,
    token: str,
    project_id: int,
    sha: str,
    state: str,
    description: str = "AI Review",
    timeout: int = 10,
) -> None:
    """设置 Commit 状态，用于 GitLab Pipeline/门禁显示。"""
    url = f"{gitlab_url.rstrip('/')}/api/v4/projects/{project_id}/statuses/{sha}"
    headers = {"PRIVATE-TOKEN": token}
    data = {
        "state": state,
        "context": "code-review-bot",
        "description": description,
    }
    logger.info(
        "[Status] 设置 commit 状态 sha=%s state=%s desc=%s",
        sha[:8],
        state,
        description,
    )
    resp = requests.post(url, json=data, headers=headers, timeout=timeout)
    logger.info("[Status] 设置结果 status=%s", resp.status_code)
    if not resp.ok:
        logger.warning("[Status] 设置失败 response=%s", resp.text[:500])
