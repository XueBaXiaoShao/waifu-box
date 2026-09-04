"""每日老婆交易系统测试。"""

from __future__ import annotations

import json

import pytest

from waifu_box import collection, waifu
from waifu_box.models import Image, VNDBCharacter, VnRef


def _set_today(
    tmp_path, monkeypatch, user_id: int, char_id: str, role: str
) -> dict:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(collection.config, "data_dir", str(tmp_path))
    return waifu.save_waifu(
        user_id,
        VNDBCharacter(
            id=char_id,
            name=f"Hero-{char_id}",
            original=f"ヒーロー-{char_id}",
            image=Image(url="https://t.vndb.org/1.jpg"),
            vns=[VnRef(id="v1", title="Game")],
        ),
        source="yuzu",
        role=role,
    )


def test_rarity_for_role() -> None:
    assert collection.rarity_for_role("primary") == ("SSR", 5)
    assert collection.rarity_for_role("main") == ("SR", 4)
    assert collection.rarity_for_role("side") == ("R", 3)
    assert collection.rarity_for_role("appears") == ("N", 2)
    assert collection.rarity_for_role("") == ("N", 2)
    assert collection.rarity_for_role("unknown") == ("N", 2)


def test_waifu_display(tmp_path, monkeypatch) -> None:
    record = _set_today(tmp_path, monkeypatch, 1, "c1", "primary")
    line = collection.waifu_display(record)
    assert line == "★★★★★ SSR ヒーロー-c1（Game）"
    # 记录没有 role 时按默认稀有度展示，不报错
    record2 = _set_today(tmp_path, monkeypatch, 2, "c2", "")
    line2 = collection.waifu_display(record2)
    assert line2 == "★★ N ヒーロー-c2（Game）"


def test_role_backfill_from_library(tmp_path, monkeypatch) -> None:
    """记录缺 role 时回查本地资料库 JSON 补稀有度。"""
    library_dir = tmp_path / "library"
    role_file = library_dir / "ゆずソフト" / "RIDDLE JOKER" / "角色" / "壬生 千咲.json"
    role_file.parent.mkdir(parents=True)
    role_file.write_text(json.dumps({"role": "primary"}), encoding="utf-8")
    monkeypatch.setattr(collection.config, "library_dir", str(library_dir))
    record = _set_today(tmp_path, monkeypatch, 1, "c1", "")
    record["library_path"] = "ゆずソフト/RIDDLE JOKER/角色/壬生 千咲.json"
    assert collection.role_of_record(record) == "primary"
    assert collection.rarity_of_record(record) == ("SSR", 5)
    # 查不到时回退默认
    record["library_path"] = "missing.json"
    assert collection.role_of_record(record) == ""


def test_trade_flow(tmp_path, monkeypatch) -> None:
    _set_today(tmp_path, monkeypatch, 111, "c1", "primary")
    _set_today(tmp_path, monkeypatch, 222, "c2", "side")

    trade = collection.propose_trade(111, 222)
    trade_id = trade["id"]
    assert trade["status"] == "pending"

    # 对方接受后今日老婆互换
    give, take, done = collection.accept_trade(trade_id, 222)
    assert give["character_id"] == "c1"
    assert take["character_id"] == "c2"
    assert waifu.get_today_waifu(111)["character_id"] == "c2"
    assert waifu.get_today_waifu(222)["character_id"] == "c1"
    # 交易记录必须保留在 waifu_trades.json（不能把老婆内容写进去）
    trades = json.loads((tmp_path / "waifu_trades.json").read_text("utf-8"))
    assert set(trades.keys()) == {"trades"}
    assert trades["trades"][0]["id"] == trade_id
    assert trades["trades"][0]["status"] == "done"
    # 重复接受报错
    with pytest.raises(ValueError):
        collection.accept_trade(trade_id, 222)


def test_trade_validation(tmp_path, monkeypatch) -> None:
    _set_today(tmp_path, monkeypatch, 111, "c1", "primary")
    _set_today(tmp_path, monkeypatch, 222, "c2", "side")

    # 不能和自己交易
    with pytest.raises(ValueError):
        collection.propose_trade(111, 111)
    # 只有目标用户可接受
    trade_id = collection.propose_trade(111, 222)["id"]
    with pytest.raises(ValueError):
        collection.accept_trade(trade_id, 111)
    # 非目标用户不能拒绝
    with pytest.raises(ValueError):
        collection.reject_trade(trade_id, 111)
    # 发起人可撤销
    collection.cancel_trade(trade_id, 111)
    with pytest.raises(ValueError):
        collection.accept_trade(trade_id, 222)


