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
- /yuzuwaifu —— 柚子社专属老婆（固定柚子社，行为保持不变；与 /waifu 每天二选一）"""


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


def _library_path(character: library.LibraryCharacter) -> str:
    root = Path(config.library_dir)
    try:
        return character.path.relative_to(root).as_posix()
    except ValueError:
        return character.path.name


async def _draw_local_character(
    settings: dict,
    group_settings: dict,
) -> library.LibraryCharacter | None:
    """从 final_company_library 抽卡：优先群会社后门，其次全局会社池。"""
    year_from = 0 if group_settings["year_off"] else settings.get("year_from", 0)
    year_to = 0 if group_settings["year_off"] else settings.get("year_to", 0)
    if group_settings["company_ids"]:
        company_ids = [str(item) for item in group_settings["company_ids"]]
    else:
        _, company_ids = _pick_pool_company(settings)
    return await asyncio.to_thread(
        library.random_character,
        company_ids=company_ids or None,
        year_from=year_from,
        year_to=year_to,
        lru=True,
    )


async def _cmd_waifu(
    matcher: Matcher,
    event: MessageEvent,
    value: str,
    source: str = "waifu",
) -> None:
    user_id = int(getattr(event, "user_id", 0))
    value = (value or "").strip()
    command, _, arg = value.partition(" ")
    command = command.lower()

    if command == "settings":
        await _handle_waifu_settings(matcher, event, arg.strip())
        return

    is_admin = permissions.is_admin(user_id)

    if not value:
        existing = waifu.get_today_waifu(user_id)
        if existing:
            reply_image = existing.get("image_url")
            if existing.get("source") != "yuzu":
                if existing.get("library_path"):
                    local = await asyncio.to_thread(
                        library.get_character_by_path,
                        str(existing["library_path"]),
                    )
                else:
                    # 兼容更新前保存的旧记录：按 VNDB ID 回查本地资料库
                    local = await asyncio.to_thread(
                        library.get_character_by_id,
                        str(existing.get("character_id") or ""),
                    )
                if local is not None:
                    reply_image = await _local_reply_image(
                        local, reply_image or ""
                    )
            text = (
                _waifu_text(
                    existing,
                    "你今天已经抽过了，明天再来（重复展示今日老婆）",
                )
                if source == "yuzu"
                else ""
            )
            await matcher.finish(
                _waifu_reply(
                    event,
                    reply_image,
                    text,
                )
            )
        settings = waifu.load_settings()
        group_settings = _event_group_settings(event)
        if source == "yuzu" or not await asyncio.to_thread(library.ensure_index):
            character = await _draw_waifu_character(
                settings, group_settings, source
            )
            if character is None:
                await matcher.finish("今天暂时抽不到老婆，请稍后再试")
            record = waifu.save_waifu(user_id, character, source=source)
            if source != "yuzu":
                waifu_usage.mark_used(character.id)
            image_url = record.get("image_url")
        else:
            local = await _draw_local_character(settings, group_settings)
            if local is None:
                await matcher.finish("今天暂时抽不到老婆，请稍后再试")
            character = _to_vndb_character(local)
            record = waifu.save_waifu(
                user_id,
                character,
                source=source,
                library_path=_library_path(local),
            )
            waifu_usage.mark_used(character.id)
            image_url = await _local_reply_image(local, record.get("image_url") or "")
        await matcher.finish(
            _waifu_reply(
                event,
                image_url,
                _waifu_text(record) if source == "yuzu" else "",
            )
        )
        return

    if command == "reroll":
        if not is_admin:
            await matcher.finish("只有管理员可以更换每日老婆")
        settings = waifu.load_settings()
        group_settings = _event_group_settings(event)
        if source == "yuzu" or not await asyncio.to_thread(library.ensure_index):
            character = await _draw_waifu_character(
                settings, group_settings, source
            )
            if character is None:
                await matcher.finish("更换失败，请稍后再试")
            record = waifu.save_waifu(user_id, character, source=source)
            if source != "yuzu":
                waifu_usage.mark_used(character.id)
            image_url = record.get("image_url")
        else:
            local = await _draw_local_character(settings, group_settings)
            if local is None:
                await matcher.finish("更换失败，请稍后再试")
            character = _to_vndb_character(local)
            record = waifu.save_waifu(
                user_id,
                character,
                source=source,
                library_path=_library_path(local),
            )
            waifu_usage.mark_used(character.id)
            image_url = await _local_reply_image(local, record.get("image_url") or "")
        await matcher.finish(
            _waifu_reply(
                event,
                image_url,
                (
                    _waifu_text(record, "管理员已更换，这是你的新老婆")
                    if source == "yuzu"
                    else ""
                ),
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
        if source != "yuzu":
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
            )
            image_url = await _local_reply_image(
                local, record.get("image_url") or ""
            )
        else:
            record = waifu.save_waifu(target_user_id, character)
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
            "用法：/waifu [reroll|set <角色名>|settings|reset [all|<QQ号>]]"
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
) -> VNDBCharacter:
    """抽卡：新鲜缓存优先（普通 waifu 用 LRU），否则实时查询并回填缓存。"""
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
