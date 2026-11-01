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

# 搜索/分页用的用户级内存索引；收藏变更时整体失效
_index_cache: dict[str, dict[str, Any]] = {}
# 会社角色总数缓存，key 为 (library_dir, library_mtime_ns, company_key)
_company_total_cache: dict[tuple[str, int, str], int] = {}
# 轻量会社索引：只读各会社 公司索引.json，避免加载全量游戏索引
_light_company_index_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
_light_company_ids_cache: dict[tuple[str, int, str], list[str]] = {}


def _invalidate_index(user_id: int | str | None = None) -> None:
    """收藏数据变更后清空搜索索引；指定用户时只清该用户。"""
    if user_id is None:
        _index_cache.clear()
    else:
        _index_cache.pop(str(user_id), None)


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
    _invalidate_index()
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


def _company_ids_from_path(relative_path: str) -> list[str]:
    """从本地资料库相对路径读取 company_ids（不依赖全量索引）。"""
    if not relative_path:
        return []
    path = Path(config.library_dir) / relative_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [
        str(item)
        for item in (data.get("company_ids") or [])
        if str(item).strip()
    ]


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
    company_ids = record.get("company_ids")
    if isinstance(company_ids, list) and company_ids:
        entry["company_ids"] = [
            str(item) for item in company_ids if str(item).strip()
        ]
    if record.get("library_path"):
        entry["library_path"] = str(record["library_path"])
        if not entry.get("company_ids"):
            ids = _company_ids_from_path(str(record["library_path"]))
            if ids:
                entry["company_ids"] = ids
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
        _invalidate_index(user_id)
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
    company_ids: list[str] | None = None,
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
    if company_ids:
        record["company_ids"] = [
            str(item) for item in company_ids if str(item).strip()
        ]
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
    index = _user_index(user_id)
    rows = (
        index["by_source"].get(filter_source, index["rows"])
        if filter_source
        else index["rows"]
    )
    if keyword.isdigit():
        position = int(keyword) - 1
        if 0 <= position < len(rows):
            return [rows[position]]
        return []
    lower = keyword.lower()
    blobs = index["blobs"]
    matches: list[dict[str, Any]] = []
    for entry in rows:
        cid = str(entry.get("character_id") or "")
        if lower in blobs.get(cid, ""):
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


def _search_blob(entry: dict[str, Any]) -> str:
    """预生成搜索文本：名字/原名/中文名/罗马音/作品名。"""
    parts = [
        str(entry.get("name") or ""),
        str(entry.get("original") or ""),
        str(entry.get("cn_name") or ""),
        str(entry.get("roman") or ""),
    ]
    for vn in entry.get("vns") or []:
        if isinstance(vn, dict):
            parts.append(str(vn.get("title") or ""))
    return " ".join(part for part in parts if part).lower()


def _build_user_index(user_id: int) -> dict[str, Any]:
    """构建用户级搜索/分页索引（会社归属、全局序号、搜索文本）。"""
    with _lock:
        _ensure_loaded()
        book = _collections.get(str(user_id), {})
        rows = _ordered_rows(book)
        entry_company_ids = {
            str(cid): _entry_company_ids(entry)
            for cid, entry in book.items()
            if isinstance(entry, dict)
        }
        indices: dict[str, dict[str, int]] = {
            "": {
                str(entry.get("character_id") or ""): position
                for position, entry in enumerate(rows, start=1)
            }
        }
        by_source: dict[str, list[dict[str, Any]]] = {}
        for source in companies.FIXED_WAIFU_COMPANIES:
            company_ids = _company_ids_for_source(source)
            source_rows = [
                entry
                for entry in rows
                if str(entry.get("source") or "") == source
                or (
                    company_ids
                    and entry_company_ids.get(
                        str(entry.get("character_id") or ""), set()
                    )
                    & company_ids
                )
            ]
            by_source[source] = source_rows
            indices[source] = {
                str(entry.get("character_id") or ""): position
                for position, entry in enumerate(source_rows, start=1)
            }
        counts = {source: 0 for source in companies.FIXED_WAIFU_COMPANIES}
        normal_count = 0
        blobs: dict[str, str] = {}
        for entry in rows:
            src = str(entry.get("source") or "waifu")
            if src in counts:
                counts[src] += 1
            else:
                normal_count += 1
            blobs[str(entry.get("character_id") or "")] = _search_blob(entry)
        index = {
            "rows": rows,
            "by_source": by_source,
            "indices": indices,
            "blobs": blobs,
            "counts": counts,
            "normal_count": normal_count,
            "size": len(rows),
        }
        _index_cache[str(user_id)] = index
        return index


def _user_index(user_id: int) -> dict[str, Any]:
    if not _loaded:
        return _build_user_index(user_id)
    cached = _index_cache.get(str(user_id))
    if cached is not None:
        return cached
    return _build_user_index(user_id)


