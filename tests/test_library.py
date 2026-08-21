"""final_company_library 本地资料库读取与抽卡测试。"""

from __future__ import annotations

import json

from waifu_box import library, logos


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _build_library(root) -> None:
    company_dir = root / "ゆずソフト"
    _write_json(
        company_dir / "公司索引.json",
        {
            "id": "p98",
            "name": "ゆずソフト",
            "vndb_name": "Yuzusoft",
            "original": "ゆずソフト",
        },
    )
    game_dir = company_dir / "喫茶ステラと死神の蝶"
    _write_json(
        game_dir / "游戏介绍.json",
        {
            "id": "v1",
            "title": "Café Stella",
            "jp_title": "喫茶ステラと死神の蝶",
            "cn_title": "星光咖啡馆",
            "released": "2020-09-24",
            "company_ids": ["p98"],
            "character_ids": ["c1", "c2"],
        },
    )
    _write_json(
        game_dir / "角色" / "ヒロイン.json",
        {
            "id": "c1",
            "name": "ヒロイン",
            "vndb_name": "Heroine",
            "display_name": "ヒロイン",
            "cn_name": "女主角",
            "sex": "female",
            "role": "main",
            "company_ids": ["p98"],
            "image": {"url": "https://t.vndb.org/ch/1/1.jpg"},
            "description": "A lovely heroine.",
            "cn_description": "可爱的主角。",
            "cv": ["声优A"],
        },
    )
    _write_json(
        game_dir / "角色" / "男配角.json",
        {
            "id": "c2",
            "name": "男配角",
            "vndb_name": "Support",
            "sex": "male",
            "role": "side",
            "company_ids": ["p98"],
            "image": {"url": "https://t.vndb.org/ch/1/2.jpg"},
        },
    )


def test_random_character_filters(tmp_path, monkeypatch) -> None:
    library_root = tmp_path / "final_company_library"
    _build_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    picked = library.random_character(company_ids=["p98"], year_from=2020)
    assert picked is not None
    assert picked.id == "c1"
    assert picked.sex == "female"
    assert picked.image_url.startswith("http")
    assert picked.game.title == "Café Stella"
    assert picked.company_ids == ["p98"]

    assert library.random_character(company_ids=["p99"]) is None
    assert library.random_character(year_from=2021) is None


def test_random_character_excludes_ids(tmp_path, monkeypatch) -> None:
    library_root = tmp_path / "final_company_library"
    _build_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    # 排除唯一的女性角色 c1 后应无候选
    assert library.random_character(company_ids=["p98"], exclude_ids={"c1"}) is None
    assert library.random_character(company_ids=["p98"], exclude_ids={"c9"}) is not None


def test_get_and_search_by_id(tmp_path, monkeypatch) -> None:
    library_root = tmp_path / "final_company_library"
    _build_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    character = library.get_character_by_id("c1")
    assert character is not None and character.name == "ヒロイン"
    assert library.get_character_by_id("c999") is None

    found = library.search_characters("ヒロイン", 1)
    assert found and found[0].id == "c1"
    assert library.search_characters("不存在", 1) == []


def test_resolve_company_ids_from_local_index(tmp_path, monkeypatch) -> None:
    library_root = tmp_path / "final_company_library"
    _build_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    assert library.resolve_company_ids(["Yuzusoft"]) == ["p98"]
    assert library.resolve_company_ids(["Yuzusoft SOUR"]) == ["p98"]


def test_logo_index_uses_csv(tmp_path, monkeypatch) -> None:
    library_root = tmp_path / "final_company_library"
    logo_root = tmp_path / "company_logos"
    _build_library(library_root)
    normalized = logo_root / "normalized"
    normalized.mkdir(parents=True)
    logo = normalized / "Yuzusoft.png"
    logo.write_bytes(b"fake-png")
    (logo_root / "company_logos.csv").write_text(
        "company_id,company_name,logo_path,status\n"
        "p98,Yuzusoft,data/company_logos/normalized/Yuzusoft.png,normalized\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    monkeypatch.setattr(logos.config, "logo_dir", str(logo_root))
    library.reset_cache()
    logos.reset_cache()

    assert logos.logo_path_for_companies(["p98"]) == logo
    assert logos.company_names(["p98"]) == ["Yuzusoft"]
