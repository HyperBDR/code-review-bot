"""Webhook routes: /webhook, /health."""

import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.config import get_config
from app.services import webhook as webhook_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _authenticate_webhook(request: Request) -> PlainTextResponse | None:
    """Authenticate GitLab webhook requests using X-Gitlab-Token."""
    expected = get_config().get("gitlab_webhook_secret", "")
    if not expected:
        logger.error("[Webhook] gitlab_webhook_secret not configured")
        return PlainTextResponse(
            content="Webhook secret not configured",
            status_code=500,
        )

    actual = request.headers.get("X-Gitlab-Token", "")
    if not hmac.compare_digest(actual, expected):
        logger.warning("[Webhook] unauthorized request: invalid X-Gitlab-Token")
        return PlainTextResponse(content="Unauthorized", status_code=401)

    return None


@router.post("/webhook")
async def webhook_handler(request: Request) -> PlainTextResponse:
    """
    Handle GitLab webhook (Merge Request or Push).
    """
    auth_response = _authenticate_webhook(request)
    if auth_response is not None:
        return auth_response

    try:
        data = await request.json()
    except Exception:
        data = {}

    logger.info(
        "webhook request -> method=%s path=%s object_kind=%s",
        request.method,
        request.url.path,
        data.get("object_kind", "?"),
    )

    object_kind = data.get("object_kind")
    logger.info("[Webhook] event type object_kind=%s", object_kind)

    if object_kind == "push":
        logger.info("[Webhook] dispatching to push handler")
        body, status = webhook_service.handle_push_webhook(data)
        return PlainTextResponse(content=body, status_code=status)

    if object_kind != "merge_request":
        logger.info("[Webhook] unsupported event type, ignoring")
        return PlainTextResponse(
            content="Not a supported event",
            status_code=200,
        )

    logger.info("[Webhook] dispatching to MR handler")
    body, status = webhook_service.handle_mr_webhook(data)
    return PlainTextResponse(content=body, status_code=status)


@router.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
