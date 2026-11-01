"""深藏彩蛋 /shou help → /waifu help → /shoukeni 测试。"""

from __future__ import annotations

from waifu_box import shoukeni, shoukeni_state, waifu


class _Event:
    def __init__(self, user_id: int, text: str) -> None:
        self.user_id = user_id
        self._text = text

    def get_plaintext(self) -> str:
        return self._text


class _Matcher:
    def __init__(self) -> None:
        self.sent: list = []

    async def finish(self, message=None) -> None:
        self.sent.append(message)
        raise _Stop()


class _Stop(Exception):
    pass


async def _run(coro) -> None:
    try:
        await coro
    except _Stop:
        pass


def _setup(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(waifu.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(shoukeni_state.config, "data_dir", str(tmp_path))


def test_shoukeni_state_requires_sequence(monkeypatch, tmp_path) -> None:
    _setup(monkeypatch, tmp_path)

    shoukeni_state.note_waifu_help(1)
    assert shoukeni_state.claim(1) == "not_ready"

    shoukeni_state.note_shou_help(1)
    shoukeni_state.note_waifu_help(1)
    assert shoukeni_state.claim(1) == "granted"
    assert shoukeni_state.has_token(1) is True
    assert shoukeni_state.claim(1) == "already"
    assert shoukeni_state.consume_token(1) is True
    assert shoukeni_state.has_token(1) is False
    assert shoukeni_state.claim(1) == "used"


async def test_shoukeni_help_tracking_and_command(
    monkeypatch, tmp_path
) -> None:
    _setup(monkeypatch, tmp_path)

    await shoukeni._track_help(_Event(1, "/shou help"))
    await shoukeni._track_help(_Event(1, "/waifu help"))

    matcher = _Matcher()
    await _run(shoukeni.handle_shoukeni(_Event(1, "/shoukeni"), matcher))
    assert "自选机会" in str(matcher.sent[-1])
    assert shoukeni_state.has_token(1) is True

    matcher2 = _Matcher()
    await _run(shoukeni.handle_shoukeni(_Event(1, "/shoukeni"), matcher2))
    assert "已经领取" in str(matcher2.sent[-1])


def test_shoukeni_slash_rule() -> None:
    assert shoukeni._is_slash_shoukeni(_Event(1, "/shoukeni"))
    assert not shoukeni._is_slash_shoukeni(_Event(1, "shoukeni"))
