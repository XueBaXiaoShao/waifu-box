"""/waifu 抽卡统计：最近 N 天被抽次数最多的角色。

历史兼容：首次调用统计时，把 waifu_state.json 中最近 N 天内的
抽卡记录（含角色名）导入历史库，配合后续实时记录的抽卡事件，
保证旧数据也能参与排名。

排序规则：次数降序；次数相同时按五十音序（假名读法）排列，
汉字名（无可读假名）排在假名名之后。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import config
from . import companies, waifu

_lock = threading.Lock()
_history_loaded = False

# 历史记录：{character_id: {"name": str, "count": int, "last_seen": str,
#                            "sort_key": list, "sources": {source: count}}}
# character_id 为 key，天然去重计数（同一角色多次抽到累加）。
_history: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# 五十音排序键
# ---------------------------------------------------------------------------

# 五十音顺（清音 + 浊音/半浊音 + 拗音按惯例并入）
_GOJUON = (
    "あいうえおかがきぎくぐけげこごさざしじすずせぜそぞ"
    "ただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷ"
    "へべぺほぼぽまみむめもゃやゅゆょよらりるれろわをん"
)
# 片假名 → 平假名
_KATA_TO_HIRA = {chr(ord("ァ") + i): chr(ord("ぁ") + i) for i in range(0x60)}
# 平假名 → 五十音序索引
_HIRA_INDEX = {ch: index for index, ch in enumerate(_GOJUON)}


def _kana_sort_key(name: str) -> list[tuple[int, str]]:
    """把名字转成五十音排序键（[(索引, 原字符)]；汉字用 (999, 字符) 排队尾）。

    规则：名字从头部起把连续假名提取成读音串；纯汉字名整串作为
    队列尾。带歧义时直接按字符逐一判断：假名字符取五十音索引，
    汉字取大索引（排在假名之后），同索引按 Unicode 稳定。
    """
    max_kanji = 500
    key: list[tuple[int, str]] = []
    for ch in name:
        if ch in _KATA_TO_HIRA:
            ch = _KATA_TO_HIRA[ch]
        if ch in _HIRA_INDEX:
            key.append((_HIRA_INDEX[ch], ch))
        else:
            key.append((max_kanji, ch))
    return key


def _sort_key_for(entry: dict[str, Any], name: str) -> list[tuple[int, str]]:
    """生成的排序键优先用名字中的假名段；全汉字名排队尾。"""
    cached = entry.get("sort_key")
    if cached:
        return [tuple(item) for item in cached]
    return _kana_sort_key(name)


def _history_file() -> Path:
    return Path(config.data_dir) / "waifu_stats.json"


def _load_persisted() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(_history_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    data = payload.get("history") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _save_persisted() -> None:
    path = _history_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {"version": 1, "history": _history},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _ensure_loaded() -> None:
    """首次调用时载入持久化历史，并导入历史数据（兼容旧数据）。

    历史兼容说明：旧版 waifu_state.json 每用户只保留最新一条记录（每日覆盖），
    waifu_usage.json 也只记每个角色最近一次使用时间，因此旧数据无法还原真实
    抽卡次数。兼容策略：
    - 以 waifu_usage.json 近 N 天内的记录为主数据源（覆盖最全）；
    - 用 waifu_state.json 中的记录补全角色名与日期；
    - 真实次数从本版本起由 record_draw 逐步累积。
    """
    global _history_loaded, _history
    if _history_loaded:
        return
    _history = _load_persisted()
    now = datetime.now(timezone.utc)

    # 1) waifu_usage.json：每个角色最近一次使用时间（近 N 天内的视为本周抽到过）
    from . import waifu_usage

    usage = waifu_usage.usage_map()
    for cid, ts in usage.items():
        cid = str(cid).strip()
        if not cid:
            continue
        dt = _parse_dt(ts)
        if dt is None or now - dt > timedelta(days=7):
            continue
        entry = _history.setdefault(
            cid, {"name": "", "count": 0, "last_seen": ""}
        )
        entry["count"] += 1
        sources = entry.setdefault("sources", {})
        sources["waifu"] = int(sources.get("waifu", 0)) + 1
        if ts > entry["last_seen"]:
            entry["last_seen"] = ts

    # 2) waifu_state.json：补全角色名与日期（含固定会社入口记录；不重复计数）
    state_seen: set[str] = set()
    for uid, record in waifu._load().get("users", {}).items():
        if not isinstance(record, dict):
            continue
        record_date = record.get("date")
        if not record_date:
            continue
        try:
            day = datetime.strptime(str(record_date)[:10], "%Y-%m-%d")
            day = day.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if now - day > timedelta(days=7):
            continue
        cid = str(record.get("character_id") or "").strip()
        if not cid:
            continue
        entry = _history.setdefault(
            cid, {"name": "", "count": 0, "last_seen": ""}
        )
        name = str(record.get("name") or record.get("original") or "").strip()
        if name and not entry["name"]:
            entry["name"] = name
            entry["sort_key"] = _kana_sort_key(name)
        src = str(record.get("source") or "waifu")
        sources = entry.setdefault("sources", {})
        # 仅当角色不在 usage（遗漏的固定会社记录等）时补一次计数；
        # 固定会社记录即使在 usage 中也补 source（独立抽卡入口）
        if cid not in usage or src in companies.FIXED_WAIFU_COMPANIES:
            entry["count"] += 1
            sources[src] = int(sources.get(src, 0)) + 1
        state_seen.add(cid)
        seen = str(record.get("date") or "")
        if seen > entry["last_seen"]:
            entry["last_seen"] = seen
    _history_loaded = True


def _resolve_name(cid: str, fallback: str = "") -> str:
    """从本地资料库解析角色名（失败时用 fallback 或 ID）。"""
    name = fallback.strip()
    if name:
        return name
    try:
        from . import library

        character = library.get_character_by_id(cid)
        if character is not None:
            return str(character.original or character.name or cid)
    except Exception:
        pass
    return cid


def record_draw(
    character_id: str,
    name: str,
    now: datetime | None = None,
    source: str = "waifu",
) -> None:
    """记录一次抽卡事件（实时调用的增量入口）。"""
    cid = str(character_id or "").strip()
    if not cid:
        return
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    with _lock:
        _ensure_loaded()
        entry = _history.setdefault(
            cid, {"name": "", "count": 0, "last_seen": ""}
        )
        clean_name = str(name or "").strip()
        if clean_name and not entry["name"]:
            entry["name"] = clean_name
            entry["sort_key"] = _kana_sort_key(clean_name)
        entry["count"] += 1
        sources = entry.setdefault("sources", {})
        sources[source] = int(sources.get(source, 0)) + 1
        if timestamp > entry["last_seen"]:
            entry["last_seen"] = timestamp
        _save_persisted()


def week_top(
    days: int = 7, limit: int = 10, source: str | None = None
) -> list[dict[str, Any]]:
    """返回最近 days 天内被抽次数最多的角色列表（含名称/次数/最后抽到时间）。

    source 为固定会社入口（yuzu/key/saga/purple）时只统计对应来源；None 统计全部。
    排序：次数降序；次数相同按五十音序（假名读法）升序。
    """
    with _lock:
        _ensure_loaded()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        rows: list[dict[str, Any]] = []
        unresolved: list[str] = []
        for cid, entry in _history.items():
            last = entry.get("last_seen") or ""
            last_dt = _parse_dt(last)
            if last_dt is None or last_dt < cutoff:
                continue
            sources = entry.get("sources") or {}
            if source is not None:
                source_count = int(sources.get(source, 0))
                if source_count <= 0:
                    continue
            else:
                source_count = int(entry.get("count") or 0)
            name = entry.get("name") or ""
            if not name:
                unresolved.append(cid)
                name = cid
            rows.append(
                {
                    "character_id": cid,
                    "name": name,
                    "count": source_count,
                    "last_seen": last,
                    "sort_key": _sort_key_for(entry, name),
                }
            )
        # 批量解析无名角色并回填持久化历史
        for cid in unresolved:
            resolved = _resolve_name(cid)
            if resolved != cid:
                _history[cid]["name"] = resolved
                _history[cid]["sort_key"] = _kana_sort_key(resolved)
                for row in rows:
                    if row["character_id"] == cid:
                        row["name"] = resolved
                        row["sort_key"] = _kana_sort_key(resolved)
        if unresolved:
            _save_persisted()
        rows.sort(
            key=lambda row: (-row["count"], row["sort_key"]),
        )
        return rows[:limit]


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def week_top_text(days: int = 7, limit: int = 10, source: str | None = None) -> str:
    """生成可读的排名文本（source 为固定会社入口时统计该会社）。"""
    rows = week_top(days=days, limit=limit, source=source)
    label = companies.FIXED_WAIFU_LABELS.get(source or "", "")
    if not rows:
        return f"最近 {days} 天还没有{label}抽卡记录"
    header = f"【{label}最近 {days} 天角色抽取排行榜】" if label else f"【最近 {days} 天角色抽取排行榜】"
    lines = [header]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. {row['name']}（{row['count']} 次）"
        )
    lines.append("注：历史旧数据每日只留最后一条，频次从本次更新起精确累积；次数相同按五十音序排列")
    return "\n".join(lines)