"""角色图鉴：记录每位用户抽到过的全部角色。

抽卡（/waifu、/yuzuwaifu、2025 池）自动收录到图鉴；同角色只记录一次，
首次抽到时间即收录时间。图鉴数据持久化在 waifu_collection.json。

历史兼容：首次运行时把 waifu_state.json 中尚存的记录导入图鉴
（旧数据每日覆盖导致的历史角色无法完全找回，仅能导入现存记录）。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from . import companies, waifu
from .config import config

_lock = threading.RLock()
_loaded = False

# {str(user_id): {str(character_id): record}}
_collections: dict[str, dict[str, dict[str, Any]]] = {}


def _book_file() -> Path:
    return Path(config.data_dir) / "waifu_collection.json"


def _load_persisted() -> dict[str, dict[str, dict[str, Any]]]:
    try:
        payload = json.loads(_book_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    data = payload.get("users") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _save_persisted() -> None:
    path = _book_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {"version": 1, "users": _collections},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _ensure_loaded() -> None:
    """首次调用时载入持久化图鉴，并导入 waifu_state 中现存的历史记录。"""
    global _loaded, _collections
    if _loaded:
        return
    _collections = _load_persisted()
    # 把 waifu_state.json 中现存的记录导入图鉴（历史兼容，幂等）
    for uid, record in waifu._load().get("users", {}).items():
        if not isinstance(record, dict):
            continue
        cid = str(record.get("character_id") or "").strip()
        if not cid:
            continue
        user = _collections.setdefault(str(uid), {})
        if cid not in user:
            user[cid] = _entry_from_record(record, first_seen=str(record.get("date") or ""))
    _loaded = True


def _entry_from_record(record: dict[str, Any], first_seen: str = "") -> dict[str, Any]:
    """从抽卡记录生成图鉴条目（保留渲染卡片所需的完整字段）。"""
    vns = record.get("vns") or []
    if not isinstance(vns, list):
        vns = []
    entry: dict[str, Any] = {
        "character_id": str(record.get("character_id") or ""),
        "name": str(record.get("name") or record.get("original") or record.get("character_id") or ""),
        "original": str(record.get("original") or ""),
        "source": str(record.get("source") or "waifu"),
        "vns": [
            {"id": str(vn.get("id") or ""), "title": str(vn.get("title") or "")}
            for vn in vns
            if isinstance(vn, dict)
        ],
        "first_seen": first_seen,
        "role": str(record.get("role") or ""),
        "image_url": str(record.get("image_url") or ""),
        "cn_name": str(record.get("cn_name") or ""),
        "roman": str(record.get("roman") or ""),
    }
    if record.get("library_path"):
        entry["library_path"] = str(record["library_path"])
    return entry


def rec_collect(user_id: int, record: dict[str, Any]) -> bool:
    """收录一次抽卡记录；新角色返回 True，已有角色返回 False（幂等）。"""
    cid = str(record.get("character_id") or "").strip()
    if not cid:
        return False
    with _lock:
        _ensure_loaded()
        user = _collections.setdefault(str(user_id), {})
        if cid in user:
            return False
        user[cid] = _entry_from_record(
            record,
            first_seen=datetime.now().isoformat(timespec="seconds"),
        )
        _save_persisted()
        return True


def rec_collect_id(
    user_id: int,
    character_id: str,
    name: str = "",
    original: str = "",
    source: str = "waifu",
    vns: list[dict[str, Any]] | None = None,
    role: str = "",
    library_path: str = "",
    image_url: str = "",
    cn_name: str = "",
    roman: str = "",
) -> bool:
    """按字段收录（抽卡命令的轻量入口）；返回是否为新角色。"""
    cid = str(character_id or "").strip()
    if not cid:
        return False
    record = {
        "character_id": cid,
        "name": name or cid,
        "original": original or name or cid,
        "source": source,
        "vns": vns or [],
        "role": role,
        "image_url": image_url,
        "cn_name": cn_name,
        "roman": roman,
    }
    if library_path:
        record["library_path"] = library_path
    return rec_collect(user_id, record)


def user_collection(user_id: int) -> dict[str, dict[str, Any]]:
    """指定用户的图鉴：{character_id: record}。"""
    with _lock:
        _ensure_loaded()
        return dict(_collections.get(str(user_id), {}))


def sync_from_state(user_id: int) -> bool:
    """把用户 waifu_state 中的当前记录补录进图鉴（幂等）。

    用于修复遗漏收录（如历史交易获得的角色）；返回是否补录了新角色。
    """
    record = waifu._load().get("users", {}).get(str(user_id))
    if not isinstance(record, dict):
        return False
    return rec_collect(user_id, record)


def search_collection(
    user_id: int,
    keyword: str,
    only_yuzu: bool = False,
    company_source: str | None = None,
) -> list[dict[str, Any]]:
    """在图鉴中检索角色。

    支持：角色名/原名/中文名/罗马音/作品名模糊匹配；纯数字时按
    图鉴列表顺序（固定会社在前）取序号（1 起）。only_yuzu=True 时只搜
    柚子社；company_source 指定固定会社入口（yuzu/key/saga/purple）。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    filter_source = "yuzu" if only_yuzu else company_source
    if keyword.isdigit():
        ordered = list(_ordered_rows(user_collection(user_id)))
        if filter_source:
            ordered = [
                r for r in ordered if _entry_matches_source(r, filter_source)
            ]
        index = int(keyword) - 1
        if 0 <= index < len(ordered):
            return [ordered[index]]
        return []
    lower = keyword.lower()
    matches: list[dict[str, Any]] = []
    for entry in user_collection(user_id).values():
        if filter_source and not _entry_matches_source(entry, filter_source):
            continue
        name = str(entry.get("name") or entry.get("original") or "").lower()
        original = str(entry.get("original") or "").lower()
        cn_name = str(entry.get("cn_name") or "").lower()
        roman = str(entry.get("roman") or "").lower()
        vns = entry.get("vns") or []
        game_titles = " ".join(
            str(vn.get("title") or "") for vn in vns if isinstance(vn, dict)
        ).lower()
        if (
            lower in name
            or lower in original
            or lower in cn_name
            or lower in roman
            or lower in game_titles
        ):
            matches.append(entry)
    # 名字精确匹配优先，其次匹配长度
    matches.sort(
        key=lambda r: (
            0 if keyword == str(r.get("name") or r.get("original") or "").lower() else 1,
            len(keyword),
        )
    )
    return matches


