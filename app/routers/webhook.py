"""Webhook routes: /webhook, /health."""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.services import webhook as webhook_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def webhook_handler(request: Request) -> PlainTextResponse:
    """
    Handle GitLab webhook (Merge Request or Push).
    """
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
