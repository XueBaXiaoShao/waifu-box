"""waifu 状态、设置与群级后门测试。"""

from __future__ import annotations

import json

from waifu_box import companies, waifu
from waifu_box.models import Image, VNDBCharacter, VnRef


def _character(char_id: str = "c1") -> VNDBCharacter:
    return VNDBCharacter(
        id=char_id,
        name="Hero",
        original="ヒーロー",
        birthday=[8, 5],
        sex=["f"],
        image=Image(url="https://t.vndb.org/1.jpg"),
        vns=[VnRef(id="v1", title="Game")],
    )


def test_state_round_trip_and_reset(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))

    assert waifu.get_today_waifu(123) is None
    record = waifu.save_waifu(123, _character("c1"), source="yuzu")
    assert record["source"] == "yuzu"
    assert waifu.get_today_waifu(123)["character_id"] == "c1"
    assert waifu.reset_waifu(123) == 1
    assert waifu.get_today_waifu(123) is None


def test_settings_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))

    assert waifu.load_settings()["pool_companies"] == []
    waifu.save_settings(
        {
            "popular_threshold": 5000,
            "year_from": 2000,
            "year_to": 2010,
            "pool_companies": ["key"],
            "pool_company_ids": {"key": ["p1"]},
        }
    )
    settings = waifu.load_settings()
    assert settings["popular_threshold"] == 5000
    assert settings["pool_company_ids"] == {"key": ["p1"]}


def test_legacy_default_pool_migrates_to_full_library(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(
        waifu.library.config,
        "library_dir",
        str(tmp_path / "no_library"),
    )
    waifu.library.reset_cache()

    def fake_resolve(search_names):
        return ["p1"]

    monkeypatch.setattr(waifu.library, "resolve_company_ids", fake_resolve)
    (tmp_path / "waifu_settings.json").write_text(
        json.dumps(
            {
                "version": 1,
                "popular_threshold": 0,
                "year_from": 0,
                "year_to": 0,
                "pool_companies": list(companies.LEGACY_WAIFU_POOL_KEYS),
                "pool_company_ids": {
                    key: ["p1"] for key in companies.LEGACY_WAIFU_POOL_KEYS
                },
            }
        ),
        encoding="utf-8",
    )

    settings = waifu.load_settings()
    assert settings["pool_companies"] == list(companies.WAIFU_POOL_KEYS)
    assert all(settings["pool_company_ids"][key] for key in companies.WAIFU_POOL_KEYS)


def test_group_backdoors(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))

    waifu.save_group_company(912875556, ["yuzusoft"], ["p98", "p12215"])
    waifu.save_group_year_off(912875556, True)
    waifu.save_group_popular_off(912875556, True)

    assert waifu.get_group_company(912875556)["company_ids"] == ["p98", "p12215"]
    assert waifu.get_group_year_off(912875556) is True
    assert waifu.get_group_popular_off(912875556) is True
