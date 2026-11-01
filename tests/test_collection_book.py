"""角色图鉴测试。"""

from __future__ import annotations

import json

from waifu_box import collection_book


def test_rec_collect_adds_and_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    record = {
        "character_id": "c1",
        "name": "あおい",
        "original": "あおい",
        "source": "waifu",
        "vns": [{"id": "v1", "title": "ゲーム"}],
    }
    assert collection_book.rec_collect(100, record) is True
    assert collection_book.rec_collect(100, record) is False  # 幂等
    assert collection_book.collection_size(100) == 1

    record2 = {**record, "character_id": "c2", "name": "さくら"}
    assert collection_book.rec_collect(100, record2) is True
    assert collection_book.collection_size(100) == 2


def test_collection_text_shows_names_and_yuzu_tag(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    collection_book.rec_collect_id(
        100, "c1", name="四季 ナツメ", source="yuzu",
        vns=[{"id": "v1", "title": "千恋＊万花"}],
    )
    collection_book.rec_collect_id(100, "c2", name="野村 美希")

    text = collection_book.collection_text(100)
    assert "「四季 ナツメ" in text.replace("【", "「").replace("】", "」") or "四季 ナツメ" in text
    assert "千恋＊万花" in text
    assert "野村 美希" in text

    yuzu_text = collection_book.collection_text(100, only_yuzu=True)
    assert "四季 ナツメ" in yuzu_text
    assert "野村 美希" not in yuzu_text


def test_collection_text_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    assert "图鉴还是空的" in collection_book.collection_text(100)


def test_history_import_from_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    state_path = tmp_path / "waifu_state.json"
    state_path.write_text(
        '{"users": {"1": {"date": "2026-10-01", "character_id": "ch_a", '
        '"name": "古参角色", "original": "古参角色", "source": "waifu"}}}',
        encoding="utf-8",
    )

    assert collection_book.collection_size(1) == 1
    text = collection_book.collection_text(1)
    assert "古参角色" in text


def test_rec_collect_preserves_card_fields(tmp_path, monkeypatch) -> None:
    """图鉴条目保留渲染卡片所需的完整字段（library_path/role/image_url）。"""
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    record = {
        "character_id": "c1",
        "name": "壬生 千咲",
        "original": "壬生 千咲",
        "source": "yuzu",
        "vns": [{"id": "v1", "title": "RIDDLE JOKER"}],
        "role": "primary",
        "image_url": "https://t.vndb.org/ch/1.jpg",
        "library_path": "ゆずソフト/RIDDLE JOKER/角色/壬生 千咲.json",
    }
    assert collection_book.rec_collect(100, record) is True

    entry = collection_book.user_collection(100)["c1"]
    assert entry["library_path"] == record["library_path"]
    assert entry["role"] == "primary"
    assert entry["image_url"] == record["image_url"]
    assert entry["vns"] == [{"id": "v1", "title": "RIDDLE JOKER"}]


def test_search_collection_matches_name_and_game(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    collection_book.rec_collect_id(
        100, "c1", name="四季 ナツメ", source="yuzu",
        vns=[{"id": "v1", "title": "千恋＊万花"}],
    )
    collection_book.rec_collect_id(
        100, "c2", name="野村 美希", source="waifu",
        vns=[{"id": "v2", "title": "Summer Pockets"}],
    )

    # 按角色名
    assert [r["character_id"] for r in collection_book.search_collection(100, "ナツメ")] == ["c1"]
    # 按作品名（不区分大小写）
    assert [r["character_id"] for r in collection_book.search_collection(100, "summer")] == ["c2"]
    # 按原名
    assert collection_book.search_collection(100, "四季")[0]["character_id"] == "c1"
    # 无匹配
    assert collection_book.search_collection(100, "不存在的角色") == []
    # 空关键词
    assert collection_book.search_collection(100, "") == []


def test_usage_text_lists_inspection_methods() -> None:
    text = collection_book.usage_text()
    assert "/waifu collection" in text
    assert "序号" in text
    assert "中文名" in text


def test_empty_collection_shows_usage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    text = collection_book.collection_text(100)
    assert "图鉴还是空的" in text
    assert "/waifu collection" in text


def test_search_collection_by_cn_name_and_roman(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    collection_book.rec_collect_id(
        100, "c1", name="四季 ナツメ", source="yuzu",
        vns=[{"id": "v1", "title": "千恋＊万花"}],
        cn_name="四季夏目", roman="Shiki Natsume",
    )
    # 中文名检索
    assert [r["character_id"] for r in collection_book.search_collection(100, "夏目")] == ["c1"]
    # 罗马音检索（不区分大小写）
    assert [r["character_id"] for r in collection_book.search_collection(100, "shiki")] == ["c1"]


def test_search_collection_by_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    # yuzu 在前 → 序号1是c1
    collection_book.rec_collect_id(100, "c1", name="柚子甲", source="yuzu")
    collection_book.rec_collect_id(100, "c2", name="常规乙", source="waifu")
    collection_book.rec_collect_id(100, "c3", name="常规丙", source="waifu")

    first = collection_book.search_collection(100, "1")
    assert first and first[0]["character_id"] == "c1"
    assert collection_book.search_collection(100, "2")[0]["character_id"] == "c2"
    assert collection_book.search_collection(100, "3")[0]["character_id"] == "c3"
    # 越界
    assert collection_book.search_collection(100, "99") == []
    # 非数字不受影响
    assert collection_book.search_collection(100, "abc") == []

def test_collection_text_shows_yuzu_progress_and_rarity(tmp_path, monkeypatch) -> None:
    """图鉴展示：柚子社进度 + 稀有度标签。"""
    yuzu_dir = tmp_path / "lib" / "ゆずソフト"
    yuzu_dir.mkdir(parents=True)
    (yuzu_dir / "公司索引.json").write_text(
        json.dumps({"id": "p98", "name": "ゆずソフト", "vndb_name": "Yuzusoft"}),
        encoding="utf-8",
    )
    game_dir = yuzu_dir / "作品X"
    (game_dir / "角色").mkdir(parents=True)
    (game_dir / "游戏介绍.json").write_text(
        json.dumps({
            "id": "v1", "title": "作品X", "jp_title": "作品X",
            "company_ids": ["p98"],
            "character_ids": ["c1", "c2"],
        }),
        encoding="utf-8",
    )
    (game_dir / "角色" / "c1.json").write_text(
        json.dumps({"id": "c1", "name": "角色一", "display_name": "角色一", "role": "primary", "company_ids": ["p98"]}),
        encoding="utf-8",
    )
    (game_dir / "角色" / "c2.json").write_text(
        json.dumps({"id": "c2", "name": "角色二", "display_name": "角色二", "role": "side", "company_ids": ["p98"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.config, "library_dir", str(tmp_path / "lib"))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    from waifu_box import library as lib_mod
    lib_mod.reset_cache()

    collection_book.rec_collect_id(200, "c1", name="角色一", source="yuzu", role="primary")
    assert collection_book.yuzu_progress(200) == (1, 2)
    text = collection_book.collection_text(200)
    assert "柚子社收藏进度：1/2" in text
    assert "[SSR]" in text


def test_rarity_fallback_to_library(tmp_path, monkeypatch) -> None:
    """图鉴条目缺 role 时回查本地库判定稀有度（常陸茉子 primary→SSR）。"""
    yuzu_dir = tmp_path / "lib" / "ゆずソフト"
    yuzu_dir.mkdir(parents=True)
    (yuzu_dir / "公司索引.json").write_text(
        json.dumps({"id": "p98", "name": "ゆずソフト", "vndb_name": "Yuzusoft"}),
        encoding="utf-8",
    )
    game_dir = yuzu_dir / "千恋＊万花"
    (game_dir / "角色").mkdir(parents=True)
    (game_dir / "游戏介绍.json").write_text(
        json.dumps({
            "id": "v19073", "title": "千恋＊万花", "jp_title": "千恋＊万花",
            "company_ids": ["p98"], "character_ids": ["c44769"],
        }),
        encoding="utf-8",
    )
    (game_dir / "角色" / "常陸 茉子.json").write_text(
        json.dumps({"id": "c44769", "name": "常陸 茉子", "display_name": "常陸 茉子", "role": "primary", "company_ids": ["p98"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.config, "library_dir", str(tmp_path / "lib"))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    from waifu_box import library as lib_mod
    lib_mod.reset_cache()

    # 收录时故意不含 role
    collection_book.rec_collect_id(300, "c44769", name="常陸 茉子", source="yuzu")
    entry = collection_book.user_collection(300)["c44769"]
    entry.pop("role", None)
    assert collection_book._rarity_of_entry(entry) == "SSR"


def test_collection_text_paginates_eight_per_page(tmp_path, monkeypatch) -> None:
    """图鉴每页最多 8 个，页码全局连续编号。"""
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    for index in range(1, 11):
        collection_book.rec_collect_id(
            100, f"c{index}", name=f"角色{index:02d}"
        )

    page1 = collection_book.collection_text(100, page=1)
    page2 = collection_book.collection_text(100, page=2)

    rows1 = [line for line in page1.splitlines() if line[:1].isdigit()]
    rows2 = [line for line in page2.splitlines() if line[:1].isdigit()]
    assert len(rows1) == 8
    assert len(rows2) == 2
    assert rows2[0].startswith("9. ")
    assert rows2[1].startswith("10. ")
    assert "第 1/2 页" in page1
    assert "第 2/2 页" in page2
    assert "下一页：/waifu collection page 2" in page1
    assert "上一页：/waifu collection page 1" in page2
    assert "下一页" not in page2


def test_collection_text_company_pagination_command(tmp_path, monkeypatch) -> None:
    """会社图鉴分页链接使用会社专属命令。"""
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False

    for index in range(1, 10):
        collection_book.rec_collect_id(
            200,
            f"k{index}",
            name=f"Key角色{index}",
            source="key",
        )

    page1 = collection_book.collection_text(
        200, company_source="key", page=1,
        command="/keywaifu collection",
    )
    page2 = collection_book.collection_text(
        200, company_source="key", page=2,
        command="/keywaifu collection",
    )
    assert "【Key图鉴】共 9 位（第 1/2 页）" in page1
    assert "下一页：/keywaifu collection page 2" in page1
    assert "上一页：/keywaifu collection page 1" in page2


def test_search_uses_stored_company_ids(tmp_path, monkeypatch) -> None:
    """会社筛选优先使用收录时保存的 company_ids，不依赖 library_path。"""
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False
    collection_book._index_cache.clear()
    collection_book.rec_collect_id(
        100,
        "c1",
        name="Key角色",
        source="waifu",
        company_ids=["p24"],
    )
    monkeypatch.setattr(
        collection_book,
        "_company_ids_for_source",
        lambda source: {"p24"} if source == "key" else set(),
    )
    collection_book._index_cache.clear()

    assert collection_book._entry_matches_source(
        collection_book.user_collection(100)["c1"], "key"
    )
    results = collection_book.search_collection(
        100, "Key角色", company_source="key"
    )
    assert [entry["character_id"] for entry in results] == ["c1"]
    assert collection_book.collection_index(100, "c1", "key") == 1


def test_search_index_invalidated_on_collect(tmp_path, monkeypatch) -> None:
    """新增收藏后搜索索引要失效，能立刻搜到新角色。"""
    monkeypatch.setattr(collection_book.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(tmp_path))
    collection_book._loaded = False
    collection_book._index_cache.clear()

    collection_book.rec_collect_id(100, "c1", name="角色一")
    assert collection_book.search_collection(100, "角色二") == []

    collection_book.rec_collect_id(100, "c2", name="角色二")
    results = collection_book.search_collection(100, "角色二")
    assert [entry["character_id"] for entry in results] == ["c2"]


def test_entry_from_library_path_stores_company_ids(tmp_path, monkeypatch) -> None:
    """新收录的本地库角色直接保存 company_ids。"""
    data_dir = tmp_path / "data"
    library_dir = tmp_path / "library"
    character_dir = library_dir / "Key"
    character_dir.mkdir(parents=True)
    (character_dir / "角色.json").write_text(
        json.dumps({"id": "c1", "company_ids": ["p24"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(collection_book.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection_book.config, "library_dir", str(library_dir))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(data_dir))
    collection_book._loaded = False
    collection_book._index_cache.clear()

    collection_book.rec_collect_id(
        100, "c1", name="Key酱", library_path="Key/角色.json"
    )
    entry = collection_book.user_collection(100)["c1"]
    assert entry["company_ids"] == ["p24"]


def test_enrich_backfills_company_ids_for_legacy_entries(
    tmp_path, monkeypatch
) -> None:
    """旧图鉴条目在 enrich 时补全 company_ids 并持久化。"""
    data_dir = tmp_path / "data"
    library_dir = tmp_path / "library"
    data_dir.mkdir(parents=True)
    character_dir = library_dir / "Key"
    character_dir.mkdir(parents=True)
    (character_dir / "角色.json").write_text(
        json.dumps({"id": "c1", "company_ids": ["p24"]}),
        encoding="utf-8",
    )
    (data_dir / "waifu_collection.json").write_text(
        json.dumps(
            {
                "version": 1,
                "users": {
                    "100": {
                        "c1": {
                            "character_id": "c1",
                            "name": "Key酱",
                            "original": "Key酱",
                            "source": "waifu",
                            "vns": [],
                            "first_seen": "2026-10-01T00:00:00",
                            "role": "",
                            "image_url": "",
                            "cn_name": "",
                            "roman": "",
                            "library_path": "Key/角色.json",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(collection_book.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection_book.config, "library_dir", str(library_dir))
    monkeypatch.setattr(collection_book.waifu.config, "data_dir", str(data_dir))
    collection_book._loaded = False
    collection_book._index_cache.clear()

    updated = collection_book.enrich_from_library(100)
    assert updated == 1
    entry = collection_book.user_collection(100)["c1"]
    assert entry["company_ids"] == ["p24"]
    persisted = json.loads(
        (data_dir / "waifu_collection.json").read_text(encoding="utf-8")
    )
    assert persisted["users"]["100"]["c1"]["company_ids"] == ["p24"]


def test_company_ids_persistent_cache_avoids_light_scan(
    tmp_path, monkeypatch
) -> None:
    """固定会社 ID 解析结果持久化，后续启动无需再扫公司索引。"""
    import json
    from waifu_box import library

    data_dir = tmp_path / "data"
    library_dir = tmp_path / "library"
    company_dir = library_dir / "Key"
    company_dir.mkdir(parents=True)
    (company_dir / "公司索引.json").write_text(
        json.dumps({"id": "p24", "name": "Key", "vndb_name": "Key"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(collection_book.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection_book.config, "library_dir", str(library_dir))
    monkeypatch.setattr(library.config, "library_dir", str(library_dir))
    library.reset_cache()
    collection_book._light_company_index_cache.clear()
    collection_book._light_company_ids_cache.clear()
    collection_book._company_id_cache.clear()

    assert collection_book._resolve_company_ids_light("key") == ["p24"]
    cache_file = data_dir / "waifu_company_ids.json"
    assert cache_file.is_file()

    collection_book._light_company_index_cache.clear()
    collection_book._light_company_ids_cache.clear()
    monkeypatch.setattr(
        collection_book,
        "_load_light_company_indexes",
        lambda: (_ for _ in ()).throw(AssertionError("should use cache")),
    )
    assert collection_book._resolve_company_ids_light("key") == ["p24"]


def test_company_totals_persistent_cache_avoids_library_index(
    tmp_path, monkeypatch
) -> None:
    """会社角色总数持久化，避免每次冷启动加载全量库索引。"""
    import json
    from waifu_box import library

    data_dir = tmp_path / "data"
    library_dir = tmp_path / "library"
    company_dir = library_dir / "Key"
    game_dir = company_dir / "Game"
    game_dir.mkdir(parents=True)
    (company_dir / "公司索引.json").write_text(
        json.dumps({"id": "p24", "name": "Key", "vndb_name": "Key"}),
        encoding="utf-8",
    )
    (game_dir / "游戏介绍.json").write_text(
        json.dumps(
            {
                "id": "v1",
                "title": "Game",
                "company_ids": ["p24"],
                "character_ids": ["c1", "c2"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(collection_book.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection_book.config, "library_dir", str(library_dir))
    monkeypatch.setattr(library.config, "library_dir", str(library_dir))
    library.reset_cache()
    collection_book._light_company_index_cache.clear()
    collection_book._light_company_ids_cache.clear()
    collection_book._company_id_cache.clear()
    collection_book._company_total_cache.clear()

    assert collection_book._company_total("key") == 2
    cache_file = data_dir / "waifu_company_totals.json"
    assert cache_file.is_file()

    collection_book._company_total_cache.clear()
    monkeypatch.setattr(
        library, "ensure_index", lambda: (_ for _ in ()).throw(
            AssertionError("should use cache")
        )
    )
    assert collection_book._company_total("key") == 2


def test_company_ids_split_hooksoft_smee_asa(tmp_path, monkeypatch) -> None:
    """固定入口 ID 解析：hook 只含 HOOKSOFT，smee/asa 各自独立。"""
    import json
    from waifu_box import library

    data_dir = tmp_path / "data"
    library_dir = tmp_path / "library"
    for folder, cid, name in (
        ("HOOKSOFT", "p106", "HOOKSOFT"),
        ("SMEE", "p328", "SMEE"),
        ("ASa Project", "p371", "ASa Project"),
    ):
        path = library_dir / folder
        path.mkdir(parents=True)
        (path / "公司索引.json").write_text(
            json.dumps({"id": cid, "name": name, "vndb_name": name}),
            encoding="utf-8",
        )
    monkeypatch.setattr(collection_book.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection_book.config, "library_dir", str(library_dir))
    monkeypatch.setattr(library.config, "library_dir", str(library_dir))
    library.reset_cache()
    collection_book._light_company_index_cache.clear()
    collection_book._light_company_ids_cache.clear()
    collection_book._company_id_cache.clear()

    assert collection_book._company_ids_for_source("hook") == {"p106"}
    assert collection_book._company_ids_for_source("smee") == {"p328"}
    assert collection_book._company_ids_for_source("asa") == {"p371"}
