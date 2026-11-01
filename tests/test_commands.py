"""命令测试：规则、群开关、额度、设置、缓存与 LRU。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from waifu_box import (
    collection,
    commands,
    http,
    library,
    natsume_state,
    shoukeni_state,
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


@pytest.fixture(autouse=True)
def _fake_card_render(monkeypatch):
    """命令测试默认不下载立绘，避免 VNDB 回退测试访问外网。"""
    async def fake_render(character):
        return b"JPEG-TEST-CARD"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)


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


async def test_waifu_collection_command_shows_book(tmp_path, monkeypatch) -> None:
    """/waifu collection 展示图鉴，含来源统计。"""
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    import waifu_box.collection_book as cb
    monkeypatch.setattr(cb.config, "data_dir", str(tmp_path))
    cb._loaded = False
    waifu.save_waifu(
        111,
        VNDBCharacter(id="c1", name="四季 ナツメ", original="四季 ナツメ"),
        source="yuzu",
        role="primary",
    )
    waifu.save_waifu(
        111,
        VNDBCharacter(id="c2", name="野村 美希", original="野村 美希"),
        source="waifu",
        role="main",
    )

    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(111), "collection"))
    text = str(matcher.sent[-1])
    assert "四季 ナツメ" in text
    assert "野村 美希" in text
    assert "柚子 1" in text
    assert "常规 1" in text


async def test_waifu_trade_dispatches_to_handler(tmp_path, monkeypatch) -> None:
    """/waifu trade @对方 与 /yuzuwaifu trade 共用交易实现（任意角色）。"""
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection.config, "data_dir", str(tmp_path))
    waifu.save_waifu(
        111,
        VNDBCharacter(id="c1", name="Hero-111", original="ヒーロー-111"),
        source="waifu",
        role="main",
    )
    waifu.save_waifu(
        222,
        VNDBCharacter(id="c2", name="Hero-222", original="ヒーロー-222"),
        source="waifu",
        role="side",
    )

    class _AtSegment:
        type = "at"
        data = {"qq": "222"}

    class _TradeEvent(_FakeGroupEvent):
        def __init__(self) -> None:
            super().__init__(111, 912875556)
            self.message = [_AtSegment()]

    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _TradeEvent(), "trade"))
    text = str(matcher.sent[-1]) if matcher.sent else ""
    assert "交易提议" in text
    assert "已在群里 @ 提醒对方" in text
    notice = matcher.sent[0]
    assert any(
        segment.type == "at" and segment.data.get("qq") == "222"
        for segment in notice
    )
    assert "收到来自 111 的每日老婆交易提议" in str(notice)


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


async def test_shoukeni_token_allows_self_set(
    monkeypatch, tmp_path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(shoukeni_state.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.permissions, "is_admin", lambda user_id: False)
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    shoukeni_state.note_shou_help(1)
    shoukeni_state.note_waifu_help(1)
    assert shoukeni_state.claim(1) == "granted"

    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(1), "set ヒロイン")
    )

    record = waifu.get_today_waifu(1)
    assert record is not None
    assert record["character_id"] == "c1"
    assert record["source"] == "waifu"
    assert shoukeni_state.has_token(1) is False
    assert "已设置为你的老婆" in str(matcher.sent[-1])

    matcher2 = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher2, _FakeEvent(2), "set ヒロイン")
    )
    assert "只有管理员" in str(matcher2.sent[-1])
    assert waifu.get_today_waifu(2) is None

    shoukeni_state.note_shou_help(3)
    shoukeni_state.note_waifu_help(3)
    assert shoukeni_state.claim(3) == "granted"
    matcher3 = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher3, _FakeEvent(3), "set 4 ヒロイン")
    )
    assert "只有管理员" in str(matcher3.sent[-1])
    assert shoukeni_state.has_token(3) is True


async def test_waifu_check_requires_qq(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    _make_admin(data_dir)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(999), "check"))
    assert "用法：/waifu check @某人 或 /waifu check <QQ号>" in str(matcher.sent[-1])


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


async def test_waifu_2025_draws_from_new_games_and_shares_quota(
    monkeypatch, tmp_path
) -> None:
    """/waifu 2025 从限定作品池抽取，与普通 /waifu 共享每日额度。"""
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(tmp_path / "data"))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    async def fake_render(character):
        return b"JPEG-CARD"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    monkeypatch.setattr(commands, "NEW_GAME_IDS", ["v1"])
    matcher = _FakeMatcher()

    # 第一次抽：写入普通 waifu 额度
    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), "2025"))
    record = waifu.get_today_waifu(123)
    assert record is not None
    assert record["source"] == "waifu"
    assert record["character_id"] == "c1"
    assert waifu_usage.last_used("c1") is not None
    assert "2025" in str(matcher.sent[-1])

    # 已抽过：重复展示，不再新抽
    sent_before = len(matcher.sent)
    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), "2025"))
    assert len(matcher.sent) == sent_before + 1
    assert "重复展示" in str(matcher.sent[-1])


async def test_yuzuwaifu_uses_omikuji_pick(
    monkeypatch, tmp_path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_library_two(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()
    (data_dir / "omikuji_yuzu.json").write_text(
        json.dumps(
            {
                "version": 1,
                "users": {
                    "123": {
                        "date": date.today().isoformat(),
                        "character_id": "c1",
                        "library_path": (
                            "ゆずソフト/喫茶ステラと死神の蝶/角色/"
                            "ヒロイン.json"
                        ),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    async def fail_draw(*args, **kwargs):
        raise AssertionError("不应走普通 yuzuwaifu 抽取")

    monkeypatch.setattr(commands, "_draw_character_with_fallback", fail_draw)
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
    assert "互换请发：/waifu trade @对方" in hint


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


def test_waifu_test_save_and_reset(tmp_path, monkeypatch) -> None:
    """test 记录可保存重看，reset 清除今日记录与次数。"""
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(tmp_path))
    assert waifu_usage.get_test_waifu(111) is None
    waifu_usage.save_test_waifu(
        111, {"date": waifu._today(), "character_id": "c1", "name": "测试"}
    )
    record = waifu_usage.get_test_waifu(111)
    assert record and record["name"] == "测试"
    assert waifu_usage.test_used_today(111) is False  # 保存记录不等于已用
    waifu_usage.mark_test_used(111)
    assert waifu_usage.test_used_today(111) is True
    waifu_usage.reset_test_waifu(111)
    assert waifu_usage.get_test_waifu(111) is None
    assert waifu_usage.test_used_today(111) is False


async def test_draw_local_retries_empty_pool_company(monkeypatch) -> None:
    """随机会会社选中空会社时，应重选其他会社而非直接返回 None。"""
    settings = {
        "pool_companies": ["empty", "good"],
        "pool_company_ids": {"empty": ["p999"], "good": ["p98"]},
        "year_from": 0,
        "year_to": 0,
    }
    group_settings = {
        "companies": [],
        "company_ids": [],
        "year_off": True,
        "popular_off": True,
    }
    picks = iter([("empty", ["p999"]), ("good", ["p98"])])
    monkeypatch.setattr(commands, "_pick_pool_company", lambda s: next(picks))
    results = iter([None, object()])
    monkeypatch.setattr(
        library,
        "random_character",
        lambda **kwargs: next(results),
    )
    character = await commands._draw_local_character(
        settings, group_settings, source="waifu"
    )
    assert character is not None


async def test_draw_local_returns_none_when_all_empty(monkeypatch) -> None:
    """所有会社都为空时才返回 None（不无限重试）。"""
    settings = {
        "pool_companies": ["empty"],
        "pool_company_ids": {"empty": ["p999"]},
        "year_from": 0,
        "year_to": 0,
    }
    group_settings = {
        "companies": [],
        "company_ids": [],
        "year_off": True,
        "popular_off": True,
    }
    monkeypatch.setattr(
        commands,
        "_pick_pool_company",
        lambda s: ("empty", ["p999"]),
    )
    monkeypatch.setattr(library, "random_character", lambda **kwargs: None)
    character = await commands._draw_local_character(
        settings, group_settings, source="waifu"
    )
    assert character is None


def test_collection_note_new_vs_duplicate(tmp_path, monkeypatch) -> None:
    """抽卡反馈：新角色提示收录进度，已有角色提示不重复收录。"""
    import waifu_box.collection_book as cb
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(cb.config, "data_dir", str(tmp_path))
    cb._loaded = False

    record = {
        "character_id": "c1",
        "name": "四季 ナツメ",
        "original": "四季 ナツメ",
        "source": "yuzu",
        "vns": [{"id": "v1", "title": "千恋＊万花"}],
    }
    note1 = commands._collection_note(100, record)
    assert "新角色已收录" in note1
    assert "当前共 1 位" in note1

    note2 = commands._collection_note(100, record)
    assert "已在你的图鉴中" in note2
    assert "不重复收录" in note2


def test_collection_note_new_vs_duplicate(tmp_path, monkeypatch) -> None:
    """抽卡反馈：新角色提示收录进度，已有角色提示不重复收录。"""
    import waifu_box.collection_book as cb
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(cb.config, "data_dir", str(tmp_path))
    cb._loaded = False

    record = {
        "character_id": "c1",
        "name": "四季 ナツメ",
        "original": "四季 ナツメ",
        "source": "yuzu",
        "vns": [{"id": "v1", "title": "千恋＊万花"}],
    }
    note1 = commands._collection_note(100, record)
    assert "新角色已收录" in note1
    assert "当前共 1 位" in note1

    note2 = commands._collection_note(100, record)
    assert "已在你的图鉴中" in note2
    assert "不重复收录" in note2


async def test_yuzuwaifu_collection_only_yuzu(tmp_path, monkeypatch) -> None:
    """/yuzuwaifu collection 只展示柚子社角色。"""
    import waifu_box.collection_book as cb
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(cb.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(commands.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection.config, "data_dir", str(tmp_path))
    cb._loaded = False
    waifu.save_waifu(
        111,
        VNDBCharacter(id="c1", name="柚子甲", original="柚子甲"),
        source="yuzu",
        role="primary",
    )
    waifu.save_waifu(
        111,
        VNDBCharacter(id="c2", name="常规乙", original="常规乙"),
        source="waifu",
        role="main",
    )

    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(111), "collection yuzu"))
    text = str(matcher.sent[-1])
    assert "柚子甲" in text
    assert "常规乙" not in text

    matcher2 = _FakeMatcher()
    await _run(
        commands._handle_yuzu_trade(matcher2, _FakeGroupEvent(111, 912875556), "collection", "")
    )
    text2 = str(matcher2.sent[-1])
    assert "柚子甲" in text2
    assert "常规乙" not in text2


class _NagatoEvent(_FakeEvent):
    def get_plaintext(self) -> str:
        return "/nagato"


def test_natsume_text_sets_are_separate() -> None:
    assert len(commands._NATSUME_HOLY_TEXTS) == 3
    assert len(commands._NATSUME_NEW_TEXTS) == 4
    assert len(commands._NATSUME_XIAHEXIAO_TEXTS) == 1
    assert len(commands._NATSUME_ZAOZI_TEXTS) == 1
    assert len(commands._NATSUME_ALL_TEXTS) == 9
    assert any("棗子的舔嘴" in text for text in commands._NATSUME_NEW_TEXTS)
    assert any("夏和小" in text for text in commands._NATSUME_XIAHEXIAO_TEXTS)
    assert any(
        "怎麼会有人不喜歡棗子姐呢" in text
        for text in commands._NATSUME_ZAOZI_TEXTS
    )
    assert all(
        not any(emoji in text for emoji in ("🥰", "🤤", "🌃", "🥵"))
        for text in commands._NATSUME_XIAHEXIAO_TEXTS
        + commands._NATSUME_ZAOZI_TEXTS
    )
    assert all(
        "" not in text
        for text in commands._NATSUME_XIAHEXIAO_TEXTS
        + commands._NATSUME_ZAOZI_TEXTS
    )
    assert all(
        text not in commands._NATSUME_HOLY_TEXTS
        for text in commands._NATSUME_NEW_TEXTS
    )
    assert all(
        text in commands._NATSUME_ALL_TEXTS
        for text in (
            commands._NATSUME_HOLY_TEXTS
            + commands._NATSUME_NEW_TEXTS
            + commands._NATSUME_XIAHEXIAO_TEXTS
            + commands._NATSUME_ZAOZI_TEXTS
        )
    )


def test_natsume_slash_rule() -> None:
    assert commands._is_slash_nagato(_NagatoEvent(1)) is True
    assert commands._is_slash_nagato(_FakeEvent(1)) is False


async def test_natsume_shortcut_returns_from_all_texts(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(natsume_state.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(commands.random, "choice", lambda seq: seq[0])
    matcher = _FakeMatcher()

    await _run(
        commands.handle_nagato(
            _NagatoEvent(1), matcher, Message("")
        )
    )

    sent = str(matcher.sent[-1])
    assert "本人真的想棗子姐" in sent


def test_natsume_state_limit_and_consume(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(natsume_state.config, "data_dir", str(tmp_path))

    assert natsume_state.limit() == 3
    for _ in range(3):
        allowed, used, cap = natsume_state.consume(7)
        assert allowed is True
        assert cap == 3
    allowed, used, cap = natsume_state.consume(7)
    assert allowed is False
    assert used == 3

    assert natsume_state.set_limit(1) == 1
    assert natsume_state.consume(8) == (True, 1, 1)
    assert natsume_state.consume(8)[0] is False

    assert natsume_state.set_limit(0) == 0
    for _ in range(5):
        assert natsume_state.consume(8)[0] is True


async def test_natsume_limit_admin_command(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(natsume_state.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(
        commands.permissions, "is_admin", lambda user_id: user_id == 1
    )
    matcher = _FakeMatcher()

    await _run(
        commands.handle_nagato(
            _NagatoEvent(1), matcher, Message("limit 2")
        )
    )
    assert natsume_state.limit() == 2
    assert "2 次" in str(matcher.sent[-1])

    matcher2 = _FakeMatcher()
    await _run(
        commands.handle_nagato(
            _NagatoEvent(2), matcher2, Message("limit 5")
        )
    )
    assert "仅管理员" in str(matcher2.sent[-1])
    assert natsume_state.limit() == 2


async def test_natsume_shortcut_respects_limit(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(natsume_state.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(commands.random, "choice", lambda seq: seq[0])
    natsume_state.set_limit(1)
    matcher = _FakeMatcher()

    await _run(
        commands.handle_nagato(
            _NagatoEvent(1), matcher, Message("")
        )
    )
    assert "本人真的想棗子姐" in str(matcher.sent[-1])

    matcher2 = _FakeMatcher()
    await _run(
        commands.handle_nagato(
            _NagatoEvent(1), matcher2, Message("")
        )
    )
    assert "已用完" in str(matcher2.sent[-1])


async def test_waifu_admin_collection_other_user(monkeypatch, tmp_path) -> None:
    """管理员 /waifu collection <QQ号> 查看他人图鉴。"""
    import json
    import waifu_box.collection_book as cb
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "admin_ids.json").write_text(
        json.dumps({"admins": [999]}), encoding="utf-8"
    )
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(cb.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection.config, "data_dir", str(data_dir))
    from waifu_box import permissions as perms
    monkeypatch.setattr(perms.config, "data_dir", str(data_dir))
    cb._loaded = False
    monkeypatch.setattr(cb.waifu.config, "data_dir", str(data_dir))

    # 目标用户有图鉴
    cb.rec_collect_id(222, "c1", name="他人角色", source="yuzu", role="primary")

    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(999), "collection 222"))
    text = str(matcher.sent[-1])
    assert "他人的图鉴" in text
    assert "他人角色" in text

    # 非管理员看不到他人图鉴（按自己图鉴处理）
    matcher2 = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher2, _FakeEvent(123), "collection 222"))
    assert "他人角色" not in str(matcher2.sent[-1])


def test_fixed_company_command_rules() -> None:
    """会社专属入口只匹配自己的斜杠命令。"""
    class _E:
        def __init__(self, text: str) -> None:
            self._text = text

        def get_plaintext(self) -> str:
            return self._text

    assert commands._is_slash_keywaifu(_E("/keywaifu"))
    assert commands._is_slash_keywaifu(_E("/keywaifu collection"))
    assert not commands._is_slash_keywaifu(_E("/waifu"))
    assert commands._is_slash_sagawaifu(_E("/sagawaifu"))
    assert not commands._is_slash_sagawaifu(_E("/keywaifu"))
    assert commands._is_slash_purplewaifu(_E("/purplewaifu"))
    assert not commands._is_slash_purplewaifu(_E("/purplewaifu2"))
    assert commands._is_slash_frontwaifu(_E("/frontwaifu"))
    assert commands._is_slash_crystalwaifu(_E("/crystalwaifu"))
    assert commands._is_slash_hookwaifu(_E("/hookwaifu"))
    assert commands._is_slash_madowaifu(_E("/madowaifu"))
    assert commands._is_slash_palwaifu(_E("/palwaifu"))
    assert commands._is_slash_favowaifu(_E("/favowaifu"))
    assert commands._is_slash_smeewaifu(_E("/smeewaifu"))
    assert commands._is_slash_asawaifu(_E("/asawaifu"))
    assert commands._is_slash_makurawaifu(_E("/makurawaifu"))
    assert not commands._is_slash_makurawaifu(_E("/makurawaifu2"))
    assert commands._is_slash_augustwaifu(_E("/augustwaifu"))
    assert not commands._is_slash_augustwaifu(_E("/augustwaifu2"))
    assert commands._is_slash_nitroplus(_E("/nitroplus"))
    assert commands._is_slash_nitroplus(_E("/nitroplus collection"))
    assert not commands._is_slash_nitroplus(_E("/nitroplus2"))
    assert commands._is_slash_qruppowaifu(_E("/qruppowaifu"))
    assert commands._is_slash_qruppowaifu(_E("/qruppowaifu collection"))
    assert not commands._is_slash_qruppowaifu(_E("/qruppowaifu2"))
    assert not commands._is_slash_frontwaifu(_E("/frontwaifu2"))


def _build_fake_company_library(
    root: Path,
    dirname: str,
    company_id: str,
    vndb_name: str,
    char_id: str,
    char_name: str,
) -> None:
    """构造单会社单角色资料库（Key/SAGA/Purple 测试用）。"""
    company_dir = root / dirname
    company_dir.mkdir(parents=True, exist_ok=True)
    (company_dir / "公司索引.json").write_text(
        json.dumps(
            {"id": company_id, "name": dirname, "vndb_name": vndb_name}
        ),
        encoding="utf-8",
    )
    game_dir = company_dir / "作品"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "游戏介绍.json").write_text(
        json.dumps(
            {
                "id": f"v-{company_id}",
                "title": f"{vndb_name} Game",
                "jp_title": f"{vndb_name} 作品",
                "released": "2020-01-01",
                "company_ids": [company_id],
                "character_ids": [char_id],
            }
        ),
        encoding="utf-8",
    )
    character_dir = game_dir / "角色"
    character_dir.mkdir(parents=True, exist_ok=True)
    (character_dir / f"{char_name}.json").write_text(
        json.dumps(
            {
                "id": char_id,
                "name": char_name,
                "display_name": char_name,
                "cn_name": char_name,
                "sex": "female",
                "role": "main",
                "company_ids": [company_id],
                "image": {"url": "https://t.vndb.org/ch/1/1.jpg"},
            }
        ),
        encoding="utf-8",
    )


def _prepare_company_test(monkeypatch, tmp_path, directory: str, company_id: str,
                          vndb_name: str, char_id: str, char_name: str) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_company_library(
        library_root, directory, company_id, vndb_name, char_id, char_name
    )
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()
    commands._fixed_company_ids_cache.clear()
    commands._yuzusoft_ids_cache = None
    commands.collection_book._company_id_cache.clear()


@pytest.mark.parametrize(
    "source,directory,company_id,vndb_name,char_id,char_name",
    [
        ("key", "Key", "p24", "Key", "c100", "Key酱"),
        ("saga", "SAGA", "p378", "SAGA PLANETS", "c200", "SAGA酱"),
        ("purple", "Purple", "p132", "Purple software", "c300", "Purple酱"),
        ("front", "Frontwing", "p200", "Frontwing", "c400", "Front酱"),
        ("crystal", "CRYSTALiA", "p201", "CRYSTALiA", "c401", "Crystal酱"),
        ("hook", "HOOKSOFT", "p202", "HOOKSOFT", "c402", "Hook酱"),
        ("mado", "Madosoft", "p203", "Madosoft", "c403", "Mado酱"),
        ("pal", "PALETTE", "p204", "PALETTE", "c404", "Pal酱"),
        ("favo", "FAVORITE", "p205", "FAVORITE", "c405", "Favo酱"),
        ("smee", "SMEE", "p328", "SMEE", "c500", "SMEE酱"),
        ("asa", "ASa Project", "p371", "ASa Project", "c501", "ASa酱"),
        ("makura", "Makura", "p259", "Makura", "c502", "Makura酱"),
        ("august", "AUGUST", "p95", "AUGUST", "c503", "August酱"),
        ("nitro", "ニトロプラス", "p42", "NITRO PLUS", "c505", "Nitro酱"),
        ("qruppo", "Qruppo", "p7659", "Qruppo", "c507", "Qruppo酱"),
    ],
)
async def test_company_waifu_draws_local_card(
    monkeypatch,
    tmp_path,
    source,
    directory,
    company_id,
    vndb_name,
    char_id,
    char_name,
) -> None:
    """会社入口从本地库固定抽对应会社角色，且不参与 LRU。"""
    _prepare_company_test(
        monkeypatch,
        tmp_path,
        directory,
        company_id,
        vndb_name,
        char_id,
        char_name,
    )

    async def fake_render(character):
        return b"JPEG-COMPANY"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(123), "", source=source)
    )

    record = waifu.get_today_waifu(123)
    assert record is not None
    assert record["source"] == source
    assert record["character_id"] == char_id
    assert record["library_path"].endswith(f"{char_name}.json")
    assert waifu_usage.last_used(char_id) is None
    assert "base64://" in str(matcher.sent[-1])


async def test_keywaifu_vndb_fallback_uses_company_filter(
    monkeypatch, tmp_path
) -> None:
    """/keywaifu 本地库不可用时回退 VNDB，仍固定传 Key 的厂商 ID。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(
        library.config, "library_dir", str(tmp_path / "no_library")
    )
    library.reset_cache()
    commands._fixed_company_ids_cache.clear()

    captured = {}

    async def fake_random(**kwargs):
        captured.update(kwargs)
        return _character("c-key")

    monkeypatch.setattr(vndb, "random_female_character", fake_random)
    monkeypatch.setattr(commands, "_company_ids", _FakeAsync(["p24"]))
    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(123), "", source="key")
    )

    assert captured["company_ids"] == ["p24"]
    assert captured["cache_key"] == "key"
    record = waifu.get_today_waifu(123)
    assert record is not None and record["source"] == "key"
    assert record["character_id"] == "c-key"
    assert waifu_usage.last_used("c-key") is None


