"""/waifu 与 /yuzuwaifu 命令入口。"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from . import (
    card,
    collection,
    companies,
    http,
    library,
    permissions,
    vndb,
    waifu,
    waifu_cache,
    waifu_usage,
)
from .config import config
from .models import Image, VNDBCharacter, VnRef

# /waifu test 测试抽卡的限定作品（新收录作品的 VNDB ID）
TEST_GAME_IDS = ["v62721", "v50215"]


def _is_slash_waifu(event: MessageEvent) -> bool:
    """/waifu 入口只认带斜杠的命令。"""
    text = (event.get_plaintext() or "").lstrip()
    return re.match(r"^/waifu(?:\s|$)", text, re.IGNORECASE) is not None


def _is_slash_yuzuwaifu(event: MessageEvent) -> bool:
    """/yuzuwaifu 入口只认带斜杠的命令。"""
    text = (event.get_plaintext() or "").lstrip()
    return re.match(r"^/yuzuwaifu(?:\s|$)", text, re.IGNORECASE) is not None


def _plugin_enabled_for_event(event: MessageEvent) -> bool:
    """该群是否启用 waifu_box（读取与 x_admin 共用的 plugin_switches.json）。"""
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return True
    try:
        payload = json.loads(
            (Path(config.data_dir) / "plugin_switches.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(payload, dict):
        return True
    groups = payload.get("groups")
    if isinstance(groups, dict):
        entry = groups.get(str(group_id))
        if isinstance(entry, dict) and "waifu_box" in entry:
            return bool(entry["waifu_box"])
    defaults = payload.get("defaults")
    if isinstance(defaults, dict) and "waifu_box" in defaults:
        return bool(defaults["waifu_box"])
    return True


waifu_short = on_command("waifu", rule=_is_slash_waifu, priority=1, block=True)
yuzuwaifu_short = on_command(
    "yuzuwaifu", rule=_is_slash_yuzuwaifu, priority=1, block=True
)


def _help_text() -> str:
    return """【每日老婆】
