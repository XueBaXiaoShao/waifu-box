"""命令测试：规则、群开关、额度、设置、缓存与 LRU。"""

from __future__ import annotations

import json
from pathlib import Path

from nonebot.adapters.onebot.v11 import Message

from waifu_box import (
    commands,
    http,
    library,
    vndb,
    waifu,
    waifu_cache,
    waifu_usage,
)
from waifu_box.models import Image, VNDBCharacter, VnRef


class _FakeEvent:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id

    def get_plaintext(self) -> str:
        return "/waifu"


class _FakeGroupEvent(_FakeEvent):
    def __init__(self, user_id: int, group_id: int) -> None:
        super().__init__(user_id)
        self.group_id = group_id


class _FakeMatcher:
    def __init__(self) -> None:
        self.sent: list = []

    async def send(self, message) -> None:
        self.sent.append(message)

    async def finish(self, message=None) -> None:
        if message is not None:
            self.sent.append(message)
        raise _Stop()


class _Stop(Exception):
    pass


async def _run(coro) -> None:
    try:
        await coro
    except _Stop:
        pass


def _character(char_id: str = "c1") -> VNDBCharacter:
    return VNDBCharacter(
        id=char_id,
        name="Hero",
        original="ヒーロー",
        sex=["f"],
        image=Image(url="https://t.vndb.org/1.jpg"),
        vns=[VnRef(id="v1", title="Game")],
    )


def test_slash_rules() -> None:
    assert commands._is_slash_waifu(_FakeEvent(1)) is True
    assert commands._is_slash_yuzuwaifu(_FakeEvent(1)) is False


def test_group_switch_disables(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(commands.config, "data_dir", str(tmp_path))
    (tmp_path / "plugin_switches.json").write_text(
        json.dumps(
            {
                "version": 1,
                "groups": {"912875556": {"waifu_box": False}},
            }
        ),
        encoding="utf-8",
    )

    assert commands._plugin_enabled_for_event(_FakeGroupEvent(1, 912875556)) is False
    assert commands._plugin_enabled_for_event(_FakeGroupEvent(1, 999)) is True


async def test_waifu_and_yuzuwaifu_share_daily_quota(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(
        library.config, "library_dir", str(tmp_path / "no_library")
    )
    library.reset_cache()
    picks = [_character("c1"), _character("c2")]
    calls = []

    async def fake_random(**kwargs):
        calls.append(1)
        return picks.pop(0)

    async def fake_yuzu_ids():
        return ["p98"]

    monkeypatch.setattr(vndb, "random_female_character", fake_random)
    monkeypatch.setattr(commands, "_yuzusoft_ids", fake_yuzu_ids)
    matcher = _FakeMatcher()

    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), ""))
    assert len(calls) == 1
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(123), "", source="yuzu")
    )
    assert len(calls) == 1
    assert "已经抽过了" in str(matcher.sent[-1])
    assert "waifu" not in str(matcher.sent[-1])


async def test_draw_uses_fresh_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(waifu_cache.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(tmp_path))
    waifu_cache.add_company_data(
        "yuzusoft",
        [{"id": "v1", "title": "Game", "released": None, "votecount": None}],
        [_character("c1")],
    )

    async def fake_random(**kwargs):
        raise AssertionError("有缓存不应请求 VNDB")

    monkeypatch.setattr(vndb, "random_female_character", fake_random)
    monkeypatch.setattr(commands, "_yuzusoft_ids", _FakeAsync(["p98"]))
    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(
            matcher, _FakeGroupEvent(123, 912875556), "", source="yuzu"
        )
    )

    assert waifu.get_today_waifu(123)["character_id"] == "c1"


async def test_draw_marks_usage_for_waifu_not_yuzu(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(
        library.config, "library_dir", str(tmp_path / "no_library")
    )
    library.reset_cache()
    picks = [_character("c5"), _character("c6")]

    async def fake_random(**kwargs):
        return picks.pop(0)

    monkeypatch.setattr(vndb, "random_female_character", fake_random)
    monkeypatch.setattr(commands, "_yuzusoft_ids", _FakeAsync(["p98"]))
    matcher = _FakeMatcher()

    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), ""))
    assert waifu_usage.last_used("c5") is not None
    waifu.reset_waifu(123)
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(123), "", source="yuzu")
    )
    assert waifu_usage.last_used("c6") is None


async def test_pool_settings_admin(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    (tmp_path / "admin_ids.json").write_text(
        json.dumps({"version": 2, "admins": [999]}), encoding="utf-8"
    )

    def fake_resolve(search_names):
        return ["p1"]

    monkeypatch.setattr(library, "resolve_company_ids", fake_resolve)
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(999), "settings pool set"))

    settings = waifu.load_settings()
    assert settings["pool_companies"] == list(commands.companies.WAIFU_POOL_KEYS)
    assert isinstance(settings["pool_company_ids"], dict)


async def test_failure_reports_message(monkeypatch) -> None:
    async def boom(matcher, event, value, source="waifu"):
        raise http.HttpError("VNDB 繁忙")

    monkeypatch.setattr(commands, "_cmd_waifu", boom)
    matcher = _FakeMatcher()
    await _run(commands.handle_waifu_short(_FakeEvent(1), matcher, Message("")))
    assert "抽卡失败" in str(matcher.sent[-1])


def _build_fake_library(root: Path) -> None:
    company_dir = root / "ゆずソフト"
    company_dir.mkdir(parents=True, exist_ok=True)
    (company_dir / "公司索引.json").write_text(
        json.dumps(
            {
                "id": "p98",
                "name": "ゆずソフト",
                "vndb_name": "Yuzusoft",
                "original": "ゆずソフト",
            }
        ),
        encoding="utf-8",
    )
    game_dir = company_dir / "喫茶ステラと死神の蝶"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "游戏介绍.json").write_text(
        json.dumps(
            {
                "id": "v1",
                "title": "Café Stella",
                "jp_title": "喫茶ステラと死神の蝶",
                "cn_title": "星光咖啡馆",
                "released": "2020-09-24",
                "company_ids": ["p98"],
                "character_ids": ["c1"],
            }
        ),
        encoding="utf-8",
    )
    character_dir = game_dir / "角色"
    character_dir.mkdir(parents=True, exist_ok=True)
    (character_dir / "ヒロイン.json").write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )


async def test_waifu_draws_from_local_library_and_sends_card(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(tmp_path / "data"))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    async def fake_render(character):
        return b"JPEG-CARD"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), ""))

    record = waifu.get_today_waifu(123)
    assert record is not None
    assert record["character_id"] == "c1"
    assert record["library_path"].endswith("ヒロイン.json")
    assert waifu_usage.last_used("c1") is not None
    assert "base64://" in str(matcher.sent[-1])


async def test_legacy_waifu_record_renders_card_by_character_id(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(tmp_path / "data"))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    # 模拟更新前保存的旧记录：没有 library_path
    waifu.save_waifu(123, _character("c1"), source="waifu")
    assert waifu.get_today_waifu(123).get("library_path") is None

    async def fake_render(character):
        return b"JPEG-CARD"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), ""))

    assert "已经抽过了" in str(matcher.sent[-1])
    assert "base64://" in str(matcher.sent[-1])


class _FakeAsync:
    def __init__(self, value) -> None:
        self._value = value

    async def __call__(self, *args, **kwargs):
        return self._value