def collection_size(user_id: int) -> int:
    """图鉴收录的角色数（不构建搜索索引）。"""
    with _lock:
        _ensure_loaded()
        return len(_collections.get(str(user_id), {}))


def collection_index(
    user_id: int,
    character_id: str,
    company_source: str | None = None,
) -> int | None:
    """角色在（会社筛选后的）图鉴列表中的 1 起始序号（O(1)）。"""
    index = _user_index(user_id)
    table = index["indices"].get(
        company_source or "", index["indices"][""]
    )
    return table.get(str(character_id or ""))


_company_id_cache: dict[tuple[str, str], set[str]] = {}


def _library_version() -> int:
    try:
        return Path(config.library_dir).stat().st_mtime_ns
    except OSError:
        return 0


def _load_light_company_indexes() -> list[dict[str, Any]]:
    """只读各会社的 公司索引.json，用于快速解析固定会社 ID。"""
    library_dir = str(Path(config.library_dir))
    version = _library_version()
    key = (library_dir, version)
    cached = _light_company_index_cache.get(key)
    if cached is not None:
        return cached
    for old_key in [
        item for item in _light_company_index_cache if item[0] == library_dir and item != key
    ]:
        _light_company_index_cache.pop(old_key, None)
    for old_key in [
        item
        for item in _light_company_ids_cache
        if item[0] == library_dir and item[1] != version
    ]:
        _light_company_ids_cache.pop(old_key, None)
    indexes: list[dict[str, Any]] = []
    root = Path(config.library_dir)
    try:
        directories = sorted(root.iterdir())
    except OSError:
        directories = []
    for company_dir in directories:
        if not company_dir.is_dir():
            continue
        try:
            payload = json.loads(
                (company_dir / "公司索引.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("id"):
            indexes.append(payload)
    _light_company_index_cache[key] = indexes
    return indexes


def _match_company_index(
    payload: dict[str, Any], search_names: list[str]
) -> bool:
    candidates = [
        str(payload.get(key) or "")
        for key in ("vndb_name", "name", "original")
    ]
    lower_candidates = {value.lower() for value in candidates if value}
    compact_candidates = {
        value.replace(" ", "").replace("-", "").lower()
        for value in lower_candidates
    }
    for search_name in search_names:
        name = search_name.strip().lower()
        if not name:
            continue
        compact_name = name.replace(" ", "").replace("-", "")
        if (
            name in lower_candidates
            or compact_name in compact_candidates
            or any(name in candidate for candidate in lower_candidates)
            or any(candidate in name for candidate in lower_candidates)
            or (
                " " in name
                and name.split(" ", 1)[0] in lower_candidates
            )
        ):
            return True
    return False


def _company_ids_file() -> Path:
    return Path(config.data_dir) / "waifu_company_ids.json"


def _load_company_ids_cache() -> dict[str, Any]:
    try:
        payload = json.loads(_company_ids_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_company_ids_cache(
    library_dir: str, version: int, ids: dict[str, list[str]]
) -> None:
    path = _company_ids_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "version": 1,
                "library_dir": library_dir,
                "library_mtime_ns": version,
                "ids": ids,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _resolve_company_ids_light(company_key: str) -> list[str]:
    library_dir = str(Path(config.library_dir))
    version = _library_version()
    cache_key = (library_dir, version, company_key)
    cached = _light_company_ids_cache.get(cache_key)
    if cached is not None:
        return cached
    payload = _load_company_ids_cache()
    if (
        payload.get("library_dir") == library_dir
        and payload.get("library_mtime_ns") == version
        and isinstance(payload.get("ids"), dict)
    ):
        for key, values in payload["ids"].items():
            if isinstance(values, list):
                _light_company_ids_cache[
                    (library_dir, version, str(key))
                ] = [str(value) for value in values]
        cached = _light_company_ids_cache.get(cache_key)
        if cached is not None:
            return cached
    indexes = _load_light_company_indexes()
    all_ids: dict[str, list[str]] = {}
    for key in companies.FIXED_WAIFU_COMPANIES.values():
        search_names = companies.fixed_search_names(key)
        all_ids[key] = [
            str(payload["id"])
            for payload in indexes
            if payload.get("id")
            and _match_company_index(payload, search_names)
        ]
        _light_company_ids_cache[(library_dir, version, key)] = all_ids[key]
    _save_company_ids_cache(library_dir, version, all_ids)
    return all_ids.get(company_key, [])


def _company_ids_for_source(source: str) -> set[str]:
    """固定会社入口对应的本地库厂商 ID 集合（轻量索引优先）。"""
    company_key = companies.FIXED_WAIFU_COMPANIES.get(source)
    if not company_key:
        return set()
    cache_key = (str(Path(config.library_dir)), company_key)
    cached = _company_id_cache.get(cache_key)
    if cached is not None:
        return cached
    ids = set(_resolve_company_ids_light(company_key))
    if not ids:
        from . import library

        if library.ensure_index():
            search_names = companies.fixed_search_names(company_key)
            ids = set(library.resolve_company_ids(search_names))
    if not ids and company_key == "yuzusoft":
        ids = {"p98", "p12215"}
    if ids:
        _company_id_cache[cache_key] = ids
    return ids


def _entry_company_ids(entry: dict[str, Any]) -> set[str]:
    """图鉴条目的本地库会社 ID：优先用收录时保存的 company_ids。"""
    raw = entry.get("company_ids")
    if isinstance(raw, list) and raw:
        return {str(item) for item in raw if str(item).strip()}
    path = entry.get("library_path")
    if not path:
        return set()
    return set(_company_ids_from_path(str(path)))


def _entry_matches_source(entry: dict[str, Any], source: str) -> bool:
    """图鉴条目是否属于某个固定会社入口。

    优先按本地库 company_ids 判断（/waifu 抽到的同会社角色也算），
    本地库缺失时回退按抽卡来源判断。
    """
    if str(entry.get("source") or "") == source:
        return True
    ids = _entry_company_ids(entry)
    company_ids = _company_ids_for_source(source)
    return bool(ids and company_ids and ids & company_ids)


def _is_yuzu_entry(entry: dict[str, Any]) -> bool:
    """图鉴条目是否柚子社角色：优先按本地库会社判断，回退按入口。"""
    return _entry_matches_source(entry, "yuzu")


def _totals_file() -> Path:
    return Path(config.data_dir) / "waifu_company_totals.json"


def _load_totals_cache() -> dict[str, Any]:
    try:
        payload = json.loads(_totals_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_totals_cache(
    library_dir: str, version: int, totals: dict[str, int]
) -> None:
    path = _totals_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "version": 1,
                "library_dir": library_dir,
                "library_mtime_ns": version,
                "totals": totals,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _company_total(source: str) -> int:
    """会社本地库角色总数（进程内 + 持久化缓存）。"""
    company_key = companies.FIXED_WAIFU_COMPANIES.get(source)
    if not company_key:
        return 0
    library_dir = str(Path(config.library_dir))
    version = _library_version()
    cache_key = (library_dir, version, company_key)
    cached = _company_total_cache.get(cache_key)
    if cached is not None:
        return cached
    payload = _load_totals_cache()
    if (
        payload.get("library_dir") == library_dir
        and payload.get("library_mtime_ns") == version
        and isinstance(payload.get("totals"), dict)
    ):
        for key, value in payload["totals"].items():
            if isinstance(value, int):
                _company_total_cache[(library_dir, version, str(key))] = value
        cached = _company_total_cache.get(cache_key)
        if cached is not None:
            return cached
    from . import library

    if not library.ensure_index():
        return 0
    totals: dict[str, int] = {}
    for source_key, key in companies.FIXED_WAIFU_COMPANIES.items():
        company_ids = _company_ids_for_source(source_key)
        totals[key] = (
            library.count_characters(company_ids=list(company_ids))
            if company_ids
            else 0
        )
        _company_total_cache[(library_dir, version, key)] = totals[key]
    _save_totals_cache(library_dir, version, totals)
    return totals.get(company_key, 0)


def company_progress(
    user_id: int, source: str
) -> tuple[int, int] | None:
    """固定会社收集进度 (已收集, 本地库总数)；库未索引返回 None。"""
    total = _company_total(source)
    if total <= 0:
        return None
    index = _user_index(user_id)
    collected = len(index["by_source"].get(source, []))
    return collected, total


def yuzu_progress(user_id: int) -> tuple[int, int] | None:
    """柚子社收集进度 (已收集, 本地库总数)；库未索引返回 None。"""
    return company_progress(user_id, "yuzu")


def usage_text() -> str:
    """图鉴检视用法说明。"""
    return (
        "【图鉴用法】\n"
        "- /waifu collection —— 查看我的图鉴列表（带序号，每页 8 个）\n"
        "- /waifu collection page 2 —— 翻到第 2 页\n"
        "- /waifu collection search <关键词> —— 搜索图鉴中的角色"
        "（名字/中文名/罗马音/作品名）\n"
        "- /waifu collection yuzu —— 只看柚子社角色\n"
        "- /keywaifu collection page 2 —— Key 图鉴第 2 页\n"
        "- /sagawaifu collection —— 只看 SAGA PLANETS 角色\n"
        "- /purplewaifu collection —— 只看 Purple software 角色\n"
        "- /makurawaifu collection —— 只看 Makura 角色\n"
        "- /augustwaifu collection —— 只看 August 角色\n"
        "- /nitroplus collection —— 只看 Nitroplus 角色\n"
        "- /qruppowaifu collection —— 只看 Qruppo 角色\n"
        "- /waifu collection <序号> —— 按列表序号查看角色卡片\n"
        "- /waifu collection <名字> —— 按名字检索（支持日文名/中文名/罗马音/作品名）\n"
        "- 抽到过的角色自动收录，重复抽到不会重复计入"
    )


def enrich_from_library(user_id: int) -> int:
    """从本地资料库补全图鉴条目的中文名/罗马音/定位/会社 ID；返回补全数。

    有 library_path 的条目直接读取角色 JSON，不依赖全量索引；旧条目补全后
    会把 company_ids 持久化，后续搜索/会社筛选不再读文件。
    """
    from . import library

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
            if entry.get("library_path") and not entry.get("company_ids"):
                need = True
            if not need:
                continue
            data: dict[str, Any] | None = None
            if entry.get("library_path"):
                path = Path(config.library_dir) / str(entry["library_path"])
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, dict):
                    data = payload
            if data is None:
                character = library.get_character_by_id(cid)
                if character is not None:
                    data = character.data or {}
            if not isinstance(data, dict):
                continue
            cn = str(data.get("cn_name") or "").strip()
            roman = str(data.get("vndb_name") or "").strip()
            role = str(data.get("role") or "").strip()
            raw_company_ids = data.get("company_ids")
            company_ids = (
                [str(item) for item in raw_company_ids if str(item).strip()]
                if isinstance(raw_company_ids, list)
                else []
            )
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
            if company_ids and not entry.get("company_ids"):
                entry["company_ids"] = company_ids
                changed = True
            if changed:
                updated += 1
        if updated:
            _save_persisted()
            _invalidate_index(user_id)
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
    page: int = 1,
    page_size: int = 8,
    command: str = "/waifu collection",
) -> str:
    """图鉴展示文本；only_yuzu/company_source 用于只看固定会社，page 为页码。"""
    index = _user_index(user_id)
    filter_source = "yuzu" if only_yuzu else company_source
    if index["size"] == 0:
        return "图鉴还是空的，快用 /waifu、/yuzuwaifu 或会社专属入口抽卡吧\n" + usage_text()
    rows = (
        index["by_source"].get(filter_source, index["rows"])
        if filter_source
        else index["rows"]
    )
    if not rows:
        if filter_source:
            label = companies.FIXED_WAIFU_LABELS.get(filter_source, "该会社")
            return f"还没有{label}角色入库"
        return "图鉴还是空的"
    counts = index["counts"]
    normal_count = index["normal_count"]
    book_size = index["size"]
    total = len(rows)
    page_size = max(1, int(page_size))
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page or 1), pages))
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]
    page_note = f"（第 {page}/{pages} 页）" if pages > 1 else ""
    if filter_source:
        label = companies.FIXED_WAIFU_LABELS.get(filter_source, "会社")
        header = f"【{label}图鉴】共 {total} 位{page_note}"
        progress = company_progress(user_id, filter_source)
        if progress is not None:
            header += f"\n{label}收藏进度：{progress[0]}/{progress[1]}"
    else:
        short_labels = {
            "yuzu": "柚子",
            "key": "Key",
            "saga": "SAGA",
            "purple": "Purple",
            "front": "Front",
            "crystal": "Cryst",
            "hook": "HOOK",
            "smee": "SMEE",
            "asa": "ASa",
            "mado": "Mado",
            "pal": "PAL",
            "favo": "FAVO",
            "makura": "枕",
            "august": "八月",
            "nitro": "N+",
            "qruppo": "Qruppo",
        }
        parts = [
            f"{short_labels[source]} {counts[source]}"
            for source in companies.FIXED_WAIFU_COMPANIES
            if counts[source] > 0
        ]
        parts.append(f"常规 {normal_count}")
        page_suffix = f" · 第 {page}/{pages} 页" if pages > 1 else ""
        header = (
            f"【我的角色图鉴】共 {book_size} 位（"
            + " / ".join(parts)
            + f"{page_suffix}）"
        )
        progress = yuzu_progress(user_id)
        if progress is not None:
            header += f"\n柚子社收藏进度：{progress[0]}/{progress[1]}"
    lines = [header]
    for index, entry in enumerate(page_rows, start=start + 1):
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
    if pages > 1:
        nav = []
        if page > 1:
            nav.append(f"上一页：{command} page {page - 1}")
        if page < pages:
            nav.append(f"下一页：{command} page {page + 1}")
        lines.append(" ｜ ".join(nav))
    lines.append("发数字或名字查看角色卡片：/waifu collection <序号|名字>")
    return "\n".join(lines)