async def test_company_entries_share_daily_quota(monkeypatch, tmp_path) -> None:
    """会社专属入口共享每日额度，重复时提示实际抽过的入口。"""
    _prepare_company_test(
        monkeypatch, tmp_path, "Key", "p24", "Key", "c100", "Key酱"
    )

    async def fake_render(character):
        return b"JPEG-KEY"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(123), "", source="key")
    )
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(123), "", source="saga")
    )

    record = waifu.get_today_waifu(123)
    assert record is not None and record["source"] == "key"
    assert "已经抽过 /keywaifu" in str(matcher.sent[-1])
    assert "Key老婆" in str(matcher.sent[-1])


async def test_company_collection_filters_by_company(monkeypatch, tmp_path) -> None:
    """会社入口的 collection 只展示对应会社角色。"""
    data_dir = tmp_path / "data"
    for module in (waifu, commands, commands.collection_book, collection):
        monkeypatch.setattr(module.config, "data_dir", str(data_dir))
    commands.collection_book._loaded = False
    waifu.save_waifu(
        111,
        VNDBCharacter(id="c-key", name="Key酱", original="Key酱"),
        source="key",
        role="primary",
    )
    waifu.save_waifu(
        111,
        VNDBCharacter(id="c-norm", name="常规乙", original="常规乙"),
        source="waifu",
        role="main",
    )

    matcher = _FakeMatcher()
    await _run(
        commands._handle_yuzu_trade(
            matcher, _FakeEvent(111), "collection", "", source="key"
        )
    )
    text = str(matcher.sent[-1])
    assert "Key酱" in text
    assert "常规乙" not in text

    matcher2 = _FakeMatcher()
    await _run(
        commands._cmd_waifu(
            matcher2, _FakeEvent(111), "collection key", source="waifu"
        )
    )
    text2 = str(matcher2.sent[-1])
    assert "Key酱" in text2
    assert "常规乙" not in text2


