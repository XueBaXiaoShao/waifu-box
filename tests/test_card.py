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
