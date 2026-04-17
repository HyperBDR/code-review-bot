"""Config: read from env only, defaults in code."""

import os

from dotenv import load_dotenv

# Project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Local dev: load env from .env
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_csv(key: str, default: str = "") -> list[str]:
    val = os.environ.get(key, default)
    return [item.strip() for item in val.split(",") if item.strip()]


def resolve_repo_workspace(cfg: dict) -> str:
    """
    Resolve repo_workspace to an absolute path.
    If already absolute, return as-is; otherwise relative to PROJECT_ROOT.
    """
    repo_ws = cfg.get("repo_workspace", "repos")
    return repo_ws if os.path.isabs(repo_ws) else os.path.join(PROJECT_ROOT, repo_ws)


def resolve_claude_skills_root(cfg: dict) -> str:
    """
    Resolve claude_skills_root to an absolute path.
    If already absolute, return as-is; otherwise relative to PROJECT_ROOT.
    """
    skills_root = cfg.get("claude_skills_root", "claude-skills")
    return (
        skills_root
        if os.path.isabs(skills_root)
        else os.path.join(PROJECT_ROOT, skills_root)
    )


def get_config() -> dict:
    """Load config from env, use defaults for missing keys."""
    return {
        "gitlab_url": _env_str("GITLAB_URL", "http://localhost"),
        "gitlab_token": _env_str("GITLAB_TOKEN"),
        "gitlab_webhook_secret": _env_str("GITLAB_WEBHOOK_SECRET"),
        "repo_workspace": _env_str("REPO_WORKSPACE", "repos"),
        "claude_cmd": _env_str("CLAUDE_CMD", "claude"),
        "claude_skills_root": _env_str("CLAUDE_SKILLS_ROOT", "claude-skills"),
        "claude_model_fallbacks": _env_csv(
            "CLAUDE_MODEL_FALLBACKS", "sonnet,haiku,opus"
        ),
        "claude_retry_delay_seconds": _env_int("CLAUDE_RETRY_DELAY_SECONDS", 2),
        "host": _env_str("HOST", "0.0.0.0"),
        "port": _env_int("PORT", 5000),
        "review_timeout": _env_int("REVIEW_TIMEOUT", 600),
        "review_queue_max": _env_int("REVIEW_QUEUE_MAX", 100),
        "review_workers": _env_int("REVIEW_WORKERS", 3),
        "review_project_max_concurrency": _env_int(
            "REVIEW_PROJECT_MAX_CONCURRENCY", 2
        ),
        "api_timeout": _env_int("API_TIMEOUT", 10),
        "log_file": _env_str("LOG_FILE", ""),
    }
