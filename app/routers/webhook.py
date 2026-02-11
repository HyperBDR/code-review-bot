"""Webhook 路由：/webhook、/health。"""

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
    处理 GitLab Webhook（Merge Request 或 Push）。
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    logger.info(
        "webhook 请求 -> method=%s path=%s object_kind=%s",
        request.method,
        request.url.path,
        data.get("object_kind", "?"),
    )

    object_kind = data.get("object_kind")
    logger.info("[Webhook] 事件类型 object_kind=%s", object_kind)

    if object_kind == "push":
        logger.info("[Webhook] 分发到 push 处理器")
        body, status = webhook_service.handle_push_webhook(data)
        return PlainTextResponse(content=body, status_code=status)

    if object_kind != "merge_request":
        logger.info("[Webhook] 不支持的事件类型，忽略")
        return PlainTextResponse(
            content="Not a supported event",
            status_code=200,
        )

    logger.info("[Webhook] 分发到 MR 处理器")
    body, status = webhook_service.handle_mr_webhook(data)
    return PlainTextResponse(content=body, status_code=status)


@router.get("/health")
async def health() -> dict:
    """健康检查端点。"""
    return {"status": "ok"}
