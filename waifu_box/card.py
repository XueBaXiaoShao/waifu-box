"""角色信息卡片渲染：左立绘、右信息/简介、右下会社 logo。"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import logos
from .http import request

CARD_WIDTH = 1100
CARD_HEIGHT = 820
LEFT_RIGHT_GAP = 455
RIGHT_LEFT = 470
RIGHT_WIDTH = CARD_WIDTH - RIGHT_LEFT - 24
BOTTOM_RESERVE = 130

_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
_FONT_FILE = _FONT_DIR / "NotoSansSC-Regular.otf"


def _font(size: int) -> ImageFont.FreeTypeFont:
    if _FONT_FILE.is_file():
        return ImageFont.truetype(str(_FONT_FILE), size=size)
    try:
        return ImageFont.load_default(size=size)  # type: ignore[call-arg]
    except TypeError:
        return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, size: int, max_width: int) -> ImageFont.FreeTypeFont:
    """按可用宽度缩小字号，避免超长角色名溢出。"""
    font = _font(size)
    while size > 18 and draw.textlength(text, font=font) > max_width:
        size -= 2
        font = _font(size)
    return font


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """按像素宽度逐字换行，兼容中日韩混排。"""
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        candidate = current + char
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    max_width: int,
    max_y: int,
    line_spacing: int = 6,
) -> None:
    x, y = xy
    for line in _wrap_text(draw, text, font, max_width):
        if y > max_y:
            break
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_spacing


def _draw_info_line(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    value: str,
    label_font: ImageFont.FreeTypeFont,
    value_font: ImageFont.FreeTypeFont,
    accent: tuple[int, int, int],
    text_color: tuple[int, int, int],
    max_width: int,
) -> int:
    draw.text((x, y), label, font=label_font, fill=accent)
    label_width = draw.textlength(label, font=label_font)
    value_width = max_width - label_width - 10
    lines = _wrap_text(draw, value, value_font, max(60, value_width))
    if not lines:
        return y + max(label_font.size, value_font.size) + 12
    draw.text(
        (x + label_width + 10, y),
        lines[0],
        font=value_font,
        fill=text_color,
    )
    for index, line in enumerate(lines[1:3], start=1):
        draw.text(
            (x, y + index * (value_font.size + 4)),
            line,
            font=value_font,
            fill=text_color,
        )
    return y + (min(2, max(0, len(lines) - 1)) + 1) * (
        value_font.size + 4
    ) + 8


def _paste_cover(canvas: Image.Image, image_bytes: bytes, area: tuple[int, int, int, int]) -> None:
    """把角色立绘等比缩放到左侧区域并居中。"""
    left, top, right, bottom = area
    target_w = right - left
    target_h = bottom - top
    try:
        portrait = Image.open(BytesIO(image_bytes)).convert("RGBA")
    except Exception:
        return
    scale = min(target_w / portrait.width, target_h / portrait.height)
    new_size = (
        max(1, int(portrait.width * scale)),
        max(1, int(portrait.height * scale)),
    )
    portrait = portrait.resize(new_size, Image.LANCZOS)
    x = left + (target_w - new_size[0]) // 2
    y = top + (target_h - new_size[1]) // 2
    canvas.paste(portrait, (x, y), portrait)


def _paste_logo(canvas: Image.Image, company_ids: list[str] | None) -> None:
    """右下角粘贴来源会社 logo。"""
    path = logos.logo_path_for_companies(company_ids)
    if path is None:
        return
    try:
        logo = Image.open(path).convert("RGBA")
    except Exception:
        return
    max_w, max_h = 220, 100
    scale = min(max_w / logo.width, max_h / logo.height)
    new_size = (
        max(1, int(logo.width * scale)),
        max(1, int(logo.height * scale)),
    )
    logo = logo.resize(new_size, Image.LANCZOS)
    x = CARD_WIDTH - 24 - new_size[0]
    y = CARD_HEIGHT - 24 - new_size[1]
    canvas.paste(logo, (x, y), logo)


def render_card(
    character: Any,
    image_bytes: bytes,
    *,
    company_name: str = "",
) -> bytes:
    """渲染角色信息卡，返回 JPEG 字节。"""
    canvas = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), "#f7f5f2")
    draw = ImageDraw.Draw(canvas)
    accent = (216, 93, 128)
    title_color = (44, 38, 42)
    text_color = (70, 62, 68)
    muted = (130, 120, 124)

    # 左侧立绘区
    draw.rounded_rectangle(
        (18, 18, 440, CARD_HEIGHT - 18),
        radius=18,
        fill="#ece7e3",
    )
    _paste_cover(canvas, image_bytes, (30, 30, 428, CARD_HEIGHT - 30))

    # 右侧分隔
    draw.line(
        (LEFT_RIGHT_GAP, 26, LEFT_RIGHT_GAP, CARD_HEIGHT - 26),
        fill="#ded6d0",
        width=2,
    )

    x = RIGHT_LEFT
    y = 26
    draw.text((x, y), "今日老婆", font=_font(24), fill=accent)
    y += 36

    name = character.name or "未知角色"
    name_font = _fit_font(draw, name, 42, RIGHT_WIDTH)
    draw.text((x, y), name, font=name_font, fill=title_color)
    y += name_font.size + 8

    cn_name = getattr(character, "cn_name", "") or ""
    if cn_name and cn_name != name:
        draw.text((x, y), cn_name, font=_font(24), fill=muted)
        y += 34
    y += 8

    game = character.game
    game_title = game.title or game.jp_title
    if game.cn_title and game.cn_title != game_title:
        game_title = f"{game_title}（{game.cn_title}）"
    info_rows = [
        ("作品", game_title),
        ("会社", company_name),
        (
            "角色定位",
            {
                "main": "主角",
                "primary": "主要角色",
                "side": "配角",
                "appears": "客串",
            }.get(
                str(character.data.get("role") or ""),
                str(character.data.get("role") or "未知"),
            ),
        ),
        ("CV", " / ".join(character.cv) if character.cv else "未收录"),
    ]
    if game.year:
        info_rows.insert(3, ("发售", str(game.year)))

    info_font = _font(24)
    for label, value in info_rows:
        y = _draw_info_line(
            draw,
            x,
            y,
            label,
            value,
            _font(22),
            info_font,
            accent,
            text_color,
            RIGHT_WIDTH,
        )

    y += 8
    intro = (
        character.cn_description
        or character.description
        or str(character.data.get("jp_description") or "")
    ).strip()
    if not intro:
        tags = character.data.get("tags") or []
        tag_names = [str(tag.get("name")) for tag in tags if tag.get("name")]
        if tag_names:
            intro = "角色特征：" + "、".join(tag_names[:10]) + "。"
    if not intro:
        intro = "暂无简介"
    if len(intro) > 700:
        intro = intro[:700].rsplit(" ", 1)[0] + "……"
    draw.text((x, y), "简介", font=_font(24), fill=accent)
    y += 36
    intro_font = _font(22)
    _draw_text_block(
        draw,
        (x, y),
        intro,
        intro_font,
        text_color,
        RIGHT_WIDTH,
        CARD_HEIGHT - BOTTOM_RESERVE - 10,
        line_spacing=7,
    )

    _paste_logo(canvas, character.company_ids)

    buffer = BytesIO()
    canvas.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


async def render_character_card(character: Any) -> bytes | None:
    """下载角色立绘并渲染卡片；失败返回 None。"""
    if not character.image_url:
        return None
    try:
        image_bytes = await request(
            "GET",
            character.image_url,
            res_type="bytes",
        )
    except Exception:
        return None
    company_name = "、".join(logos.company_names(character.company_ids))
    try:
        return render_card(character, image_bytes, company_name=company_name)
    except Exception:
        return None


def base64_image(data: bytes) -> str:
    """转成 OneBot 可发送的 base64 图片。"""
    return base64.b64encode(data).decode()
