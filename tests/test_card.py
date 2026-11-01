"""角色信息卡片渲染测试。"""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from waifu_box import card


def _image_bytes() -> bytes:
    image = Image.new("RGB", (250, 300), (120, 180, 220))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_render_card_returns_jpeg(tmp_path) -> None:
    character = _FakeCharacter()
    data = card.render_card(
        character,
        _image_bytes(),
        company_name="Yuzusoft（柚子社）",
        header="今日生日",
    )
    assert data[:2] == b"\xff\xd8"
    rendered = Image.open(BytesIO(data))
    assert rendered.size == (card.CARD_WIDTH, card.CARD_HEIGHT)
    assert card.base64_image(data).startswith("/9j/")


async def test_render_character_card_downloads_image(monkeypatch) -> None:
    character = _FakeCharacter()

    async def fake_request(method, url, **kwargs):
        assert url == character.image_url
        return _image_bytes()

    monkeypatch.setattr(card, "request", fake_request)
    data = await card.render_character_card(character)
    assert data is not None and data[:2] == b"\xff\xd8"


class _FakeCharacter:
    id = "c1"
    name = "ヒロイン"
    original = "ヒロイン"
    cn_name = "女主角"
    image_url = "https://t.vndb.org/ch/1/1.jpg"
    description = "A lovely heroine."
    cn_description = "可爱的主角。"
    cv = ["声优A"]
    company_ids = ["p98"]
    game_ids = ["v1"]
    data = {
        "role": "main",
        "cn_name": "女主角",
        "cn_description": "可爱的主角。",
        "description": "A lovely heroine.",
        "cv": ["声优A"],
        "jp_description": "",
        "company_ids": ["p98"],
    }

    class _Game:
        id = "v1"
        title = "Café Stella"
        jp_title = "喫茶ステラと死神の蝶"
        cn_title = "星光咖啡馆"
        released = "2020-09-24"
        year = 2020

    game = _Game()


def test_display_game_title_skips_duplicate_english_translation() -> None:
    class _Game:
        title = "RIDDLE JOKER"
        jp_title = ""
        cn_title = "Riddle Joker"

    assert card._display_game_title(_Game()) == "RIDDLE JOKER"


def test_display_game_title_keeps_real_translation() -> None:
    class _Game:
        title = "Café Stella"
        jp_title = "喫茶ステラと死神の蝶"
        cn_title = "星光咖啡馆"

    assert card._display_game_title(_Game()) == "Café Stella（星光咖啡馆）"


def test_clean_description_strips_vndb_markup() -> None:
    raw = (
        "[b]Profile[/b]\n"
        "[url=https://vndb.org/c1]Tomohiro[/url] &amp; "
        "[url=/c2]Yukigeshiki[/url]\n"
        "[spoiler]hidden[/spoiler]"
    )
    cleaned = card.clean_description(raw)
    assert "Profile" in cleaned
    assert "Tomohiro" in cleaned
    assert "Yukigeshiki" in cleaned
    assert "hidden" in cleaned
    assert "&" in cleaned
    assert "[url" not in cleaned
    assert "[/url]" not in cleaned
    assert "[b]" not in cleaned
    assert "[/b]" not in cleaned
