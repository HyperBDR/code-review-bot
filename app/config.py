"""配置：仅从环境变量读取，代码内提供默认值。"""

import os

from dotenv import load_dotenv

# 项目根目录（包含 .opencode 的目录）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 本地开发：从 .env 加载环境变量
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


def resolve_repo_workspace(cfg: dict) -> str:
    """
    解析 repo_workspace 为绝对路径。
    若配置为绝对路径则原样返回，否则相对于 PROJECT_ROOT。
    """
    repo_ws = cfg.get("repo_workspace", "repos")
    return repo_ws if os.path.isabs(repo_ws) else os.path.join(PROJECT_ROOT, repo_ws)


def get_config() -> dict:
    """从环境变量加载配置，缺失用默认值。"""
    return {
        "gitlab_url": _env_str("GITLAB_URL", "http://localhost"),
        "gitlab_token": _env_str("GITLAB_TOKEN"),
        "repo_workspace": _env_str("REPO_WORKSPACE", "repos"),
        "opencode_cmd": _env_str("OPENCODE_CMD", "opencode"),
        "opencode_log_level": _env_str("OPENCODE_LOG_LEVEL", "WARN"),
        "opencode_model": _env_str("OPENCODE_MODEL", ""),
        "host": _env_str("HOST", "0.0.0.0"),
        "port": _env_int("PORT", 5000),
        "review_timeout": _env_int("REVIEW_TIMEOUT", 600),
        "api_timeout": _env_int("API_TIMEOUT", 10),
        "log_file": _env_str("LOG_FILE", ""),
    }
