"""本地 VNDB 角色资料库：读取 final_company_library 并按会社/年代抽卡。

该模块只扫描每家会社的《游戏介绍.json》建立轻量索引，需要某个作品的角色时
才读取对应的《角色/*.json》，避免每次抽卡全量解析上万份角色文件。
"""

from __future__ import annotations

import json
import random
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import waifu_usage
from .config import config

_index_lock = threading.Lock()
_index_loaded = False
_companies_by_id: dict[str, dict[str, Any]] = {}
_games_by_id: dict[str, "LibraryGame"] = {}
_character_id_to_game: dict[str, str] = {}
_game_characters: dict[str, dict[str, "LibraryCharacter"]] = {}


@dataclass
class LibraryGame:
    """一部游戏在 final_company_library 中的索引信息。"""

    id: str
    title: str
    jp_title: str
    cn_title: str
    released: str
    company_id: str
    company_ids: list[str]
    character_ids: list[str]
    directory: Path

    @property
    def year(self) -> int | None:
        if isinstance(self.released, str) and self.released[:4].isdigit():
            return int(self.released[:4])
        return None


@dataclass
class LibraryCharacter:
    """一个本地资料库角色，data 为原始 JSON，便于卡片渲染使用全部字段。"""

    data: dict[str, Any]
    path: Path
    game: LibraryGame

    @property
    def id(self) -> str:
        return str(self.data.get("id") or "")

    @property
    def name(self) -> str:
        return str(
            self.data.get("display_name")
            or self.data.get("name")
            or self.data.get("vndb_name")
            or ""
        )

    @property
    def original(self) -> str:
        return str(self.data.get("original") or self.name or "")

    @property
    def cn_name(self) -> str:
        return str(self.data.get("cn_name") or "")

    @property
    def sex(self) -> str:
        return str(self.data.get("sex") or "")

    @property
    def image_url(self) -> str:
        image = self.data.get("image") or {}
        return str(image.get("url") or "")

    @property
    def description(self) -> str:
        return str(self.data.get("description") or "")

    @property
    def cn_description(self) -> str:
        return str(self.data.get("cn_description") or "")

    @property
    def cv(self) -> list[str]:
        return list(self.data.get("cv") or [])

    @property
    def company_ids(self) -> list[str]:
        return [str(item) for item in (self.data.get("company_ids") or [])]

    @property
    def game_ids(self) -> list[str]:
        return [str(item) for item in (self.data.get("game_ids") or [])]


def _library_root() -> Path:
    return Path(config.library_dir)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_index_locked() -> None:
    """扫描各会社的《公司索引.json》与全部《游戏介绍.json》。"""
    global _index_loaded
    if _index_loaded:
        return

    _companies_by_id.clear()
    _games_by_id.clear()
    _character_id_to_game.clear()
    _game_characters.clear()

    root = _library_root()
    if not root.is_dir():
        _index_loaded = True
        return

    for company_dir in sorted(root.iterdir()):
        if not company_dir.is_dir():
            continue
        company_index = _load_json(company_dir / "公司索引.json")
        if not company_index:
            continue
        company_id = str(company_index.get("id") or "")
        if not company_id:
            continue
        _companies_by_id[company_id] = company_index

        for game_dir in sorted(company_dir.iterdir()):
            if not game_dir.is_dir():
                continue
            intro = _load_json(game_dir / "游戏介绍.json")
            if not intro:
                continue
            game_id = str(intro.get("id") or "")
            if not game_id:
                continue
            character_ids = [
                str(item) for item in (intro.get("character_ids") or [])
            ]
            game = LibraryGame(
                id=game_id,
                title=str(intro.get("title") or intro.get("name") or ""),
                jp_title=str(intro.get("jp_title") or ""),
                cn_title=str(intro.get("cn_title") or ""),
                released=str(intro.get("released") or ""),
                company_id=company_id,
                company_ids=[
                    str(item) for item in (intro.get("company_ids") or [])
                ],
                character_ids=character_ids,
                directory=game_dir,
            )
            _games_by_id[game_id] = game
            for character_id in character_ids:
                _character_id_to_game.setdefault(character_id, game_id)

    _index_loaded = True


def ensure_index() -> bool:
    """确保轻量索引已加载；资料库目录存在时返回 True。"""
    with _index_lock:
        _load_index_locked()
    return bool(_games_by_id)


def reset_cache() -> None:
    """清空内存索引（测试或资料库变更后调用）。"""
    global _index_loaded
    with _index_lock:
        _index_loaded = False
        _companies_by_id.clear()
        _games_by_id.clear()
        _character_id_to_game.clear()
        _game_characters.clear()


def games(
    *,
    company_ids: list[str] | None = None,
    year_from: int = 0,
    year_to: int = 0,
) -> list[LibraryGame]:
    """按会社/年代过滤资料库中的游戏。"""
    if not ensure_index():
        return []
    wanted = {str(item) for item in company_ids} if company_ids else None
    result: list[LibraryGame] = []
    for game in _games_by_id.values():
        if wanted is not None and not (
            set(game.company_ids) & wanted
        ):
            continue
        year = game.year
        if year_from and year_from > 0 and (year is None or year < year_from):
            continue
        if year_to and year_to > 0 and (year is None or year > year_to):
            continue
        if not game.character_ids:
            continue
        result.append(game)
    return result


