"""waifu LRU 使用记录：character_id -> 最近使用时间。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from .config import config

_lock = threading.Lock()


def _usage_file() -> Path:
    return Path(config.data_dir) / "waifu_usage.json"


def _test_usage_file() -> Path:
    return Path(config.data_dir) / "waifu_test_usage.json"


def _load_path(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_path(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load() -> dict:
    return _load_path(_usage_file())


def _save(payload: dict) -> None:
    _save_path(payload, _usage_file())


def usage_map() -> dict[str, str]:
    """返回 {character_id: 最近使用时间}。"""
    return _load().get("usage", {})


def mark_used(character_id: str) -> None:
    with _lock:
        payload = _load()
        payload.setdefault("usage", {})[character_id] = datetime.now().isoformat()
        _save(payload)


def last_used(character_id: str) -> str | None:
    return usage_map().get(character_id)


def test_used_today(user_id: int) -> bool:
    """/waifu test 当日是否已用过（每人每天限 1 次）。"""
    day = datetime.now().strftime("%Y-%m-%d")
    payload = _load_path(_test_usage_file())
    return str(user_id) in (payload.get(day) or {})


def mark_test_used(user_id: int) -> None:
    """记录 /waifu test 当日使用。"""
    with _lock:
        payload = _load_path(_test_usage_file())
        day = datetime.now().strftime("%Y-%m-%d")
        payload.setdefault(day, {})[str(user_id)] = datetime.now().isoformat()
        _save_path(payload, _test_usage_file())