def test_trade_requires_today_waifu(tmp_path, monkeypatch) -> None:
    # 发起人没抽今天
    _set_today(tmp_path, monkeypatch, 222, "c2", "side")
    with pytest.raises(ValueError):
        collection.propose_trade(111, 222)
    # 对方没抽今天
    _set_today(tmp_path, monkeypatch, 111, "c1", "primary")
    with pytest.raises(ValueError):
        collection.propose_trade(111, 333)
    # 接受时有一方没抽（已过期）则失效
    trade_id = collection.propose_trade(111, 222)["id"]
    state = json.loads((tmp_path / "waifu_state.json").read_text("utf-8"))
    state["users"]["222"]["date"] = "1999-01-01"
    (tmp_path / "waifu_state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        collection.accept_trade(trade_id, 222)


def test_trade_yuzu_only(tmp_path, monkeypatch) -> None:
    """非柚子社角色（无本地库、/waifu 抽的）暂时不能交易。"""
    _set_today(tmp_path, monkeypatch, 111, "c1", "primary")
    waifu.save_waifu(
        222,
        VNDBCharacter(id="c2", name="Hero-222", original="ヒーロー-222"),
        source="waifu",
        role="main",
    )
    # 对方是 /waifu 抽的未知会社角色 → 不能交易
    with pytest.raises(ValueError):
        collection.propose_trade(111, 222)
    with pytest.raises(ValueError):
        collection.propose_trade(222, 111)
    # 接受时如果有一方变成了非柚子社（管理员 set 过），交易失效
    _set_today(tmp_path, monkeypatch, 222, "c2", "side")
    trade_id = collection.propose_trade(111, 222)["id"]
    state = json.loads((tmp_path / "waifu_state.json").read_text("utf-8"))
    state["users"]["222"]["source"] = "waifu"
    (tmp_path / "waifu_state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        collection.accept_trade(trade_id, 222)


def test_trade_yuzu_by_company(tmp_path, monkeypatch) -> None:
    """/waifu 抽到柚子社角色（按 library_path 会社判断）同样可以交易。"""
    library_dir = tmp_path / "library"
    char_file = (
        library_dir
        / "ゆずソフト"
        / "ライムライト・レモネードジャム"
        / "角色"
        / "礫川 美玖.json"
    )
    char_file.parent.mkdir(parents=True)
    char_file.write_text(json.dumps({"company_ids": ["p98"]}), encoding="utf-8")
    monkeypatch.setattr(collection.config, "library_dir", str(library_dir))

    _set_today(tmp_path, monkeypatch, 111, "c1", "primary")
    waifu.save_waifu(
        222,
        VNDBCharacter(id="c2", name="Hero-222", original="ヒーロー-222"),
        source="waifu",
        role="primary",
        library_path="ゆずソフト/ライムライト・レモネードジャム/角色/礫川 美玖.json",
    )
    assert collection.is_yuzu_record(waifu.get_today_waifu(222))
    trade_id = collection.propose_trade(111, 222)["id"]
    give, take, _ = collection.accept_trade(trade_id, 222)
    assert give["character_id"] == "c1"
    assert take["character_id"] == "c2"

    # 非柚子社的本地库角色仍不可交易
    other_file = (
        library_dir / "ほかほか" / "その他" / "角色" / "誰か.json"
    )
    other_file.parent.mkdir(parents=True)
    other_file.write_text(
        json.dumps({"company_ids": ["p999"]}), encoding="utf-8"
    )
    waifu.save_waifu(
        333,
        VNDBCharacter(id="c3", name="Hero-333", original="ヒーロー-333"),
        source="waifu",
        role="main",
        library_path="ほかほか/その他/角色/誰か.json",
    )
    with pytest.raises(ValueError):
        collection.propose_trade(111, 333)


def test_trade_reject_and_expire(tmp_path, monkeypatch) -> None:
    _set_today(tmp_path, monkeypatch, 111, "c1", "primary")
    _set_today(tmp_path, monkeypatch, 222, "c2", "side")
    trade_id = collection.propose_trade(111, 222)["id"]
    collection.reject_trade(trade_id, 222)
    with pytest.raises(ValueError):
        collection.accept_trade(trade_id, 222)

    # 过期交易无法接受
    monkeypatch.setattr(collection, "TRADE_TTL_SECONDS", 0)
    trade_id2 = collection.propose_trade(111, 222)["id"]
    with pytest.raises(ValueError):
        collection.accept_trade(trade_id2, 222)


def test_pending_trades(tmp_path, monkeypatch) -> None:
    _set_today(tmp_path, monkeypatch, 111, "c1", "primary")
    _set_today(tmp_path, monkeypatch, 222, "c2", "side")
    collection.propose_trade(111, 222)
    assert len(collection.pending_trades(111)) == 1
    assert len(collection.pending_trades(222)) == 1
    assert collection.pending_trades(333) == []
    assert len(collection.pending_incoming(222)) == 1
    assert collection.pending_incoming(111) == []
    assert len(collection.pending_outgoing(111)) == 1
    assert collection.pending_outgoing(222) == []


def test_pending_multiple(tmp_path, monkeypatch) -> None:
    _set_today(tmp_path, monkeypatch, 111, "c1", "primary")
    _set_today(tmp_path, monkeypatch, 222, "c2", "side")
    _set_today(tmp_path, monkeypatch, 333, "c3", "main")
    collection.propose_trade(111, 222)
    collection.propose_trade(333, 222)
    assert len(collection.pending_incoming(222)) == 2
    assert len(collection.pending_outgoing(111)) == 1


def test_ranking(tmp_path, monkeypatch) -> None:
    _set_today(tmp_path, monkeypatch, 1, "c1", "primary")  # 5★
    _set_today(tmp_path, monkeypatch, 2, "c3", "main")  # 4★
    _set_today(tmp_path, monkeypatch, 3, "c4", "side")  # 3★
    records = waifu.all_today_waifu()
    entries = collection.ranking(records)
    assert entries == [(1, 5, "SSR"), (2, 4, "SR"), (3, 3, "R")]
    # 按群过滤
    assert waifu.all_today_waifu(group_id=999) == []