def _ordered_rows(book: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """图鉴展示顺序：固定会社入口在前，其余按收录时间倒序。"""
    order = {
        source: index
        for index, source in enumerate(companies.FIXED_WAIFU_COMPANIES)
    }
    rows = list(book.values())
    rows.sort(key=lambda r: str(r.get("first_seen") or ""), reverse=True)
    rows.sort(
        key=lambda r: order.get(
            str(r.get("source") or ""), len(order)
        )
    )
    return rows


def collection_size(user_id: int) -> int:
    """图鉴收录的角色数。"""
    return len(user_collection(user_id))


_company_id_cache: dict[str, set[str]] = {}


def _company_ids_for_source(source: str) -> set[str]:
    """固定会社入口对应的本地库厂商 ID 集合。"""
    company_key = companies.FIXED_WAIFU_COMPANIES.get(source)
    if not company_key:
        return set()
    cached = _company_id_cache.get(company_key)
    if cached is not None:
        return cached
    from . import library

    ids: set[str] = set()
    if library.ensure_index():
        search_names = [
            str(name)
            for name in companies.COMPANIES[company_key]["search"]
        ]
        ids = set(library.resolve_company_ids(search_names))
    if not ids and company_key == "yuzusoft":
        ids = {"p98", "p12215"}
    if ids:
        _company_id_cache[company_key] = ids
    return ids


def _entry_matches_source(entry: dict[str, Any], source: str) -> bool:
    """图鉴条目是否属于某个固定会社入口。

    优先按本地库 company_ids 判断（/waifu 抽到的同会社角色也算），
    本地库缺失时回退按抽卡来源判断。
    """
    if str(entry.get("source") or "") == source:
        return True
    company_ids = _company_ids_for_source(source)
    if not company_ids or not entry.get("library_path"):
        return False
    path = Path(config.library_dir) / str(entry["library_path"])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    ids = {str(item) for item in data.get("company_ids") or []}
    return bool(ids & company_ids)


def _is_yuzu_entry(entry: dict[str, Any]) -> bool:
    """图鉴条目是否柚子社角色：优先按本地库会社判断，回退按入口。"""
    return _entry_matches_source(entry, "yuzu")


def company_progress(
    user_id: int, source: str
) -> tuple[int, int] | None:
    """固定会社收集进度 (已收集, 本地库总数)；库未索引返回 None。"""
    from . import library

    if not library.ensure_index():
        return None
    company_ids = _company_ids_for_source(source)
    if not company_ids:
        return None
    total = library.count_characters(company_ids=list(company_ids))
    if total <= 0:
        return None
    book = user_collection(user_id)
    collected = sum(
        1 for record in book.values() if _entry_matches_source(record, source)
    )
    return collected, total


def yuzu_progress(user_id: int) -> tuple[int, int] | None:
    """柚子社收集进度 (已收集, 本地库总数)；库未索引返回 None。"""
    return company_progress(user_id, "yuzu")


def usage_text() -> str:
    """图鉴检视用法说明。"""
    return (
        "【图鉴用法】\n"
        "- /waifu collection —— 查看我的图鉴列表（带序号）\n"
        "- /waifu collection yuzu —— 只看柚子社角色\n"
        "- /keywaifu collection —— 只看 Key 角色\n"
        "- /sagawaifu collection —— 只看 SAGA PLANETS 角色\n"
        "- /purplewaifu collection —— 只看 Purple software 角色\n"
        "- /waifu collection <序号> —— 按列表序号查看角色卡片\n"
        "- /waifu collection <名字> —— 按名字检索（支持日文名/中文名/罗马音/作品名）\n"
        "- 抽到过的角色自动收录，重复抽到不会重复计入"
    )


def enrich_from_library(user_id: int) -> int:
    """从本地资料库补全图鉴条目的中文名/罗马音/定位；返回补全数。

    旧图鉴数据（或收录时本地库未索引的角色）可能在收藏后才有
    cn_name/roman/role，调用方在检视前跑一次即可。
    role 用于稀有度展示（primary→SSR 等），缺失会被判为默认稀有度。
    """
    from . import library

    if not library.ensure_index():
        return 0
    updated = 0
    with _lock:
        _ensure_loaded()
        user = _collections.setdefault(str(user_id), {})
        for entry in user.values():
            if not isinstance(entry, dict):
                continue
            cid = str(entry.get("character_id") or "")
            if not cid:
                continue
            need = False
            if not str(entry.get("cn_name") or "").strip():
                need = True
            if not str(entry.get("roman") or "").strip():
                need = True
            if not str(entry.get("role") or "").strip():
                need = True
            if not need:
                continue
            character = library.get_character_by_id(cid)
            if character is None:
                continue
            cn = str(getattr(character, "cn_name", "") or "").strip()
            roman = str((character.data or {}).get("vndb_name") or "").strip()
            role = str((character.data or {}).get("role") or "").strip()
            changed = False
            if cn and not str(entry.get("cn_name") or "").strip():
                entry["cn_name"] = cn
                changed = True
            if roman and not str(entry.get("roman") or "").strip():
                entry["roman"] = roman
                changed = True
            if role and not str(entry.get("role") or "").strip():
                entry["role"] = role
                changed = True
            if changed:
                updated += 1
        if updated:
            _save_persisted()
        return updated


ROLE_RARITY: dict[str, tuple[str, int]] = {
    "primary": ("SSR", 5),
    "main": ("SR", 4),
    "side": ("R", 3),
    "appears": ("N", 2),
}


def _rarity_of_entry(entry: dict[str, Any]) -> str:
    role = str(entry.get("role") or "").strip().lower()
    if not role:
        # 兜底：条目缺 role 时回查本地资料库（旧图鉴数据）
        try:
            from . import library

            character = library.get_character_by_id(
                str(entry.get("character_id") or "")
            )
            if character is not None:
                role = str((character.data or {}).get("role") or "").strip().lower()
        except Exception:
            role = ""
    rarity, _ = ROLE_RARITY.get(role, ("N", 2))
    return rarity


def collection_text(
    user_id: int,
    only_yuzu: bool = False,
    company_source: str | None = None,
) -> str:
    """图鉴展示文本；only_yuzu/company_source 用于只看固定会社。"""
    book = user_collection(user_id)
    filter_source = "yuzu" if only_yuzu else company_source
    if not book:
        return "图鉴还是空的，快用 /waifu、/yuzuwaifu 或会社专属入口抽卡吧\n" + usage_text()
    rows: list[dict[str, Any]] = []
    counts = {source: 0 for source in companies.FIXED_WAIFU_COMPANIES}
    normal_count = 0
    for entry in book.values():
        src = str(entry.get("source") or "waifu")
        if src in counts:
            counts[src] += 1
        else:
            normal_count += 1
        if filter_source and not _entry_matches_source(entry, filter_source):
            continue
        rows.append(entry)
    if not rows:
        if filter_source:
            label = companies.FIXED_WAIFU_LABELS.get(filter_source, "该会社")
            return f"还没有{label}角色入库"
        return "图鉴还是空的"
    # 固定会社入口在前，其余按首次收录时间倒序
    rows = _ordered_rows({str(r.get("character_id") or ""): r for r in rows})
    if filter_source:
        label = companies.FIXED_WAIFU_LABELS.get(filter_source, "会社")
        header = f"【{label}图鉴】共 {len(rows)} 位"
        progress = company_progress(user_id, filter_source)
        if progress is not None:
            header += f"\n{label}收藏进度：{progress[0]}/{progress[1]}"
    else:
        short_labels = {
            "yuzu": "柚子",
            "key": "Key",
            "saga": "SAGA",
            "purple": "Purple",
        }
        parts = [
            f"{short_labels[source]} {counts[source]}"
            for source in companies.FIXED_WAIFU_COMPANIES
        ]
        parts.append(f"常规 {normal_count}")
        header = (
            f"【我的角色图鉴】共 {len(book)} 位（"
            + " / ".join(parts)
            + "）"
        )
        progress = yuzu_progress(user_id)
        if progress is not None:
            header += f"\n柚子社收藏进度：{progress[0]}/{progress[1]}"
    lines = [header]
    for index, entry in enumerate(rows[:40], start=1):
        name = str(entry.get("name") or entry.get("original") or entry.get("character_id"))
        cn_name = str(entry.get("cn_name") or "").strip()
        if cn_name and cn_name != name:
            name = f"{cn_name}（{name}）"
        vns = entry.get("vns") or []
        game = vns[0].get("title") if vns and vns[0].get("title") else ""
        src = str(entry.get("source") or "")
        tag = companies.FIXED_WAIFU_TAGS.get(src, "常")
        rarity = _rarity_of_entry(entry)
        line = f"{index}. [{tag}][{rarity}] {name}"
        if game:
            line += f"（{game}）"
        lines.append(line)
    if len(rows) > 40:
        lines.append(f"……（还有 {len(rows) - 40} 位未展示）")
    lines.append("发数字或名字查看角色卡片：/waifu collection <序号|名字>")
    return "\n".join(lines)