- /waifu —— 从本地 VNDB 资料库抽每日老婆，并生成角色信息卡片
- /waifu settings —— 查看/修改抽卡设置（热度、年代、全局会社池；仅管理员）
- /waifu settings group=<群号> kaisha=<会社key|off> —— 群会社后门
- /waifu settings group=<群号> year=off|on —— 该群解除/恢复年代限制
- /waifu settings group=<群号> popular=off|on —— 该群解除/恢复热度限制
- /waifu reset [all|<QQ号>] —— 重置每日额度（仅管理员）
- /waifu check <QQ号> —— 查看指定用户今天抽到的老婆（仅管理员）
- /waifu test —— 测试抽卡（仅管理员；只从新收录作品的角色中抽取，不占用每日额度）
- /yuzuwaifu —— 柚子社专属老婆（固定柚子社，同样输出卡片；与 /waifu 共享每日额度）
- /yuzuwaifu list [<QQ号>|@对方] —— 查看今天的每日老婆（含稀有度）
- /yuzuwaifu trade @对方 —— 提议交换双方的今日柚子社每日老婆（按会社判断，/waifu 抽到柚子社角色也可交易）
- /yuzuwaifu accept|reject —— 接受/拒绝交易（只有一笔时不用交易号）
- /yuzuwaifu cancel —— 撤销自己发起的交易（只有一笔时不用交易号）
- /yuzuwaifu rank —— 今日每日老婆稀有度排行榜"""


@waifu_short.handle()
async def handle_waifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    if not _plugin_enabled_for_event(event):
        await matcher.finish("该群已禁用每日老婆功能")
    value = (arg.extract_plain_text() or "").strip()
    try:
        await _cmd_waifu(matcher, event, value)
    except (http.HttpError, RuntimeError) as exc:
        await matcher.finish(f"waifu 抽卡失败，请稍后再试（{exc}）")


@yuzuwaifu_short.handle()
async def handle_yuzuwaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    if not _plugin_enabled_for_event(event):
        await matcher.finish("该群已禁用每日老婆功能")
    value = (arg.extract_plain_text() or "").strip()
    if value:
        first, _, rest = value.partition(" ")
        first = first.lower()
        if first in (
            "list",
            "trade",
            "rank",
            "accept",
            "reject",
            "cancel",
        ):
            await _handle_yuzu_trade(matcher, event, first, rest.strip())
            return
    try:
        await _cmd_waifu(matcher, event, value, source="yuzu")
    except (http.HttpError, RuntimeError) as exc:
        await matcher.finish(f"yuzuwaifu 抽卡失败，请稍后再试（{exc}）")


def _image_segment(url_or_base64: str | None) -> MessageSegment | None:
    if not url_or_base64:
        return None
    if url_or_base64.startswith("http"):
        return MessageSegment.image(url_or_base64)
    if url_or_base64.startswith("base64://"):
        return MessageSegment.image(url_or_base64)
    return MessageSegment.image(f"base64://{url_or_base64}")


def _message_with_image(image_url: str | None, text: str) -> Message:
    segments: list[MessageSegment] = []
    image = _image_segment(image_url)
    if image is not None:
        segments.append(image)
    if text:
        segments.append(MessageSegment.text(text))
    return Message(segments)


def _waifu_reply(
    event: MessageEvent,
    image_url: str | None,
    text: str,
    at_user_id: int | None = None,
) -> Message:
    segments: list[MessageSegment] = []
    if getattr(event, "group_id", None) is not None:
        target = (
            at_user_id
            if at_user_id is not None
            else getattr(event, "user_id", None)
        )
        if target is not None:
            segments.append(MessageSegment.at(user_id=int(target)))
    image = _image_segment(image_url)
    if image is not None:
        segments.append(image)
    segments.append(MessageSegment.text(text))
    return Message(segments)


def _waifu_text(record: dict, note: str = "") -> str:
    """老婆信息只展示名字与代表作。"""
    name = record.get("original") or record.get("name") or "未知"
    vns = record.get("vns") or []
    representative = vns[0].get("title") if vns and vns[0].get("title") else ""
    lines = (
        [f"你今天的老婆是来自「{representative}」的{name}"]
        if representative
        else [f"你今天的老婆是{name}"]
    )
    if note:
        lines.append(note)
    return "\n".join(lines)


def _to_vndb_character(character: library.LibraryCharacter) -> VNDBCharacter:
    """把本地资料库角色转成现有保存/展示模型。"""
    return VNDBCharacter(
        id=character.id,
        name=character.name,
        original=character.original,
        image=Image(url=character.image_url),
        vns=[
            VnRef(
                id=character.game.id,
                title=character.game.jp_title or character.game.title,
            )
        ],
    )


async def _local_reply_image(
    character: library.LibraryCharacter,
    fallback_url: str = "",
) -> str:
    """渲染本地角色卡片；失败时回退到原立绘 URL。"""
    image_bytes = await card.render_character_card(character)
    if image_bytes:
        return f"base64://{card.base64_image(image_bytes)}"
    return fallback_url


async def _record_reply_image(record: dict) -> str:
    """把已保存的老婆记录渲染成卡片图片；本地库缺失时用同款样式兜底渲染。"""
    reply_image = str(record.get("image_url") or "")
    if record.get("library_path"):
        local = await asyncio.to_thread(
            library.get_character_by_path,
            str(record["library_path"]),
        )
    else:
        # 兼容更新前保存的旧记录：按 VNDB ID 回查本地资料库
        local = await asyncio.to_thread(
            library.get_character_by_id,
            str(record.get("character_id") or ""),
        )
    if local is not None:
        reply_image = await _local_reply_image(local, reply_image)
    else:
        company_ids = (
            ["p98", "p12215"]
            if str(record.get("source") or "") == "yuzu"
            else []
        )
        image_bytes = await card.render_character_card(
            _RecordCharacter(record, company_ids=company_ids)
        )
        if image_bytes:
            reply_image = f"base64://{card.base64_image(image_bytes)}"
    return reply_image


class _RecordCharacter:
    """把已保存的每日老婆记录包装成卡片渲染对象（本地库缺失时的兜底）。

    与本地资料库角色同款卡片样式：左立绘 + 右信息简介 + 右下会社 logo。
    """

    def __init__(
        self, record: dict, company_ids: list[str] | None = None
    ) -> None:
        vns = record.get("vns") or []
        game = vns[0] if vns and isinstance(vns[0], dict) else {}
        self.name = str(
            record.get("original") or record.get("name") or "未知角色"
        )
        self.cn_name = ""
        self.cv: list[str] = []
        self.company_ids = company_ids or []
        self.data: dict = {"role": str(record.get("role") or "")}
        self.game = _CardGame(title=str(game.get("title") or ""))
        self.description = ""
        self.cn_description = ""
        self.image_url = str(record.get("image_url") or "")


class _CardGame:
    """卡片渲染所需的极简作品信息。"""

    def __init__(self, title: str) -> None:
        self.title = title
        self.jp_title = title
        self.cn_title = ""
        self.year: int | None = None


def _library_path(character: library.LibraryCharacter) -> str:
    root = Path(config.library_dir)
    try:
        return character.path.relative_to(root).as_posix()
    except ValueError:
        return character.path.name


async def _draw_local_character(
    settings: dict,
    group_settings: dict,
    source: str = "waifu",
    exclude_ids: set[str] | None = None,
) -> library.LibraryCharacter | None:
    """从 final_company_library 抽卡：优先群会社后门，其次全局会社池。"""
    year_from = 0 if group_settings["year_off"] else settings.get("year_from", 0)
    year_to = 0 if group_settings["year_off"] else settings.get("year_to", 0)
    if source == "yuzu":
        company_ids = ["p98", "p12215"]
        lru = False
    elif group_settings["company_ids"]:
        company_ids = [str(item) for item in group_settings["company_ids"]]
        lru = True
    else:
        _, company_ids = _pick_pool_company(settings)
        lru = True
    return await asyncio.to_thread(
        library.random_character,
        company_ids=company_ids or None,
        year_from=year_from,
        year_to=year_to,
        lru=lru,
        exclude_ids=exclude_ids,
    )


async def _cmd_waifu(
    matcher: Matcher,
    event: MessageEvent,
    value: str,
    source: str = "waifu",
) -> None:
    user_id = int(getattr(event, "user_id", 0))
    group_id = getattr(event, "group_id", None)
    value = (value or "").strip()
    command, _, arg = value.partition(" ")
    command = command.lower()

    if command == "virus":
        await matcher.finish(
            "Special Thanks to 病毒@kitsurato. "
            "病毒@kitsurato様のご協力誠にありがとうございます。"
        )

    if command == "test":
        if not permissions.is_admin(user_id):
            await matcher.finish("只有管理员可以测试抽卡")
        local = await asyncio.to_thread(
            library.random_character,
            game_ids=TEST_GAME_IDS,
        )
        if local is None:
            await matcher.finish("测试角色不存在，请检查资料库")
        image_url = await _local_reply_image(
            local, local.image_url or ""
        )
        await matcher.finish(
            _waifu_reply(event, image_url, "【测试抽卡】新收录作品限定")
        )

    if command == "settings":
        await _handle_waifu_settings(matcher, event, arg.strip())
        return

    is_admin = permissions.is_admin(user_id)

    if not value:
        existing = waifu.get_today_waifu(user_id)
        if existing:
            reply_image = await _record_reply_image(existing)
            if existing.get("source") == "yuzu":
                repeat_note = (
                    "你今天已经抽过 /yuzuwaifu 了，"
                    "这是你今天的柚子社老婆（重复展示）"
                )
            else:
                repeat_note = (
                    "你今天已经抽过 /waifu 了，"
                    "这是你今天的每日老婆（重复展示）"
                )
            await matcher.finish(
                _waifu_reply(
                    event,
                    reply_image,
                    repeat_note,
                )
            )
        settings = waifu.load_settings()
        group_settings = _event_group_settings(event)
        exclude_ids = (
            waifu.taken_character_ids(group_id, user_id)
            if group_id is not None
            else set()
        )
        if not await asyncio.to_thread(library.ensure_index):
            character = await _draw_waifu_character(
                settings, group_settings, source, exclude_ids
            )
            if character is None:
                await matcher.finish("今天暂时抽不到老婆，请稍后再试")
            record = waifu.save_waifu(
                user_id, character, source=source, group_id=group_id
            )
            if source != "yuzu":
                waifu_usage.mark_used(character.id)
            image_url = record.get("image_url")
        else:
            local = await _draw_local_character(
                settings, group_settings, source, exclude_ids
            )
            if local is None:
                await matcher.finish("今天暂时抽不到老婆，请稍后再试")
            character = _to_vndb_character(local)
            record = waifu.save_waifu(
                user_id,
                character,
                source=source,
                library_path=_library_path(local),
                group_id=group_id,
                role=str(local.data.get("role") or ""),
            )
            if source != "yuzu":
                waifu_usage.mark_used(character.id)
            image_url = await _local_reply_image(local, record.get("image_url") or "")
        await matcher.finish(
            _waifu_reply(event, image_url, "")
        )
        return

    if command == "reroll":
        if not is_admin:
            await matcher.finish("只有管理员可以更换每日老婆")
        settings = waifu.load_settings()
        group_settings = _event_group_settings(event)
        exclude_ids = (
            waifu.taken_character_ids(group_id, user_id)
            if group_id is not None
            else set()
        )
        if not await asyncio.to_thread(library.ensure_index):
            character = await _draw_waifu_character(
                settings, group_settings, source, exclude_ids
            )
            if character is None:
                await matcher.finish("更换失败，请稍后再试")
            record = waifu.save_waifu(
                user_id, character, source=source, group_id=group_id
            )
            if source != "yuzu":
                waifu_usage.mark_used(character.id)
            image_url = record.get("image_url")
        else:
            local = await _draw_local_character(
                settings, group_settings, source, exclude_ids
            )
            if local is None:
                await matcher.finish("更换失败，请稍后再试")
            character = _to_vndb_character(local)
            record = waifu.save_waifu(
                user_id,
                character,
                source=source,
                library_path=_library_path(local),
                group_id=group_id,
                role=str(local.data.get("role") or ""),
            )
            if source != "yuzu":
                waifu_usage.mark_used(character.id)
            image_url = await _local_reply_image(local, record.get("image_url") or "")
        await matcher.finish(
            _waifu_reply(
                event,
                image_url,
                "",
            )
        )
    elif command == "set":
        if not is_admin:
            await matcher.finish("只有管理员可以指定每日老婆")
        keyword = arg.strip()
        if not keyword:
            await matcher.finish("用法：/waifu set [<QQ号>] <角色名或VNDB ID>")
        target_user_id = user_id
        first, _, rest = keyword.partition(" ")
        if first.isdigit() and rest:
            target_user_id = int(first)
            keyword = rest.strip()
        local: library.LibraryCharacter | None = None
        local_items = await asyncio.to_thread(
            library.search_characters, keyword, 1
        )
        local = local_items[0] if local_items else None
        if local is None:
            if re.match(r"^c\d+$", keyword, re.IGNORECASE):
                try:
                    character = await vndb.get_by_id(keyword.lower())
                except Exception:
                    character = None
            else:
                items = await vndb.search_character(keyword, 1)
                character = items[0] if items else None
        else:
            character = None
        if local is None and character is None:
            await matcher.finish(f"未找到角色：{keyword}")
        if local is not None:
            record = waifu.save_waifu(
                target_user_id,
                _to_vndb_character(local),
                source=source,
                library_path=_library_path(local),
                group_id=group_id,
                role=str(local.data.get("role") or ""),
            )
            image_url = await _local_reply_image(
                local, record.get("image_url") or ""
            )
        else:
            record = waifu.save_waifu(
                target_user_id,
                character,
                source=source,
                group_id=group_id,
            )
            image_url = record.get("image_url")
        note = (
            f"已为用户 {target_user_id} 设置老婆"
            if target_user_id != user_id
            else "已设置为你的老婆"
        )
        await matcher.finish(
            _waifu_reply(
                event,
                image_url,
                _waifu_text(record, note),
                at_user_id=target_user_id if target_user_id != user_id else None,
            )
        )
    elif command == "check":
        if not is_admin:
            await matcher.finish("只有管理员可以查看他人的每日老婆")
        target = arg.strip()
        if not target.isdigit():
            await matcher.finish("用法：/waifu check <QQ号>")
        target_user_id = int(target)
        existing = waifu.get_today_waifu(target_user_id)
        if existing is None:
            await matcher.finish(f"用户 {target_user_id} 今天还没有每日老婆")
        reply_image = await _record_reply_image(existing)
        if existing.get("source") == "yuzu":
            note = f"用户 {target_user_id} 今天抽的是 /yuzuwaifu（管理员查看）"
        else:
            note = f"用户 {target_user_id} 今天抽的是 /waifu（管理员查看）"
        await matcher.finish(
            _waifu_reply(
                event,
                reply_image,
                _waifu_text(existing, note),
                at_user_id=target_user_id if target_user_id != user_id else None,
            )
        )
    elif command == "reset":
        if not is_admin:
            await matcher.finish("只有管理员可以重置每日老婆")
        target = arg.strip()
        if not target or target.lower() == "all":
            count = waifu.reset_waifu(None)
            await matcher.finish(
                f"已重置全部用户的每日老婆（{count} 人），今天可以重新抽取"
            )
        if target.isdigit():
            count = waifu.reset_waifu(int(target))
            if count:
                await matcher.finish(f"已重置用户 {target} 的每日老婆")
            await matcher.finish(f"用户 {target} 今天还没有每日老婆")
        await matcher.finish("用法：/waifu reset [all|<QQ号>]")
    else:
        await matcher.finish(
            "用法：/waifu [reroll|set <角色名>|check <QQ号>|"
            "settings|reset [all|<QQ号>]]"
        )


def _event_group_settings(event: MessageEvent) -> dict:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return {
            "companies": [],
            "company_ids": [],
            "year_off": False,
            "popular_off": False,
        }
    return {
        **waifu.get_group_company(int(group_id)),
        "year_off": waifu.get_group_year_off(int(group_id)),
        "popular_off": waifu.get_group_popular_off(int(group_id)),
    }


_yuzusoft_ids_cache: list[str] | None = None


async def _yuzusoft_ids() -> list[str]:
    global _yuzusoft_ids_cache
    if _yuzusoft_ids_cache is None:
        try:
            ids = await vndb.resolve_company_ids(
                [str(name) for name in companies.COMPANIES["yuzusoft"]["search"]]
            )
        except Exception:
            ids = []
        _yuzusoft_ids_cache = ids or ["p98", "p12215"]
    return _yuzusoft_ids_cache


def _pick_pool_company(settings: dict) -> tuple[str | None, list[str]]:
    pool_companies = settings.get("pool_companies") or []
    groups = settings.get("pool_company_ids") or {}
    if isinstance(groups, dict) and pool_companies:
        key = random.choice(pool_companies)
        ids = groups.get(key) or []
        if ids:
            return key, [str(item) for item in ids]
        all_ids = [str(item) for value in groups.values() for item in value]
        return None, all_ids
    if isinstance(groups, list):
        return None, [str(item) for item in groups]
    return None, []


async def _draw_waifu_character(
    settings: dict,
    group_settings: dict,
    source: str,
    exclude_ids: set[str] | None = None,
) -> VNDBCharacter | None:
    """抽卡：新鲜缓存优先（普通 waifu 用 LRU），否则实时查询并回填缓存。
    抽中 exclude_ids（同群其他用户今天已抽）中的角色时最多重试 6 次。"""
    exclude_ids = exclude_ids or set()
    for _ in range(6):
        character = await _draw_waifu_character_once(settings, group_settings, source)
        if character is None:
            return None
        if character.id not in exclude_ids:
            return character
    return None


async def _draw_waifu_character_once(
    settings: dict,
    group_settings: dict,
    source: str,
) -> VNDBCharacter | None:
    """单次抽卡：新鲜缓存优先（普通 waifu 用 LRU），否则实时查询并回填缓存。"""
    popular = (
        0 if group_settings["popular_off"] else settings.get("popular_threshold", 0)
    )
    year_from = 0 if group_settings["year_off"] else settings.get("year_from", 0)
    year_to = 0 if group_settings["year_off"] else settings.get("year_to", 0)

    if source == "yuzu":
        cache_key: str | None = "yuzusoft"
        company_ids = await _yuzusoft_ids()
    elif group_settings["company_ids"]:
        cache_key = (
            group_settings["companies"][0]
            if group_settings["companies"]
            else None
        )
        company_ids = group_settings["company_ids"]
    else:
        cache_key, company_ids = _pick_pool_company(settings)

    character: VNDBCharacter | None = None
    if cache_key and waifu_cache.is_fresh(cache_key):
        character = waifu_cache.pick_character(
            cache_key, popular, year_from, year_to, lru=source != "yuzu"
        )
    if character is None:
        try:
            character = await vndb.random_female_character(
                popular_threshold=popular,
                year_from=year_from,
                year_to=year_to,
                company_ids=company_ids,
                cache_key=cache_key,
            )
        except (http.HttpError, RuntimeError):
            if cache_key:
                character = waifu_cache.pick_character(
                    cache_key, popular, year_from, year_to, lru=source != "yuzu"
                )
            if character is None:
                raise
    return character


async def _handle_waifu_settings(
    matcher: Matcher, event: MessageEvent, value: str
) -> None:
    user_id = int(getattr(event, "user_id", 0))
    parts = value.split() if value else []
    action = parts[0].lower() if parts else ""

    if not action:
        await matcher.finish(waifu.settings_text(waifu.load_settings()))
    if action == "company" and len(parts) == 1:
        lines = ["可选会社："]
        lines.extend(
            f"{key}（{companies.COMPANIES[key]['display']}）"
            for key in companies.COMPANIES
        )
        await matcher.finish("\n".join(lines))
    if action == "pool" and len(parts) == 1:
        settings = waifu.load_settings()
        pool_names = "、".join(
            str(companies.COMPANIES[key]["display"])
            for key in settings.get("pool_companies", [])
            if key in companies.COMPANIES
        )
        lines = [f"当前全局会社池：{pool_names or '不限'}"]
        lines.append("可设置的默认池（waifu 专用，yuzuwaifu 不受影响）：")
        lines.extend(
            f"{key}（{companies.COMPANIES[key]['display']}）"
            for key in companies.WAIFU_POOL_KEYS
        )
        await matcher.finish("\n".join(lines))
    if any(
        token.startswith(("group=", "kaisha=", "year=", "popular="))
        for token in parts
    ):
        await _handle_group_kaisha(matcher, event, value)
        return
    if not permissions.is_admin(user_id):
        await matcher.finish("只有管理员可以修改每日老婆设置")

    settings = waifu.load_settings()
    if action == "popular":
        if len(parts) != 2 or not parts[1].isdigit() or not (0 <= int(parts[1]) <= 100000):
            await matcher.finish(
                "用法：/waifu settings popular <N>（0=关闭，最大 100000）"
            )
        settings["popular_threshold"] = int(parts[1])
        waifu.save_settings(settings)
        await matcher.finish(
            f"已设置热度阈值：{settings['popular_threshold']}（0=关闭）"
        )
    if action == "year":
        if len(parts) not in (2, 3):
            await matcher.finish(
                "用法：/waifu settings year <起始年> [结束年]（0=不限）"
            )
        try:
            year_from = int(parts[1])
            year_to = int(parts[2]) if len(parts) == 3 else 0
        except ValueError:
            await matcher.finish("年份必须是数字")
        if not (
            0 <= year_from <= 2100
            and 0 <= year_to <= 2100
            and (year_from == 0 or year_to == 0 or year_from <= year_to)
        ):
            await matcher.finish("年份范围无效（0=不限，且起始年不能大于结束年）")
        settings["year_from"] = year_from
        settings["year_to"] = year_to
        waifu.save_settings(settings)
        await matcher.finish(
            f"已设置年代范围：{year_from or '不限'} - {year_to or '不限'}"
        )
    if action == "pool":
        if len(parts) < 2 or parts[1].lower() not in ("set", "off"):
            await matcher.finish("用法：/waifu settings pool set|off")
        if parts[1].lower() == "off":
            settings["pool_companies"] = []
            settings["pool_company_ids"] = {}
            waifu.save_settings(settings)
            await matcher.finish("已关闭全局会社池（waifu 不限会社）")
        groups: dict[str, list[str]] = {}
        for key in companies.WAIFU_POOL_KEYS:
            search_names = [
                str(name) for name in companies.COMPANIES[key]["search"]
            ]
            try:
                groups[key] = library.resolve_company_ids(search_names)
            except Exception:
                groups[key] = []
        settings["pool_companies"] = list(companies.WAIFU_POOL_KEYS)
        settings["pool_company_ids"] = groups
        waifu.save_settings(settings)
        total = sum(len(ids) for ids in groups.values())
        await matcher.finish(
            f"已设置全局会社池：{companies.display_names(list(companies.WAIFU_POOL_KEYS))}"
            f"（{len(groups)} 家会社，共 {total} 个本地厂商；抽卡时随机选一家）"
        )
    if action == "reset":
        waifu.save_settings(waifu.default_settings())
        await matcher.finish("每日老婆设置已重置（热度关闭、年代不限）")
    await matcher.finish(
        "用法：/waifu settings [popular <N>|year <起始年> [结束年]|"
        "group=<群号> kaisha=<会社key|off>|reset]"
    )


async def _handle_group_kaisha(
    matcher: Matcher, event: MessageEvent, value: str
) -> None:
    user_id = int(getattr(event, "user_id", 0))
    if not permissions.is_admin(user_id):
        await matcher.finish("只有管理员可以设置群级设置")
    group_id: int | None = None
    kaisha: str | None = None
    year_off: str | None = None
    popular_off: str | None = None
    for token in value.split():
        if token.startswith("group="):
            raw = token.partition("=")[2]
            if raw.isdigit():
                group_id = int(raw)
        elif token.startswith("kaisha="):
            kaisha = token.partition("=")[2].strip().lower()
        elif token.startswith("year="):
            year_off = token.partition("=")[2].strip().lower()
        elif token.startswith("popular="):
            popular_off = token.partition("=")[2].strip().lower()
    if group_id is None:
        await matcher.finish(
            "用法：/waifu settings group=<群号> "
            "kaisha=<会社key|off> | year=off|on | popular=off|on"
        )
    if year_off is not None:
        if year_off not in ("on", "off"):
            await matcher.finish("year 参数只能是 on（恢复）或 off（解除）")
        waifu.save_group_year_off(group_id, year_off == "off")
        state = "已解除" if year_off == "off" else "已恢复"
        await matcher.finish(f"群 {group_id} {state}年代限制")
    if popular_off is not None:
        if popular_off not in ("on", "off"):
            await matcher.finish("popular 参数只能是 on（恢复）或 off（解除）")
        waifu.save_group_popular_off(group_id, popular_off == "off")
        state = "已解除" if popular_off == "off" else "已恢复"
        await matcher.finish(f"群 {group_id} {state}热度限制")
    if kaisha is None:
        await matcher.finish(
            "用法：/waifu settings group=<群号> "
            "kaisha=<会社key|off> | year=off|on | popular=off|on"
        )
    if kaisha == "off":
        waifu.save_group_company(group_id, [], [])
        await matcher.finish(f"已清除群 {group_id} 的会社后门")
    if kaisha not in companies.COMPANIES:
        await matcher.finish(
            f"未知会社：{kaisha}；可用 /waifu settings company 查看列表"
        )
    search_names = [str(name) for name in companies.COMPANIES[kaisha]["search"]]
    company_ids = library.resolve_company_ids(search_names)
    waifu.save_group_company(group_id, [kaisha], company_ids)
    await matcher.finish(
        f"群 {group_id} 已设置会社后门：{companies.display_names([kaisha])}"
        f"（本地库解析到 {len(company_ids)} 个厂商）"
    )


def _at_user_ids(event: MessageEvent) -> list[int]:
    """提取消息中的 @ 目标 QQ 号。"""
    result: list[int] = []
    message = getattr(event, "message", None)
    if message is None:
        return result
    for segment in message:
        data = getattr(segment, "data", None) or {}
        if getattr(segment, "type", None) == "at" and str(data.get("qq") or "").isdigit():
            result.append(int(data["qq"]))
    return result


def _trade_pick_hint(user_id: int, target_user_id: int) -> str:
    """交易前提示：列出双方今天的每日老婆（每人只有一张，无需卡号）。"""
    lines: list[str] = []
    my_record = waifu.get_today_waifu(user_id)
    their_record = waifu.get_today_waifu(target_user_id)
    if my_record is not None:
        lines.append("【你今天的每日老婆】")
        lines.append(collection.waifu_display(my_record))
        if str(my_record.get("source") or "") != "yuzu":
            lines.append("（/waifu 抽的其他会社，暂时不能交易）")
    else:
        lines.append("你还没抽今天的每日老婆（/yuzuwaifu）")
    if their_record is not None:
        lines.append(f"【用户 {target_user_id} 今天的每日老婆】")
        lines.append(collection.waifu_display(their_record))
        if str(their_record.get("source") or "") != "yuzu":
            lines.append("（/waifu 抽的其他会社，暂时不能交易）")
    else:
        lines.append(f"用户 {target_user_id} 今天还没抽每日老婆")
    lines.append("互换请发：/yuzuwaifu trade @对方")
    return "\n".join(lines)


def _resolve_trade_id(value: str, user_id: int, direction: str) -> str:
    """解析 accept/reject/cancel 的交易号；不传交易号时自动选唯一的待处理交易。"""
    trade_id = value.strip().upper()
    if trade_id:
        return trade_id
    pending = (
        collection.pending_incoming(user_id)
        if direction == "incoming"
        else collection.pending_outgoing(user_id)
    )
    if not pending:
        raise ValueError("你当前没有待处理的交易")
    if len(pending) > 1:
        lines = ["你有多笔待处理交易，请附交易号："]
        for trade in pending:
            peer = (
                int(trade.get("proposer") or 0)
                if direction == "incoming"
                else int(trade.get("target") or 0)
            )
            lines.append(f"{trade['id']}（与 {peer}）")
        raise ValueError("\n".join(lines))
    return str(pending[0].get("id") or "")


async def _handle_yuzu_trade(
    matcher: Matcher,
    event: MessageEvent,
    action: str,
    value: str,
) -> None:
    user_id = int(getattr(event, "user_id", 0))
    at_ids = _at_user_ids(event)

    if action == "list":
        target = value.strip()
        target_user_id = user_id
        if target.isdigit():
            target_user_id = int(target)
        elif at_ids:
            target_user_id = at_ids[0]
        if target_user_id == user_id:
            my_record = waifu.get_today_waifu(user_id)
            if my_record is None:
                await matcher.finish(
                    "你还没抽今天的每日老婆，发 /yuzuwaifu 抽一张吧"
                )
            lines = [
                "【你今天的每日老婆】",
                collection.waifu_display(my_record),
                "互换请发：/yuzuwaifu trade @对方",
            ]
            await matcher.finish("\n".join(lines))
        await matcher.finish(_trade_pick_hint(user_id, target_user_id))

    if action == "rank":
        group_id = getattr(event, "group_id", None)
        records = waifu.all_today_waifu(group_id=group_id)
        if not records:
            await matcher.finish("今天还没有人抽到每日老婆")
        entries = collection.ranking(records)
        lines = ["【今日每日老婆稀有度排行】"]
        my_rank = "未上榜"
        for index, (uid, stars, rarity) in enumerate(entries, start=1):
            line = f"{index}. 用户 {uid}：{stars}★{rarity}"
            lines.append(line)
            if uid == user_id:
                my_rank = str(index)
        lines.append(f"你的排名：第 {my_rank} 名")
        await matcher.finish("\n".join(lines))

    if action == "trade":
        if not at_ids:
            await matcher.finish(
                "用法：/yuzuwaifu trade @对方（交换双方今天的每日老婆）"
            )
        target_user_id = at_ids[0]
        try:
            trade = collection.propose_trade(user_id, target_user_id)
        except ValueError as exc:
            await matcher.finish(str(exc))
        my_record = waifu.get_today_waifu(user_id)
        their_record = waifu.get_today_waifu(target_user_id)
        lines = [
            f"交易提议 #{trade['id']}",
            "你给出：",
            collection.waifu_display(my_record),
            "你想换取：",
            collection.waifu_display(their_record),
            f"请在 10 分钟内让 @{target_user_id} 确认：",
            "/yuzuwaifu accept",
            "拒绝：/yuzuwaifu reject（不用交易号）",
        ]
        await matcher.finish("\n".join(lines))

    if action == "accept":
        try:
            trade_id = _resolve_trade_id(value, user_id, "incoming")
        except ValueError as exc:
            await matcher.finish(str(exc))
        try:
            give_record, take_record, trade = collection.accept_trade(
                trade_id, user_id
            )
        except ValueError as exc:
            await matcher.finish(str(exc))
        await matcher.finish(
            f"交易 #{trade_id} 完成！\n"
            f"你获得了：{collection.waifu_display(give_record)}\n"
            f"你给出的：{collection.waifu_display(take_record)}\n"
            "发 /yuzuwaifu 或 /yuzuwaifu list 查看你现在的每日老婆"
        )

    if action == "reject":
        try:
            trade_id = _resolve_trade_id(value, user_id, "incoming")
        except ValueError as exc:
            await matcher.finish(str(exc))
        try:
            collection.reject_trade(trade_id, user_id)
        except ValueError as exc:
            await matcher.finish(str(exc))
        await matcher.finish(f"已拒绝交易 #{trade_id}")

    if action == "cancel":
        try:
            trade_id = _resolve_trade_id(value, user_id, "outgoing")
        except ValueError as exc:
            await matcher.finish(str(exc))
        try:
            collection.cancel_trade(trade_id, user_id)
        except ValueError as exc:
            await matcher.finish(str(exc))
        await matcher.finish(f"已撤销交易 #{trade_id}")
