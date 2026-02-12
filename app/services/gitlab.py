"""GitLab API: comments and commit status."""

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
    """Post a comment on the given MR."""
    base = gitlab_url.rstrip("/")
    url = f"{base}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes"
    headers = {"PRIVATE-TOKEN": token}
    logger.info("[MR] Posting comment project_id=%s mr_iid=%s", project_id, mr_iid)
    resp = requests.post(url, json={"body": message}, headers=headers, timeout=timeout)
    logger.info("[MR] Comment response status=%s", resp.status_code)
    if not resp.ok:
        logger.warning("[MR] Comment failed response=%s", resp.text[:500])


def post_commit_comment(
    gitlab_url: str,
    token: str,
    project_id: int,
    sha: str,
    message: str,
    timeout: int = 10,
) -> None:
    """Post a comment on the given commit (used for push review results)."""
    base = gitlab_url.rstrip("/")
    url = f"{base}/api/v4/projects/{project_id}/repository/commits/{sha}/comments"
    headers = {"PRIVATE-TOKEN": token}
    logger.info("[Push] Posting commit comment project_id=%s sha=%s", project_id, sha[:8])
    resp = requests.post(url, json={"note": message}, headers=headers, timeout=timeout)
    logger.info("[Push] Commit comment response status=%s", resp.status_code)
    if not resp.ok:
        logger.warning("[Push] Comment failed response=%s", resp.text[:500])


def set_commit_status(
    gitlab_url: str,
    token: str,
    project_id: int,
    sha: str,
    state: str,
    description: str = "AI Review",
    timeout: int = 10,
) -> None:
    """Set commit status for GitLab pipeline / gate display."""
    url = f"{gitlab_url.rstrip('/')}/api/v4/projects/{project_id}/statuses/{sha}"
    headers = {"PRIVATE-TOKEN": token}
    data = {
        "state": state,
        "context": "code-review-bot",
        "description": description,
    }
    logger.info(
        "[Status] Setting commit status sha=%s state=%s desc=%s",
        sha[:8],
        state,
        description,
    )
    resp = requests.post(url, json=data, headers=headers, timeout=timeout)
    logger.info("[Status] Set result status=%s", resp.status_code)
    if not resp.ok:
        logger.warning("[Status] Set failed response=%s", resp.text[:500])