async def test_waifu_check_accepts_at_mention(monkeypatch, tmp_path) -> None:
    """/waifu check @某人 与 /waifu check <QQ号> 等价。"""
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
        return b"JPEG-CHECK-AT"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    event = _FakeGroupEvent(999, 912875556)
    event.message = Message([MessageSegment.at(123)])
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, event, "check"))

    sent = str(matcher.sent[-1])
    assert "用户 123" in sent
    assert "/waifu（管理员查看）" in sent


async def test_waifu_set_accepts_at_mention(monkeypatch, tmp_path) -> None:
    """/waifu set @某人 <角色名> 可直接代指定。"""
    data_dir = tmp_path / "data"
    _make_admin(data_dir)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    async def fake_render(character):
        return b"JPEG-SET-AT"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    event = _FakeGroupEvent(999, 912875556)
    event.message = Message([MessageSegment.at(123)])
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, event, "set ヒロイン"))

    record = waifu.get_today_waifu(123)
    assert record is not None
    assert record["character_id"] == "c1"
    assert record["source"] == "waifu"
    assert waifu.get_today_waifu(999) is None
    assert "已为用户 123 设置老婆" in str(matcher.sent[-1])


def test_extract_page_variants() -> None:
    assert commands._extract_page("page 2") == ("", 2)
    assert commands._extract_page("yuzu page 3") == ("yuzu", 3)
    assert commands._extract_page("123 page 2") == ("123", 2)
    assert commands._extract_page("PAGE 4") == ("", 4)
    assert commands._extract_page("2") == ("2", 1)


