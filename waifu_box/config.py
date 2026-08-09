"""每日老婆独立插件配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    """插件运行配置。"""

    # 数据目录（与 x_admin/galgame-box 共用，默认 /app/data）
    data_dir: str = "data"
    # 请求超时（秒）与重试次数
    request_timeout: int = 30
    request_retries: int = 3
    # 每日定时增量刷新缓存
    cache_refresh_enabled: bool = True
    cache_refresh_time: str = "04:00"
    cache_vn_limit: int = 30

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            data_dir=(
                _env_str("WAIFU_DATA_DIR")
                or _env_str("LOCALSTORE_DATA_DIR")
                or "data"
            ),
            request_timeout=_env_int("WAIFU_REQUEST_TIMEOUT", 30),
            request_retries=_env_int("WAIFU_REQUEST_RETRIES", 3),
            cache_refresh_enabled=_env_bool(
                "WAIFU_CACHE_REFRESH_ENABLED", True
            ),
            cache_refresh_time=_env_str("WAIFU_CACHE_REFRESH_TIME", "04:00"),
            cache_vn_limit=_env_int("WAIFU_CACHE_VN_LIMIT", 30),
        )


config = Config.from_env()