def _load_game_characters(game: LibraryGame) -> dict[str, LibraryCharacter]:
    """读取一部作品目录下的全部角色 JSON（带内存缓存）。"""
    cached = _game_characters.get(game.id)
    if cached is not None:
        return cached
    characters: dict[str, LibraryCharacter] = {}
    character_dir = game.directory / "角色"
    if character_dir.is_dir():
        for path in sorted(character_dir.glob("*.json")):
            data = _load_json(path)
            if not data or not data.get("id"):
                continue
            character = LibraryCharacter(
                data=data,
                path=path,
                game=game,
            )
            characters[str(data["id"])] = character
    _game_characters[game.id] = characters
    return characters


def _female_candidates(game: LibraryGame) -> list[LibraryCharacter]:
    return [
        character
        for character in _load_game_characters(game).values()
        if character.sex == "female" and character.image_url
    ]


def _pick_lru(candidates: list[LibraryCharacter]) -> LibraryCharacter:
    usage = waifu_usage.usage_map()
    never_used = [candidate for candidate in candidates if candidate.id not in usage]
    if never_used:
        return random.choice(never_used)
    oldest = min(usage[candidate.id] for candidate in candidates)
    bucket = [
        candidate for candidate in candidates
        if usage[candidate.id] == oldest
    ]
    return random.choice(bucket)


def random_character(
    *,
    company_ids: list[str] | None = None,
    year_from: int = 0,
    year_to: int = 0,
    lru: bool = False,
) -> LibraryCharacter | None:
    """随机抽取一名有立绘的女性角色（资料库内）。"""
    candidates_games = games(
        company_ids=company_ids,
        year_from=year_from,
        year_to=year_to,
    )
    if not candidates_games:
        return None

    weights = [max(1, len(game.character_ids)) for game in candidates_games]
    tried: set[str] = set()
    attempts = min(8, len(candidates_games))
    for _ in range(attempts):
        game = random.choices(candidates_games, weights=weights, k=1)[0]
        if game.id in tried:
            continue
        tried.add(game.id)
        candidates = _female_candidates(game)
        if not candidates:
            continue
        if lru:
            return _pick_lru(candidates)
        return random.choice(candidates)
    return None


def get_character_by_id(character_id: str) -> LibraryCharacter | None:
    """按 VNDB 角色 ID 查找本地角色。"""
    if not ensure_index():
        return None
    game_id = _character_id_to_game.get(character_id)
    if not game_id:
        return None
    game = _games_by_id.get(game_id)
    if game is None:
        return None
    return _load_game_characters(game).get(character_id)


def get_character_by_path(relative_path: str) -> LibraryCharacter | None:
    """按 final_company_library 内的相对路径读取角色。"""
    if not ensure_index():
        return None
    path = _library_root() / relative_path
    if not path.is_file():
        return None
    data = _load_json(path)
    if not data:
        return None
    game_id = _character_id_to_game.get(str(data.get("id") or ""))
    game = _games_by_id.get(game_id) if game_id else None
    if game is None:
        return None
    return LibraryCharacter(data=data, path=path, game=game)


def search_characters(keyword: str, limit: int = 1) -> list[LibraryCharacter]:
    """按角色文件名/作品名搜索本地角色（管理员 set 用）。"""
    if not ensure_index():
        return []
    needle = keyword.strip().lower()
    if not needle:
        return []
    if re_full_id(needle):
        character = get_character_by_id(needle)
        return [character] if character else []

    matches: list[LibraryCharacter] = []
    for game in _games_by_id.values():
        haystack = " ".join(
            [game.title, game.jp_title, game.cn_title, game.id]
        ).lower()
        if needle in haystack:
            for character in _female_candidates(game):
                matches.append(character)
                if len(matches) >= limit:
                    return matches
        character_dir = game.directory / "角色"
        if not character_dir.is_dir():
            continue
        for path in sorted(character_dir.glob("*.json")):
            if needle not in path.stem.lower():
                continue
            data = _load_json(path)
            if not data:
                continue
            character = LibraryCharacter(
                data=data,
                path=path,
                game=game,
            )
            if character.sex == "female" and character.image_url:
                matches.append(character)
                if len(matches) >= limit:
                    return matches
    return matches


def re_full_id(value: str) -> bool:
    """是否为 c 开头的 VNDB 角色 ID。"""
    return len(value) > 1 and value[0] == "c" and value[1:].isdigit()


def resolve_company_ids(search_names: list[str]) -> list[str]:
    """把搜索名解析为资料库中存在的 VNDB 厂商 ID（精确优先）。"""
    if not ensure_index():
        return []
    lower_names = [name.strip().lower() for name in search_names if name.strip()]
    if not lower_names:
        return []
    result: list[str] = []
    for company_id, company in _companies_by_id.items():
        candidates = [
            str(company.get("vndb_name") or ""),
            str(company.get("name") or ""),
            str(company.get("original") or ""),
        ]
        lower_candidates = {value.lower() for value in candidates if value}
        compact_candidates = {
            value.replace(" ", "").replace("-", "").lower()
            for value in lower_candidates
        }
        for name in lower_names:
            compact_name = name.replace(" ", "").replace("-", "").lower()
            matched = (
                name in lower_candidates
                or compact_name in compact_candidates
                or any(name in candidate for candidate in lower_candidates)
                or any(candidate in name for candidate in lower_candidates)
                or (
                    " " in name
                    and name.split(" ", 1)[0] in lower_candidates
                )
            )
            if matched and company_id not in result:
                result.append(company_id)
    return result


def company_display_name(company_id: str) -> str:
    """返回会社展示名；未收录时原样返回 ID。"""
    if ensure_index():
        company = _companies_by_id.get(company_id)
        if company:
            return str(
                company.get("vndb_name")
                or company.get("name")
                or company.get("original")
                or company_id
            )
    return company_id


def all_company_ids() -> list[str]:
    """资料库中全部会社 ID。"""
    ensure_index()
    return list(_companies_by_id.keys())