async def test_waifu_collection_page_2(monkeypatch, tmp_path) -> None:
    """/waifu collection page 2 显示第二页。"""
    import waifu_box.collection_book as cb

    data_dir = tmp_path / "data"
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(cb.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection.config, "data_dir", str(data_dir))
    cb._loaded = False
    for index in range(1, 11):
        cb.rec_collect_id(111, f"c{index}", name=f"角色{index:02d}")

    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(111), "collection page 2"))
    text = str(matcher.sent[-1])
    assert "第 2/2 页" in text
    assert "9. " in text and "10. " in text
    assert "上一页：/waifu collection page 1" in text


async def test_company_collection_page_2(monkeypatch, tmp_path) -> None:
    """/keywaifu collection page 2 使用会社图鉴分页。"""
    import waifu_box.collection_book as cb

    data_dir = tmp_path / "data"
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(cb.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection.config, "data_dir", str(data_dir))
    cb._loaded = False
    for index in range(1, 10):
        cb.rec_collect_id(
            111, f"k{index}", name=f"Key角色{index}", source="key"
        )

    matcher = _FakeMatcher()
    await _run(
        commands._handle_yuzu_trade(
            matcher, _FakeEvent(111), "collection", "page 2", source="key"
        )
    )
    text = str(matcher.sent[-1])
    assert "【Key图鉴】共 9 位（第 2/2 页）" in text
    assert "上一页：/keywaifu collection page 1" in text


