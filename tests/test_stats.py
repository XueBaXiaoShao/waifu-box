"""waifu 抽卡统计测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from waifu_box import stats


def test_week_top_counts_recorded_draws(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(stats.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(stats.waifu.config, "data_dir", str(tmp_path))
    stats._history_loaded = False

    now = datetime.now(timezone.utc)
    stats.record_draw("c1", "角色一", now=now)
    stats.record_draw("c1", "角色一", now=now)
    stats.record_draw("c2", "角色二", now=now)

    top = stats.week_top(days=7, limit=10)
    assert top[0]["character_id"] == "c1"
    assert top[0]["count"] == 2
    assert top[1]["character_id"] == "c2"
    assert top[1]["count"] == 1


def test_week_top_excludes_old_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(stats.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(stats.waifu.config, "data_dir", str(tmp_path))
    stats._history_loaded = False

    old = datetime.now(timezone.utc) - timedelta(days=30)
    stats.record_draw("c_old", "旧角色", now=old)
    stats.record_draw("c_new", "新角色")

    top = stats.week_top(days=7)
    assert len(top) == 1
    assert top[0]["character_id"] == "c_new"


def test_week_top_text_ranks_names(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(stats.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(stats.waifu.config, "data_dir", str(tmp_path))
    stats._history_loaded = False

    stats.record_draw("c1", "四季 ナツメ")
    stats.record_draw("c1", "四季 ナツメ")
    stats.record_draw("c2", "野村 美希")

    text = stats.week_top_text(days=7, limit=10)
    assert "四季 ナツメ（2 次）" in text
    assert "野村 美希（1 次）" in text


def test_history_imports_recent_state_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(stats.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(stats.waifu.config, "data_dir", str(tmp_path))
    stats._history_loaded = False

    # 写入 waifu_state.json 近期记录（兼容旧数据）
    state_path = tmp_path / "waifu_state.json"
    state_path.write_text(
        "{\"users\": {\"1\": {\"date\": \"%s\", \"character_id\": \"ch_a\", \"name\": \"昨日角色\"}}}"
        % (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
        encoding="utf-8",
    )

    top = stats.week_top(days=7)
    assert any(row["character_id"] == "ch_a" for row in top)
    row = next(row for row in top if row["character_id"] == "ch_a")
    assert row["name"] == "昨日角色"


def test_week_top_ties_ordered_by_gojuon(tmp_path, monkeypatch) -> None:
    """次数相同时按五十音序排列（假名名在前，汉字名在后）。"""
    monkeypatch.setattr(stats.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(stats.waifu.config, "data_dir", str(tmp_path))
    stats._history_loaded = False

    stats.record_draw("c1", "あおい")   # あ → 前
    stats.record_draw("c2", "さくら")   # さ → 后于 あ
    stats.record_draw("c3", "かえで")   # か → 中
    stats.record_draw("c4", "漢字名")   # 汉字 → 末尾

    top = stats.week_top(days=7, limit=10)
    names = [row["name"] for row in top]
    assert names == ["あおい", "かえで", "さくら", "漢字名"]


def test_week_top_source_filter_yuzu(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(stats.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(stats.waifu.config, "data_dir", str(tmp_path))
    stats._history_loaded = False

    stats.record_draw("c1", "あおい", source="yuzu")
    stats.record_draw("c2", "かえで", source="waifu")

    top = stats.week_top(days=7, limit=10, source="yuzu")
    assert [row["character_id"] for row in top] == ["c1"]
    top_all = stats.week_top(days=7, limit=10)
    assert {row["character_id"] for row in top_all} == {"c1", "c2"}


def test_week_top_text_yuzu_label(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(stats.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(stats.waifu.config, "data_dir", str(tmp_path))
    stats._history_loaded = False

    stats.record_draw("c1", "あおい", source="yuzu")
    text = stats.week_top_text(days=7, limit=10, source="yuzu")
    assert "柚子社" in text
    assert "あおい" in text

def test_week_top_source_filter_fixed_company(tmp_path, monkeypatch) -> None:
    """Key/SAGA/Purple 等固定会社入口可按来源过滤并显示会社名。"""
    monkeypatch.setattr(stats.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(stats.waifu.config, "data_dir", str(tmp_path))
    stats._history_loaded = False

    stats.record_draw("c-key", "Key酱", source="key")
    stats.record_draw("c-waifu", "普通酱", source="waifu")

    top = stats.week_top(days=7, limit=10, source="key")
    assert [row["character_id"] for row in top] == ["c-key"]
    text = stats.week_top_text(days=7, limit=10, source="key")
    assert "Key" in text
    assert "Key酱" in text
    assert "普通酱" not in text
