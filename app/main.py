"""
GitLab + OpenCode code review service.

Accepts GitLab webhooks (Merge Request or Push), runs local OpenCode with
git-review skill for review, and posts results back to GitLab.
"""

import logging
import logging.handlers
import os

import uvicorn
from fastapi import FastAPI

from app.config import get_config
from app.routers import webhook

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _setup_logging(log_file: str = "") -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # Console handler for docker logs
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        root.addHandler(sh)

    # Optional rotating file handler
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        # 30MB per file, keep 3 backups
        fh = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=30 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)


_setup_logging(get_config().get("log_file", ""))

app = FastAPI(
    title="code-review-bot",
    description="GitLab AI code review via OpenCode",
)

app.include_router(webhook.router, tags=["webhook"])


def main() -> None:
    cfg = get_config()
    host = cfg.get("host", "0.0.0.0")
    port = cfg.get("port", 5000)
    logging.getLogger(__name__).info("Starting server host=%s port=%s", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
