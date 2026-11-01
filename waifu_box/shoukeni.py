"""深藏彩蛋：/shou help → /waifu help → /shoukeni。"""

from __future__ import annotations

import re

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.message import event_preprocessor

from . import shoukeni_state


def _is_slash_shoukeni(event: MessageEvent) -> bool:
    text = (event.get_plaintext() or "").lstrip()
    return re.match(r"^/shoukeni(?:\s|$)", text, re.IGNORECASE) is not None


shoukeni = on_command(
    "shoukeni",
    rule=_is_slash_shoukeni,
    priority=5,
    block=True,
)


@event_preprocessor
async def _track_help(event: MessageEvent) -> None:
    if not hasattr(event, "get_plaintext") or not hasattr(event, "user_id"):
        return
    text = (event.get_plaintext() or "").strip()
    if re.match(r"^/(?:shou|show)\s+help\s*$", text, re.IGNORECASE):
        shoukeni_state.note_shou_help(event.user_id)
    elif re.match(r"^/waifu\s+(?:help|帮助)\s*$", text, re.IGNORECASE):
        shoukeni_state.note_waifu_help(event.user_id)


@shoukeni.handle()
async def handle_shoukeni(
    event: MessageEvent,
    matcher: Matcher,
) -> None:
    status = shoukeni_state.claim(event.user_id)
    if status == "granted":
        await matcher.finish(
            "……你找到了。今天有一次自选机会："
            "/waifu set <角色名或cID>（仅限自己）。"
        )
    if status == "already":
        await matcher.finish(
            "今天的机会已经领取过了，直接使用 "
            "/waifu set <角色名或cID> 即可。"
        )
    if status == "used":
        await matcher.finish("今天的机会已经用过了。")
    await matcher.finish("条件还没满足。")
