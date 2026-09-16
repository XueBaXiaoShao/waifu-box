"""命令测试：规则、群开关、额度、设置、缓存与 LRU。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nonebot.adapters.onebot.v11 import Message

from waifu_box import (
    collection,
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


def test_resolve_trade_id_without_id(tmp_path, monkeypatch) -> None:
    """accept/reject/cancel 不传交易号时自动选唯一的待处理交易。"""
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection.config, "data_dir", str(tmp_path))
    waifu.save_waifu(
        111,
        VNDBCharacter(id="c1", name="千咲", original="壬生千咲"),
        source="yuzu",
        role="primary",
    )
    waifu.save_waifu(
        222,
        VNDBCharacter(id="c2", name="丛雨", original="叢雨"),
        source="yuzu",
        role="side",
    )
    trade = collection.propose_trade(111, 222)
    # 目标用户不传交易号 → 自动解析到唯一一笔
    assert commands._resolve_trade_id("", 222, "incoming") == trade["id"]
    # 发起人撤销同理
    assert commands._resolve_trade_id("", 111, "outgoing") == trade["id"]
    # 没待处理交易报错
    with pytest.raises(ValueError):
        commands._resolve_trade_id("", 333, "incoming")
    # 多笔时要求附交易号
    waifu.save_waifu(
        333,
        VNDBCharacter(id="c3", name="夕音", original="天霧夕音"),
        source="yuzu",
        role="main",
    )
    collection.propose_trade(333, 222)
    with pytest.raises(ValueError):
        commands._resolve_trade_id("", 222, "incoming")
    # 显式交易号仍然可用
    assert commands._resolve_trade_id(trade["id"], 222, "incoming") == trade["id"]


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
    assert "已经抽过" in str(matcher.sent[-1])


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


async def test_waifu_virus_special_thanks() -> None:
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(1), "virus"))
    assert "Special Thanks to 病毒@kitsurato" in str(matcher.sent[-1])
    assert "ご協力誠にありがとうございます" in str(matcher.sent[-1])


def _make_admin(data_dir: Path, admin_id: int = 999) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "admin_ids.json").write_text(
        json.dumps({"admins": [admin_id]}),
        encoding="utf-8",
    )


async def test_waifu_check_requires_admin() -> None:
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(1), "check 123"))
    assert "只有管理员" in str(matcher.sent[-1])


async def test_yuzuwaifu_set_keeps_yuzu_source(monkeypatch, tmp_path) -> None:
    """/yuzuwaifu set 存下的记录 source 必须是 yuzu，否则无法交易。"""
    data_dir = tmp_path / "data"
    _make_admin(data_dir, admin_id=999)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    async def fake_get_by_id(char_id: str):
        return _character(char_id)

    monkeypatch.setattr(commands.vndb, "get_by_id", fake_get_by_id)

    matcher = _FakeMatcher()
    # 本地库能搜到 → 走本地分支，source 为 yuzu
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(999), "set ヒロイン", source="yuzu")
    )
    record = waifu.get_today_waifu(999)
    assert record is not None and record["source"] == "yuzu"
    # VNDB 回退分支也必须存 yuzu
    await _run(
        commands._cmd_waifu(
            matcher, _FakeEvent(999), "set c9876", source="yuzu"
        )
    )
    record = waifu.get_today_waifu(999)
    assert record is not None and record["source"] == "yuzu"
    # 该记录可以被交易
    monkeypatch.setattr(collection.config, "data_dir", str(data_dir))
    waifu.save_waifu(
        123,
        VNDBCharacter(id="c2", name="丛雨", original="叢雨"),
        source="yuzu",
        role="side",
    )
    collection.propose_trade(999, 123)


async def test_waifu_check_requires_qq(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    _make_admin(data_dir)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(999), "check"))
    assert "用法：/waifu check <QQ号>" in str(matcher.sent[-1])


async def test_waifu_check_target_not_drawn(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    _make_admin(data_dir)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(999), "check 123"))
    assert "用户 123 今天还没有每日老婆" in str(matcher.sent[-1])


async def test_waifu_check_shows_target_waifu(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    _make_admin(data_dir)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    waifu.save_waifu(123, _character("c1"), source="waifu")

    async def fake_render(character):
        return b"JPEG-CHECK"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(999), "check 123"))

    sent = str(matcher.sent[-1])
    assert "base64://" in sent
    assert "用户 123" in sent
    assert "/waifu（管理员查看）" in sent
    # 管理员查看不应改动目标用户的记录
    assert waifu.get_today_waifu(123)["character_id"] == "c1"


async def test_waifu_check_shows_yuzuwaifu_source(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    _make_admin(data_dir)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    waifu.save_waifu(123, _character("c1"), source="yuzu")

    async def fake_render(character):
        return b"JPEG-CHECK-YUZU"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(999), "check 123"))

    sent = str(matcher.sent[-1])
    assert "base64://" in sent
    assert "/yuzuwaifu（管理员查看）" in sent


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


def _build_fake_library_two(root: Path) -> None:
    """单作品双女角资料库，用于验证同群不重复抽卡。"""
    _build_fake_library(root)
    character_dir = root / "ゆずソフト" / "喫茶ステラと死神の蝶" / "角色"
    (character_dir / "ヒロイン二号.json").write_text(
        json.dumps(
            {
                "id": "c2",
                "name": "ヒロイン二号",
                "vndb_name": "Heroine2",
                "display_name": "ヒロイン二号",
                "cn_name": "女主角二号",
                "sex": "female",
                "role": "main",
                "company_ids": ["p98"],
                "image": {"url": "https://t.vndb.org/ch/2/2.jpg"},
                "description": "Another heroine.",
                "cn_description": "另一位主角。",
                "cv": ["声优B"],
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
    assert "你今天的老婆" not in str(matcher.sent[-1])


async def test_yuzuwaifu_draws_local_yuzusoft_card(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(tmp_path / "data"))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    async def fake_render(character):
        return b"JPEG-YUZU"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(
            matcher, _FakeEvent(123), "", source="yuzu"
        )
    )

    record = waifu.get_today_waifu(123)
    assert record is not None
    assert record["source"] == "yuzu"
    assert record["character_id"] == "c1"
    assert record["library_path"].endswith("ヒロイン.json")
    assert waifu_usage.last_used("c1") is None
    assert "base64://" in str(matcher.sent[-1])


async def test_waifu_and_yuzuwaifu_share_local_quota(
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
    assert waifu.get_today_waifu(123)["source"] == "waifu"

    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(123), "", source="yuzu")
    )
    record = waifu.get_today_waifu(123)
    assert record is not None and record["source"] == "waifu"
    assert "base64://" in str(matcher.sent[-1])
    assert "已经抽过" in str(matcher.sent[-1])


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

    assert "已经抽过" in str(matcher.sent[-1])
    assert "base64://" in str(matcher.sent[-1])


async def test_group_no_duplicate_waifu(monkeypatch, tmp_path) -> None:
    """同群同日不能抽到别人已抽的老婆（防牛头人），不同群可重复。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_library_two(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    async def fake_render(character):
        return b"JPEG-CARD"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()

    await _run(commands._cmd_waifu(matcher, _FakeGroupEvent(123, 912875556), ""))
    first = waifu.get_today_waifu(123)["character_id"]
    assert waifu.get_today_waifu(123)["group_id"] == "912875556"

    await _run(commands._cmd_waifu(matcher, _FakeGroupEvent(456, 912875556), ""))
    second = waifu.get_today_waifu(456)["character_id"]
    assert waifu.get_today_waifu(456)["group_id"] == "912875556"
    assert first != second

    # 不同群可抽到相同角色
    await _run(commands._cmd_waifu(matcher, _FakeGroupEvent(789, 777777777), ""))
    third = waifu.get_today_waifu(789)["character_id"]
    assert waifu.get_today_waifu(789)["group_id"] == "777777777"
    assert third in {first, second}


class _FakeAsync:
    def __init__(self, value) -> None:
        self._value = value

    async def __call__(self, *args, **kwargs):
        return self._value


async def test_record_reply_image_fallback_card(monkeypatch, tmp_path) -> None:
    """本地库缺失时也要渲染同款卡片，而不是回退成裸图。"""
    monkeypatch.setattr(commands.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(library.config, "library_dir", str(tmp_path / "empty"))
    library.reset_cache()
    record = {
        "date": "2026-09-04",
        "source": "yuzu",
        "character_id": "c9999",
        "name": "隠 杏珠",
        "original": "隠 杏珠",
        "image_url": "https://t.vndb.org/ch/99/180599.jpg",
        "vns": [{"id": "v56650", "title": "ライムライト・レモネードジャム"}],
        "role": "",
        "group_id": None,
    }

    async def fake_render(character):
        assert character.image_url == record["image_url"]
        assert character.name == "隠 杏珠"
        assert character.game.title == "ライムライト・レモネードジャム"
        return b"JPEG-CARD"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    reply = await commands._record_reply_image(record)
    assert reply == "base64://SlBFRy1DQVJE"
    # 渲染失败时仍回退到原图 URL
    async def fail_render(character):
        return None

    monkeypatch.setattr(commands.card, "render_character_card", fail_render)
    reply = await commands._record_reply_image(record)
    assert reply == record["image_url"]


def test_trade_pick_hint_lists_both_sides(tmp_path, monkeypatch) -> None:
    """交易提示：列出双方今天的每日老婆（无卡号）。"""
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection.config, "data_dir", str(tmp_path))
    waifu.save_waifu(
        111,
        VNDBCharacter(
            id="c1",
            name="千咲",
            original="壬生千咲",
            vns=[VnRef(id="v1", title="RIDDLE JOKER")],
        ),
        source="yuzu",
        role="primary",
    )
    waifu.save_waifu(
        222,
        VNDBCharacter(
            id="c2",
            name="丛雨",
            original="叢雨",
            vns=[VnRef(id="v2", title="千恋＊万花")],
        ),
        source="yuzu",
        role="side",
    )
    hint = commands._trade_pick_hint(111, 222)
    assert "【你今天的每日老婆】" in hint
    assert "壬生千咲" in hint
    assert "SSR" in hint
    assert "【用户 222 今天的每日老婆】" in hint
    assert "叢雨" in hint
    assert "互换请发：/yuzuwaifu trade @对方" in hint


def test_waifu_test_daily_limit(tmp_path, monkeypatch) -> None:
    """每个人每天只能用一次 /waifu test。"""
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(tmp_path))
    assert waifu_usage.test_used_today(111) is False
    waifu_usage.mark_test_used(111)
    assert waifu_usage.test_used_today(111) is True
    # 其他人不受影响
    assert waifu_usage.test_used_today(222) is False
    # 记录持久化在 waifu_test_usage.json
    payload = json.loads((tmp_path / "waifu_test_usage.json").read_text("utf-8"))
    assert str(111) in list(payload.values())[0]
