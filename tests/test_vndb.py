"""waifu-box VNDB 客户端测试。"""

from __future__ import annotations

import pytest

from waifu_box import vndb


def test_waifu_filters() -> None:
    assert vndb._waifu_filters() == ["and", ["sex", "=", "f"]]
    filters = vndb._waifu_filters(
        popular_threshold=5000, year_from=2000, year_to=2010, company_ids=["p98"]
    )
    assert ["vn", "=", ["votecount", ">=", 5000]] in filters
    assert ["vn", "=", ["released", ">=", "2000-01-01"]] in filters
    company_or = next(
        item for item in filters if isinstance(item, list) and item and item[0] == "or"
    )
    assert ["vn", "=", ["developer", "=", ["id", "=", "p98"]]] in company_or[1:]


async def test_random_female_character_company_path(monkeypatch) -> None:
    async def fake_post(path, payload):
        if path == "vn":
            return {"results": [{"id": "v1", "title": "Game", "votecount": 4141}]}
        return {
            "results": [
                {
                    "id": "c1",
                    "name": "Hero",
                    "sex": ["f"],
                    "image": {"url": "https://t.vndb.org/1.jpg"},
                    "vns": [{"id": "v1", "title": "Game"}],
                }
            ]
        }

    monkeypatch.setattr(vndb, "_post", fake_post)
    character = await vndb.random_female_character(company_ids=["p98"])
    assert character is not None and character.id == "c1"


async def test_resolve_company_ids(monkeypatch) -> None:
    async def fake_post(path, payload):
        keyword = payload["filters"][2]
        if keyword == "Yuzusoft":
            return {"results": [{"id": "p98", "name": "Yuzusoft"}]}
        return {"results": []}

    monkeypatch.setattr(vndb, "_post", fake_post)
    assert await vndb.resolve_company_ids(["Yuzusoft"]) == ["p98"]


async def test_refresh_company_cache_skips_existing(tmp_path, monkeypatch) -> None:
    from waifu_box import waifu_cache

    monkeypatch.setattr(waifu_cache.config, "data_dir", str(tmp_path))
    waifu_cache.add_company_data(
        "key",
        [{"id": "v1", "title": "Game", "released": None, "votecount": None}],
        [
            vndb.VNDBCharacter(
                id="c1",
                name="Hero",
                sex=["f"],
                image={"url": "https://t.vndb.org/1.jpg"},
                vns=[{"id": "v1", "title": "Game"}],
            )
        ],
    )
    calls: list[str] = []

    async def fake_post(path, payload):
        calls.append(path)
        return {"results": [{"id": "v1", "title": "Game"}]}

    monkeypatch.setattr(vndb, "_post", fake_post)
    result = await vndb.refresh_company_cache("key", ["p24"], vn_limit=10)
    assert result["skipped"] == 1
    assert calls == ["vn"]


async def test_get_by_id(monkeypatch) -> None:
    async def fake_post(path, payload):
        assert payload["filters"] == ["id", "=", "c9"]
        return {"results": [{"id": "c9", "name": "Hero"}]}

    monkeypatch.setattr(vndb, "_post", fake_post)
    assert (await vndb.get_by_id("c9")).id == "c9"
