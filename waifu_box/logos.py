"""会社 logo 索引：读取 company_logos/company_logos.csv 并定位图片文件。"""

from __future__ import annotations

import csv
import threading
from pathlib import Path
from typing import Any

from . import library
from .config import config

_lock = threading.Lock()
_index: dict[str, Path] | None = None


def _logo_root() -> Path:
    return Path(config.logo_dir)


def _load_index() -> dict[str, Path]:
    global _index
    if _index is not None:
        return _index
    with _lock:
        if _index is not None:
            return _index
        index: dict[str, Path] = {}
        root = _logo_root()
        csv_path = root / "company_logos.csv"
        if csv_path.is_file():
            try:
                with csv_path.open(
                    "r", encoding="utf-8-sig", newline=""
                ) as f:
                    for row in csv.DictReader(f):
                        company_id = str(row.get("company_id") or "").strip()
                        raw = str(row.get("logo_path") or "").strip()
                        if not company_id or not raw:
                            continue
                        relative = raw
                        prefix = "data/company_logos/"
                        if relative.startswith(prefix):
                            relative = relative[len(prefix) :]
                        path = root / relative
                        if path.is_file():
                            index[company_id] = path
            except (OSError, csv.Error):
                pass
        _index = index
        return index


def _fallback_path(company_id: str) -> Path | None:
    """CSV 缺失时按公司名在 normalized / 根目录中找 logo。"""
    name = library.company_display_name(company_id)
    if not name:
        return None
    root = _logo_root()
    normalized = root / "normalized"
    for folder in (normalized, root):
        if not folder.is_dir():
            continue
        for suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            candidate = folder / f"{name}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def reset_cache() -> None:
    """清空 logo 索引（测试用）。"""
    global _index
    with _lock:
        _index = None


def logo_path_for_companies(company_ids: list[str] | None) -> Path | None:
    """返回第一个能匹配到 logo 的会社图片路径。"""
    index = _load_index()
    for company_id in company_ids or []:
        path = index.get(company_id)
        if path is not None:
            return path
    for company_id in company_ids or []:
        path = _fallback_path(company_id)
        if path is not None:
            return path
    return None


def company_names(company_ids: list[str] | None) -> list[str]:
    """返回这些公司 ID 的展示名（保留 CSV 中的英文名优先）。"""
    names: list[str] = []
    for company_id in company_ids or []:
        name = library.company_display_name(company_id)
        if name:
            names.append(name)
    return names
