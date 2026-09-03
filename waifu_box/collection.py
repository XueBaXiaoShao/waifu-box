"""每日老婆交易系统（基于 waifu_state.json 的今日记录）。

只允许交换每天抽到的每日老婆（/waifu 或 /yuzuwaifu 的记录），
每人每天只有一条记录，展示与交易都读同一数据源，不存在卡号错位问题。
角色按其在作品中的定位（role）定稀有度，仅用于展示与排行榜。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import waifu
from .config import config

_lock = threading.RLock()

# 角色定位 → (稀有度名, 星级)
ROLE_RARITY: dict[str, tuple[str, int]] = {
    "primary": ("SSR", 5),
    "main": ("SR", 4),
    "side": ("R", 3),
    "appears": ("N", 2),
}
DEFAULT_RARITY = ("N", 2)

TRADE_TTL_SECONDS = 600  # 交易提议 10 分钟未处理自动过期


def _trades_file() -> Path:
    return Path(config.data_dir) / "waifu_trades.json"


def _load_trades() -> dict[str, Any]:
    try:
        payload = json.loads(_trades_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_trades(payload: dict[str, Any]) -> None:
    path = _trades_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def rarity_for_role(role: str) -> tuple[str, int]:
    """角色定位 → 稀有度：(名称, 星级)。"""
    return ROLE_RARITY.get((role or "").strip().lower(), DEFAULT_RARITY)


def role_of_record(record: dict[str, Any]) -> str:
    """取每日老婆记录的角色定位；记录未存 role 时回查本地资料库。"""
    role = str(record.get("role") or "").strip()
    if role:
        return role
    library_path = record.get("library_path")
    if library_path:
        try:
            path = Path(config.library_dir) / str(library_path)
            data = json.loads(path.read_text(encoding="utf-8"))
            return str(data.get("role") or "").strip()
        except (OSError, json.JSONDecodeError):
            return ""
    return ""


def rarity_of_record(record: dict[str, Any]) -> tuple[str, int]:
    """每日老婆记录 → 稀有度：(名称, 星级)。"""
    return rarity_for_role(role_of_record(record))


def waifu_display(record: dict[str, Any]) -> str:
    """每日老婆记录的展示文本（带稀有度）。"""
    rarity, stars = rarity_of_record(record)
    name = str(record.get("original") or record.get("name") or "未知")
    vns = record.get("vns") or []
    game = vns[0].get("title") if vns and vns[0].get("title") else ""
    line = f"{'★' * stars} {rarity} {name}"
    if game:
        line += f"（{game}）"
    return line


def require_yuzu_waifu(user_id: int) -> dict[str, Any]:
    """返回用户今天的柚子社每日老婆；未抽或不是柚子社抛 ValueError。"""
    record = waifu.get_today_waifu(user_id)
    if record is None:
        raise ValueError("你还没有抽今天的每日老婆，先抽一张 /yuzuwaifu 吧")
    if str(record.get("source") or "") != "yuzu":
        raise ValueError(
            "你今天的每日老婆是 /waifu 抽的其他会社角色，暂时不能交易"
        )
    return record


def _new_trade_id() -> str:
    return uuid.uuid4().hex[:8].upper()


def propose_trade(
    proposer_id: int,
    target_id: int,
) -> dict[str, Any]:
    """发起交易：提议用双方的今日柚子社每日老婆互换；双方都必须是柚子社。"""
    if proposer_id == target_id:
        raise ValueError("不能和自己交易")
    require_yuzu_waifu(proposer_id)
    try:
        require_yuzu_waifu(target_id)
    except ValueError:
        raise ValueError("对方今天还没有柚子社每日老婆，暂时不能交易") from None
    now = datetime.now()
    trade: dict[str, Any] = {
        "id": _new_trade_id(),
        "proposer": proposer_id,
        "target": target_id,
        "created_at": now.isoformat(timespec="seconds"),
        "expires_at": (now.timestamp() + TRADE_TTL_SECONDS),
        "status": "pending",
    }
    with _lock:
        payload = _load_trades()
        trades = payload.setdefault("trades", [])
        if not isinstance(trades, list):
            trades = []
            payload["trades"] = trades
        trades.append(trade)
        _write_trades(payload)
    return trade


def get_trade(trade_id: str) -> dict[str, Any] | None:
    for trade in _load_trades().get("trades", []):
        if isinstance(trade, dict) and trade.get("id") == trade_id:
            return trade
    return None


def _expire_trades(payload: dict[str, Any]) -> int:
    """惰性清理过期交易；返回清理数量。"""
    trades = payload.get("trades")
    if not isinstance(trades, list):
        return 0
    now = time.time()
    before = len(trades)
    payload["trades"] = [
        trade
        for trade in trades
        if not (
            isinstance(trade, dict)
            and trade.get("status") == "pending"
            and float(trade.get("expires_at") or 0) <= now
        )
    ]
    return before - len(payload["trades"])


def accept_trade(
    trade_id: str, user_id: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """接受交易：必须由目标用户操作；成功互换双方的今日老婆。

    返回 (对方换来的老婆, 自己给出的老婆, trade)。交换与交易落库在同一
    把锁内原子完成，展示永远读取 waifu_state.json 同一数据源。
    """
    with _lock:
        payload = _load_trades()
        _expire_trades(payload)
        trade = None
        for item in payload.get("trades", []):
            if isinstance(item, dict) and item.get("id") == trade_id:
                trade = item
                break
        if trade is None:
            raise ValueError("交易不存在或已过期")
        if trade.get("status") != "pending":
            raise ValueError("交易已被处理")
        if int(trade.get("target") or 0) != user_id:
            raise ValueError("只有交易对方可以接受")
        if float(trade.get("expires_at") or 0) <= time.time():
            raise ValueError("交易已过期")
        proposer_id = int(trade["proposer"])
        try:
            proposer_record = waifu.get_today_waifu(proposer_id)
            target_record = waifu.get_today_waifu(user_id)
            if proposer_record is None or target_record is None:
                raise ValueError("有一方今天还没抽每日老婆，交易失效")
            if (
                str(proposer_record.get("source") or "") != "yuzu"
                or str(target_record.get("source") or "") != "yuzu"
            ):
                raise ValueError("交易对象不是柚子社每日老婆，交易失效")
            waifu.swap_today_waifu(proposer_id, user_id)
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        trade["status"] = "done"
        trade["completed_at"] = datetime.now().isoformat(timespec="seconds")
        _write_trades(payload)
        return proposer_record, target_record, trade


def reject_trade(trade_id: str, user_id: int) -> dict[str, Any]:
    """拒绝交易；必须由目标用户操作。"""
    with _lock:
        payload = _load_trades()
        _expire_trades(payload)
        for trade in payload.get("trades", []):
            if isinstance(trade, dict) and trade.get("id") == trade_id:
                if trade.get("status") != "pending":
                    raise ValueError("交易已被处理")
                if int(trade.get("target") or 0) != user_id:
                    raise ValueError("只有交易对方可以拒绝")
                trade["status"] = "rejected"
                trade["rejected_at"] = datetime.now().isoformat(timespec="seconds")
                _write_trades(payload)
                return trade
    raise ValueError("交易不存在或已过期")


def cancel_trade(trade_id: str, user_id: int) -> dict[str, Any]:
    """撤销自己发起的未处理交易。"""
    with _lock:
        payload = _load_trades()
        _expire_trades(payload)
        for trade in payload.get("trades", []):
            if isinstance(trade, dict) and trade.get("id") == trade_id:
                if trade.get("status") != "pending":
                    raise ValueError("交易已被处理")
                if int(trade.get("proposer") or 0) != user_id:
                    raise ValueError("只有发起人可以撤销")
                trade["status"] = "cancelled"
                trade["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
                _write_trades(payload)
                return trade
    raise ValueError("交易不存在或已过期")


def pending_trades(user_id: int) -> list[dict[str, Any]]:
    """该用户涉及（发起或目标）的未处理交易。"""
    result: list[dict[str, Any]] = []
    for trade in _load_trades().get("trades", []):
        if not isinstance(trade, dict) or trade.get("status") != "pending":
            continue
        if int(trade.get("proposer") or 0) == user_id or int(
            trade.get("target") or 0
        ) == user_id:
            result.append(trade)
    return result


def pending_incoming(user_id: int) -> list[dict[str, Any]]:
    """等待该用户接受/拒绝的交易（自己是目标）。"""
    return [
        trade
        for trade in pending_trades(user_id)
        if int(trade.get("target") or 0) == user_id
    ]


def pending_outgoing(user_id: int) -> list[dict[str, Any]]:
    """该用户发起的、还没被处理的交易（自己可撤销）。"""
    return [
        trade
        for trade in pending_trades(user_id)
        if int(trade.get("proposer") or 0) == user_id
    ]


def ranking(records: list[tuple[int, dict[str, Any]]]) -> list[tuple[int, int, str]]:
    """按今日老婆稀有度排行：[(user_id, 星级, 稀有度名)]，按星级降序。"""
    entries: list[tuple[int, int, str]] = []
    for user_id, record in records:
        rarity, stars = rarity_of_record(record)
        entries.append((int(user_id), int(stars), rarity))
    entries.sort(key=lambda item: (-item[1], item[0]))
    return entries