async def test_collection_search_prefix_unique(monkeypatch, tmp_path) -> None:
    """/waifu collection search <关键词> 唯一匹配时出卡片。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.collection_book.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()
    commands.collection_book._loaded = False
    commands.collection_book.rec_collect_id(
        111, "c1", name="四季 ナツメ", original="四季ナツメ"
    )

    async def fake_render(character):
        return b"JPEG-SEARCH"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(
            matcher, _FakeEvent(111), "collection search ナツメ"
        )
    )
    text = str(matcher.sent[-1])
    assert "图鉴角色" in text
    assert "base64://" in text


async def test_collection_search_prefix_no_match(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.collection_book.config, "data_dir", str(data_dir))
    commands.collection_book._loaded = False
    commands.collection_book.rec_collect_id(111, "c1", name="四季 ナツメ")

    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(
            matcher, _FakeEvent(111), "collection search 不存在"
        )
    )
    text = str(matcher.sent[-1])
    assert "没有找到「不存在」" in text
    assert "试试更短的名字或作品名" in text


async def test_collection_search_requires_keyword(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.collection_book.config, "data_dir", str(data_dir))
    commands.collection_book._loaded = False

    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(111), "collection search")
    )
    assert "用法：/waifu collection search <关键词>" in str(matcher.sent[-1])


async def test_collection_search_multiple_shows_indices(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.collection_book.config, "data_dir", str(data_dir))
    commands.collection_book._loaded = False
    for index in range(1, 11):
        commands.collection_book.rec_collect_id(
            111, f"c{index}", name=f"角色{index:02d}"
        )

    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(111), "collection search 角色")
    )
    text = str(matcher.sent[-1])
    assert "找到 10 个匹配角色" in text
    numbered = [line for line in text.splitlines() if line[:1].isdigit()]
    assert len(numbered) == 8
    assert "另有 2 个" in text
    assert "发序号或更精确的名字查看卡片：/waifu collection <序号|名字>" in text


async def test_company_collection_search_prefix(monkeypatch, tmp_path) -> None:
    """/keywaifu collection search <关键词> 只在 Key 图鉴内搜索。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.collection_book.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_company_library(
        library_root, "Key", "p24", "Key", "c100", "Key酱"
    )
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()
    commands.collection_book._loaded = False
    commands.collection_book.rec_collect_id(
        111, "c100", name="Key酱", source="key"
    )

    async def fake_render(character):
        return b"JPEG-KEY-SEARCH"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(
        commands._handle_yuzu_trade(
            matcher,
            _FakeEvent(111),
            "collection",
            "search Key酱",
            source="key",
        )
    )
    text = str(matcher.sent[-1])
    assert "Key图鉴角色" in text
    assert "base64://" in text


