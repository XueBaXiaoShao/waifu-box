"""深藏彩蛋 /shou help → /waifu help → /shoukeni 的状态。"""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
from typing import Any

from .config import config

_lock = threading.Lock()


def _file() -> Path:
    return Path(config.data_dir) / "shoukeni_state.json"


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
    users = payload.get("users")
    if not isinstance(users, dict) or payload.get("date") != _today():
        users = {}
    return {"version": 1, "date": _today(), "users": users}


def _entry(
    payload: dict[str, Any], user_id: int, create: bool = True
) -> dict[str, Any] | None:
    users = payload["users"]
    key = str(int(user_id))
    entry = users.get(key)
    if not isinstance(entry, dict):
        if not create:
            return None
        entry = {"step": 0, "claimed": False, "used": False}
        users[key] = entry
    entry["step"] = int(entry.get("step") or 0)
    entry["claimed"] = bool(entry.get("claimed"))
    entry["used"] = bool(entry.get("used"))
    return entry


def note_shou_help(user_id: int) -> None:
    with _lock:
        payload = _normalized(_load())
        entry = _entry(payload, user_id)
        if entry is not None and entry["step"] < 1:
            entry["step"] = 1
            _save(payload)


def note_waifu_help(user_id: int) -> None:
    with _lock:
        payload = _normalized(_load())
        entry = _entry(payload, user_id)
        if entry is not None and entry["step"] == 1:
            entry["step"] = 2
            _save(payload)


def claim(user_id: int) -> str:
    """领取每日机会；返回 granted / already / used / not_ready。"""
    with _lock:
        payload = _normalized(_load())
        entry = _entry(payload, user_id)
        if entry is None or entry["step"] < 2:
            return "not_ready"
        if entry["claimed"]:
            return "used" if entry["used"] else "already"
        entry["claimed"] = True
        _save(payload)
        return "granted"


def has_token(user_id: int) -> bool:
    with _lock:
        payload = _normalized(_load())
        entry = _entry(payload, user_id, create=False)
        if entry is None:
            return False
        return bool(entry["claimed"] and not entry["used"])


def consume_token(user_id: int) -> bool:
    with _lock:
        payload = _normalized(_load())
        entry = _entry(payload, user_id, create=False)
        if entry is None or not entry["claimed"] or entry["used"]:
            return False
        entry["used"] = True
        _save(payload)
        return True
