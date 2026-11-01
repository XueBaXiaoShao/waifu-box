"""长文彩蛋 /nagato 的每人每日上限。"""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
from typing import Any

from .config import config

DEFAULT_LIMIT = 3
_lock = threading.Lock()


def _file() -> Path:
    return Path(config.data_dir) / "natsume_state.json"


def _today() -> str:
    return date.today().isoformat()


def _load() -> dict[str, Any]:
    try:
        payload = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save(payload: dict[str, Any]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _normalized(payload: dict[str, Any]) -> dict[str, Any]:
    raw_limit = payload.get("limit")
    if not isinstance(raw_limit, int) or isinstance(raw_limit, bool):
        raw_limit = DEFAULT_LIMIT
    users = payload.get("users")
    if not isinstance(users, dict) or payload.get("date") != _today():
        users = {}
    return {
        "version": 1,
        "limit": max(0, raw_limit),
        "date": _today(),
        "users": users,
    }


def limit() -> int:
    with _lock:
        return int(_normalized(_load())["limit"])


def set_limit(value: int) -> int:
    with _lock:
        payload = _normalized(_load())
        payload["limit"] = max(0, int(value))
        _save(payload)
        return int(payload["limit"])


def consume(user_id: int) -> tuple[bool, int, int]:
    """尝试消耗一次触发额度，返回（是否允许，已用次数，上限）。"""
    with _lock:
        payload = _normalized(_load())
        cap = int(payload["limit"])
        if cap <= 0:
            return True, 0, 0
        users: dict[str, Any] = payload["users"]
        key = str(int(user_id))
        try:
            used = int(users.get(key) or 0)
        except (TypeError, ValueError):
            used = 0
        if used >= cap:
            return False, used, cap
        users[key] = used + 1
        _save(payload)
        return True, used + 1, cap