async def test_collection_search_with_company_alias(monkeypatch, tmp_path) -> None:
    """/waifu collection yuzu search <关键词> 只在柚子社图鉴内搜索。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.collection_book.config, "data_dir", str(data_dir))
    commands.collection_book._loaded = False
    commands.collection_book.rec_collect_id(
        111, "c1", name="柚子酱", source="yuzu"
    )
    commands.collection_book.rec_collect_id(
        111, "c2", name="Key酱", source="key"
    )

    async def fake_render(character):
        return b"JPEG-YUZU-SEARCH"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(
            matcher, _FakeEvent(111), "collection yuzu search 柚子"
        )
    )
    text = str(matcher.sent[-1])
    assert "柚子酱" in text
    assert "Key酱" not in text


async def test_collection_other_user_by_at_requires_admin(
    monkeypatch, tmp_path
) -> None:
    """普通用户 @某人 不能查看对方图鉴。"""
    import waifu_box.collection_book as cb

    data_dir = tmp_path / "data"
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(cb.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection.config, "data_dir", str(data_dir))
    cb._loaded = False
    cb.rec_collect_id(
        222, "c1", name="他人角色", source="yuzu", role="primary"
    )

    event = _FakeGroupEvent(123, 912875556)
    event.message = Message([MessageSegment.at(222)])
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, event, "collection"))

    text = str(matcher.sent[-1])
    assert "只有管理员可以查看他人图鉴" in text
    assert "他人角色" not in text


async def test_collection_other_user_at_pagination_admin(
    monkeypatch, tmp_path
) -> None:
    """管理员 @他人 查看图鉴时，分页提示使用对方 QQ 号。"""
    import waifu_box.collection_book as cb

    data_dir = tmp_path / "data"
    _make_admin(data_dir)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(cb.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection.config, "data_dir", str(data_dir))
    cb._loaded = False
    for index in range(1, 11):
        cb.rec_collect_id(
            222,
            f"c{index}",
            name=f"他人角色{index:02d}",
            source="yuzu",
        )

    event = _FakeGroupEvent(999, 912875556)
    event.message = Message([MessageSegment.at(222)])
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, event, "collection"))
    text = str(matcher.sent[-1])
    assert "他人的图鉴" in text
    assert "下一页：/waifu collection 222 page 2" in text

    matcher2 = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher2, event, "collection page 2")
    )
    text2 = str(matcher2.sent[-1])
    assert "第 2/2 页" in text2
    assert "上一页：/waifu collection 222 page 1" in text2


async def test_fixed_company_falls_back_to_vndb_when_local_missing(
    monkeypatch, tmp_path
) -> None:
    """本地库没有该会社时，会社入口回退 VNDB 而不是报抽不到。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    async def fake_company_ids(company_key):
        assert company_key == "hooksoft"
        return ["p999"]

    async def fake_random(**kwargs):
        assert kwargs["company_ids"] == ["p999"]
        return _character("c-vndb")

    monkeypatch.setattr(commands, "_company_ids", fake_company_ids)
    monkeypatch.setattr(vndb, "random_female_character", fake_random)

    matcher = _FakeMatcher()
    await _run(
        commands._cmd_waifu(matcher, _FakeEvent(123), "", source="hook")
    )

    record = waifu.get_today_waifu(123)
    assert record is not None
    assert record["source"] == "hook"
    assert record["character_id"] == "c-vndb"
    assert "base64://" in str(matcher.sent[-1])


async def test_waifu_reset_at_and_undo(monkeypatch, tmp_path) -> None:
    """管理员可 @某人 reset，并用 /waifu undo 撤销。"""
    data_dir = tmp_path / "data"
    _make_admin(data_dir)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    waifu.save_waifu(123, _character("c-reset"))

    event = _FakeGroupEvent(999, 912875556)
    event.message = Message([MessageSegment.at(123)])
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, event, "reset"))

    assert waifu.get_today_waifu(123) is None
    assert "已重置用户 123" in str(matcher.sent[-1])
    assert "/waifu undo" in str(matcher.sent[-1])

    undo_matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(undo_matcher, _FakeEvent(999), "undo"))
    assert waifu.get_today_waifu(123) is not None
    assert "已撤销" in str(undo_matcher.sent[-1])


async def test_waifu_undo_requires_admin(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(commands.config, "data_dir", str(tmp_path))
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), "undo"))
    assert "只有管理员可以撤销" in str(matcher.sent[-1])


async def test_waifu_undo_without_history(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    _make_admin(data_dir)
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(999), "undo"))
    assert "没有可撤销的 reset 记录" in str(matcher.sent[-1])


async def test_default_waifu_shows_company_pool_hint(
    monkeypatch, tmp_path
) -> None:
    """默认 /waifu 抽卡后提示可指定会社卡池。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu_usage.config, "data_dir", str(data_dir))
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    library_root = tmp_path / "final_company_library"
    _build_fake_library(library_root)
    monkeypatch.setattr(library.config, "library_dir", str(library_root))
    library.reset_cache()

    async def fake_render(character):
        return b"JPEG-HINT"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), ""))

    assert len(matcher.sent) == 1
    text = str(matcher.sent[-1])
    assert "📖" in text
    assert "/waifu collection" in text
    assert "卡池提示" in text
    assert "/waifu yuzu" in text
    assert "base64://" in text
    assert waifu.get_today_waifu(123)["source"] == "waifu"


async def test_waifu_help_lists_special_pools() -> None:
    """/waifu help 展示包含特殊卡池入口的完整帮助。"""
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), "help"))
    text = str(matcher.sent[-1])
    assert "/makurawaifu" in text
    assert "/augustwaifu" in text
    assert "/nitroplus" in text
    assert "stats" not in text
    assert "rank" not in text


@pytest.mark.parametrize(
    "value,directory,company_id,vndb_name,char_id,char_name,source",
    [
        ("yuzu", "Yuzusoft", "p98", "Yuzusoft", "c600", "Yuzu酱", "yuzu"),
        ("smee", "SMEE", "p328", "SMEE", "c601", "SMEE酱", "smee"),
        ("asa", "ASa Project", "p371", "ASa Project", "c602", "ASa酱", "asa"),
        ("makura", "Makura", "p259", "Makura", "c603", "Makura酱", "makura"),
        ("august", "AUGUST", "p95", "AUGUST", "c604", "August酱", "august"),
        ("nitro", "ニトロプラス", "p42", "NITRO PLUS", "c605", "Nitro酱", "nitro"),
        ("nitroplus", "ニトロプラス", "p42", "NITRO PLUS", "c606", "Nitro酱", "nitro"),
        ("qruppo", "Qruppo", "p7659", "Qruppo", "c607", "Qruppo酱", "qruppo"),
        ("qroppo", "Qruppo", "p7659", "Qruppo", "c608", "Qruppo酱", "qruppo"),
    ],
)
async def test_waifu_company_prefix_selects_pool(
    monkeypatch,
    tmp_path,
    value,
    directory,
    company_id,
    vndb_name,
    char_id,
    char_name,
    source,
) -> None:
    """/waifu <会社> 直接选择对应会社池，且不弹默认池提示。"""
    _prepare_company_test(
        monkeypatch,
        tmp_path,
        directory,
        company_id,
        vndb_name,
        char_id,
        char_name,
    )

    async def fake_render(character):
        return b"JPEG-PREFIX"

    monkeypatch.setattr(commands.card, "render_character_card", fake_render)
    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(123), value))

    record = waifu.get_today_waifu(123)
    assert record is not None
    assert record["source"] == source
    assert record["character_id"] == char_id
    assert not any("卡池提示" in str(item) for item in matcher.sent)
    assert "base64://" in str(matcher.sent[-1])


async def test_waifu_company_prefix_collection_filters_pool(
    monkeypatch, tmp_path
) -> None:
    """/waifu yuzu collection 等价于 /yuzuwaifu collection。"""
    import waifu_box.collection_book as cb

    data_dir = tmp_path / "data"
    monkeypatch.setattr(commands.config, "data_dir", str(data_dir))
    monkeypatch.setattr(waifu.config, "data_dir", str(data_dir))
    monkeypatch.setattr(cb.config, "data_dir", str(data_dir))
    monkeypatch.setattr(collection.config, "data_dir", str(data_dir))
    cb._loaded = False
    cb.rec_collect_id(111, "c-yuzu", name="柚子角色", source="yuzu")
    cb.rec_collect_id(111, "c-waifu", name="普通角色", source="waifu")

    matcher = _FakeMatcher()
    await _run(commands._cmd_waifu(matcher, _FakeEvent(111), "yuzu collection"))
    text = str(matcher.sent[-1])
    assert "柚子角色" in text
    assert "普通角色" not in text
