"""/waifu 与会社专属入口（/yuzuwaifu、/keywaifu、/sagawaifu、/purplewaifu）。"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
from pathlib import Path

from nonebot import on_command
import nonebot
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from . import (
    card,
    collection,
    collection_book,
    companies,
    http,
    library,
    natsume_state,
    permissions,
    shoukeni_state,
    vndb,
    waifu,
    waifu_cache,
    waifu_usage,
)
from .config import config
from .models import Image, VNDBCharacter, VnRef

# /waifu 2025 限定作品（新收录作品的 VNDB ID；已下放普通池，这里仅作限定抽取入口）
NEW_GAME_IDS = [
    "v62721", "v50215",
    "v63385", "v57252", "v57740", "v58009", "v56400", "v60562",
    "v56862", "v60096", "v60213", "v62700", "v63472", "v59534",
    "v59419", "v60196", "v60395", "v60646", "v59520", "v56147",
    "v60663", "v62286", "v56343", "v61834", "v57718", "v52407",
    "v61216", "v61093", "v63384", "v52780", "v59519", "v61200",
    "v66374", "v58614", "v63082",
]


def _is_slash_waifu(event: MessageEvent) -> bool:
    """/waifu 入口只认带斜杠的命令。"""
    text = (event.get_plaintext() or "").lstrip()
    return re.match(r"^/waifu(?:\s|$)", text, re.IGNORECASE) is not None


def _is_slash_fixed_waifu(command_name: str):
    """会社专属入口只认带斜杠的对应命令。"""

    def _rule(event: MessageEvent) -> bool:
        text = (event.get_plaintext() or "").lstrip()
        return (
            re.match(
                rf"^/{re.escape(command_name)}(?:\s|$)",
                text,
                re.IGNORECASE,
            )
            is not None
        )

    return _rule


_is_slash_yuzuwaifu = _is_slash_fixed_waifu("yuzuwaifu")
_is_slash_keywaifu = _is_slash_fixed_waifu("keywaifu")
_is_slash_sagawaifu = _is_slash_fixed_waifu("sagawaifu")
_is_slash_purplewaifu = _is_slash_fixed_waifu("purplewaifu")
_is_slash_frontwaifu = _is_slash_fixed_waifu("frontwaifu")
_is_slash_crystalwaifu = _is_slash_fixed_waifu("crystalwaifu")
_is_slash_hookwaifu = _is_slash_fixed_waifu("hookwaifu")
_is_slash_madowaifu = _is_slash_fixed_waifu("madowaifu")
_is_slash_palwaifu = _is_slash_fixed_waifu("palwaifu")
_is_slash_favowaifu = _is_slash_fixed_waifu("favowaifu")
_is_slash_smeewaifu = _is_slash_fixed_waifu("smeewaifu")
_is_slash_asawaifu = _is_slash_fixed_waifu("asawaifu")
_is_slash_makurawaifu = _is_slash_fixed_waifu("makurawaifu")
_is_slash_augustwaifu = _is_slash_fixed_waifu("augustwaifu")
_is_slash_nitroplus = _is_slash_fixed_waifu("nitroplus")
_is_slash_qruppowaifu = _is_slash_fixed_waifu("qruppowaifu")
_is_slash_nagato = _is_slash_fixed_waifu("nagato")


# 长門的枣子姐圣经（/nagato 彩蛋，无 emoji，带标点）
_NATSUME_HOLY_TEXTS = (
    "本人真的想棗子姐想得要發瘋了。本人躺在床上会想棗子姐，本人洗澡会想棗子姐，"
    "本人出門会想棗子姐，本人走路会想棗子姐，本人坐車会想棗子姐，本人上班会想棗子姐，"
    "本人開会会想棗子姐，本人摸魚会想棗子姐，本人放工会想棗子姐，本人喝酒会想棗子姐，"
    "本人喝醉了会想棗子姐，本人盯着切片裏的棗子姐看，本人盯着谷子裏的棗子姐看，"
    "本人盯着本子裏的棗子姐看，本人盯着插畫裏的棗子姐看，本人盯着手辦裏的棗子姐看，"
    "本人盯着星光咖啡館与死神之蝶裏的四季夏目看，看的本人真的覚得自己像中邪了一樣。"
    "本人好孤獨啊！真的好孤獨啊！你知道嗎？每到深夜，本人渾身滾燙滾燙，"
    "本人發病了！本人要瘋狂！棗子姐……嘿嘿嘿……棗子姐……棗子姐……嘿嘿嘿……"
    "棗子姐……棗子姐……嘿嘿嘿……棗子姐……棗子姐……嘿嘿嘿……棗子姐……"
    "棗子姐……嘿嘿嘿……棗子姐……",
    "自分は本当にナツメのことが恋しくて気が狂っちゃいそう。"
    "ベッドに寝転んでる時もナツメのことを思ってて、シャワー浴びる時もナツメのことを思ってて、"
    "出かける時もナツメのことを思ってて、歩いてる時もナツメのことを思ってて、"
    "車に乗ってる時もナツメのことを思ってて、働いてる時もナツメのことを思ってて、"
    "会議の時もナツメのことを思ってて、サボってる時もナツメのことを思ってて、"
    "退勤の時もナツメのことを思ってて、飲んでる時もナツメのことを思ってて、"
    "酔った時もナツメのことを思ってて、切り抜きのナツメをガン見してて、"
    "グッズのナツメをガン見してて、薄い本のナツメをガン見してて、"
    "イラストのナツメをガン見してて、フィギュアのナツメをガン見してて、"
    "『喫茶ステラと死神の蝶』の四季ナツメをガン見してて、"
    "本当に病みつきになりそうだと自分でも思ってる。"
    "ナツメへの思いはもはや病的になりそう。孤独だ！自分はなんとも孤独だ！"
    "真夜中になると、全身熱くて苦しくて……もうダメだ！狂っちゃう！！"
    "ナツメ……ヘヘヘ……ナツメさん……ナツメ……ヘヘヘ……ナツメさん……"
    "ナツメ……ヘヘヘ……ナツメさん……ナツメ……ヘヘヘ……ナツメさん……"
    "ナツメ……ヘヘヘ……ナツメさん……ナツメ……ヘヘヘ……ナツメさん……"
    "ナツメ……ヘヘヘ……ナツメさん……ナツメ……ヘヘヘ……ナツメさん…",
    """ナツメ！ナツメ！ナツメ！ナツメぅぅうううわぁああああああああああああああああああああああん！！！
あぁああああ…ああ…あっあっー！あぁああああああ！！！ナツメナツメナツメぅううぁわぁああああ！！！
あぁクンカクンカ！クンカクンカ！スーハースーハー！スーハースーハー！いい匂いだなぁ…くんくん
んはぁっ！四季ナツメたんの黒髪ロングをクンカクンカしたいお！クンカクンカ！あぁあ！！
間違えた！モフモフしたいお！モフモフ！モフモフ！髪髪モフモフ！カリカリモフモフ…きゅんきゅんきゅい！！
Hシーンのナツメたんかわいかったよぅ！！あぁぁああ…あああ…あっあぁああああ！！ふぁぁあああんんっ！！
Getchuキャラ部門大賞取れて良かったねナツメたん！あぁあああああ！かわいい！ナツメたん！かわいい！あっああぁああ！
音声も発売されて嬉し…いやぁああああああ！！！にゃああああああああん！！ぎゃああああああああ！！
ぐあああああああああああ！！！エロゲなんて現実じゃない！！！！あ…同人誌も音声もよく考えたら…
ナ ツ メ ち ゃ ん は 現実 じ ゃ な い？にゃあああああああああああああん！！うぁああああああああああ！！
そんなぁああああああ！！いやぁぁぁあああああああああ！！はぁああああああん！！キャフェステリャぁああああ！！
この！ちきしょー！やめてやる！！現実なんかやめ…て…え！？見…てる？イベントCGのナツメちゃんが僕を見てる？
イベントCGのナツメちゃんが僕を見てるぞ！ナツメちゃんが僕を見てるぞ！立ち絵のナツメちゃんが僕を見てるぞ！！
音声のナツメちゃんが僕に話しかけてるぞ！！！よかった…世の中まだまだ捨てたモンじゃないんだねっ！
いやっほぉおおおおおおお！！！僕にはナツメちゃんがいる！！やったよ希！！ひとりでできるもん！！！
あ、同人誌のナツメちゃあああああああああああああああん！！いやぁあああああああああああああああ！！！！
あっあんああっああんあスズネ様ぁあ！！カ、カンナー！！ノゾミちゃぁああああああン！！！メイちゃぁあああん！！
ううっうぅうう！！俺の想いよナツメへ届け！！カフェステラのナツメへ届け！""",
)

_NATSUME_NEW_TEXTS = (
    "棗子的舔嘴……嘿嘿嘿……棗子的舔嘴……棗子的黑臉……嘿嘿嘿……棗子的黑臉……棗子的脚……嘿嘿嘿……棗子的脚……棗子的腿子……嘿嘿嘿……棗子的腿子……棗子的舔嘴……嘿嘿嘿……棗子的舔嘴……棗子的黑臉……嘿嘿嘿……棗子的黑臉……棗子的脚……嘿嘿嘿……棗子的脚……棗子的腿子……嘿嘿嘿……棗子的腿子……",
    "棗子的舔嘴……嘿嘿嘿……棗子的舔嘴……棗子的腿子……嘿嘿嘿……棗子的腿子……棗子的脚……嘿嘿嘿……棗子的脚……棗子的舔嘴……嘿嘿嘿……棗子的舔嘴……棗子的腿子……嘿嘿嘿……棗子的腿子……棗子的脚……嘿嘿嘿……棗子的脚……",
    "棗子的黑臉……嘿嘿嘿……棗子的脚……棗子的黑臉……嘿嘿嘿……棗子的脚……棗子的黑臉……嘿嘿嘿……棗子的脚……棗子的黑臉……嘿嘿嘿……棗子的脚……棗子的黑臉……嘿嘿嘿……棗子的脚……棗子的黑臉……嘿嘿嘿……棗子的脚……",
    "棗子的黑臉……嘿嘿嘿……棗子的黑臉……棗子的黑臉……嘿嘿嘿……棗子的黑臉……棗子的黑臉……嘿嘿嘿……棗子的黑臉……棗子的黑臉……嘿嘿嘿……棗子的黑臉……棗子的黑臉……嘿嘿嘿……棗子的黑臉……棗子的黑臉……嘿嘿嘿……棗子的黑臉……",
)
_NATSUME_XIAHEXIAO_TEXTS = (
    "怎麼会有人不喜歡夏和小呢今天也是想夏和小的一天夏和小嘿嘿嘿本人真的想夏和小想的要發瘋了"
    "本人躺在床上会想夏和小本人洗澡会想夏和小本人出門会想夏和小本人走路会想夏和小"
    "本人坐車会想夏和小本人上班会想夏和小本人開会会想夏和小本人摸魚会想夏和小"
    "本人放工会想夏和小本人喝酒会想夏和小本人喝醉了会想夏和小"
    "本人盯着夏和小配的四季ナツメ看本人盯着夏和小配的壬生千咲看本人盯着夏和小配的結城希亜看"
    "本人盯着夏和小配的谷風天音看本人盯着夏和小配的茶園那優花看本人盯着夏和小配的本間心鈴看"
    "本人盯着夏和小配的椎名雪看本人盯着夏和小配的有瀬かぐや看本人盯着夏和小配的峠の霊看"
    "看的本人真的覚得自己像中邪了一樣，本人対夏和小的念想似乎都是病態的了"
    "本人好孤獨啊！真的好孤獨啊！你知道嗎？每到深夜本人渾身滾燙滾燙本人發病了本人要瘋狂"
    "夏和小……嘿嘿嘿……夏和小……夏和小……嘿嘿嘿……夏和小……夏和小……嘿嘿嘿……夏和小……"
    "夏和小……嘿嘿嘿……夏和小……夏和小……嘿嘿嘿……夏和小……夏和小……嘿嘿嘿……夏和小……"
    "夏和小……嘿嘿嘿……夏和小……夏和小……嘿嘿嘿……夏和小……夏和小……",
)
_NATSUME_ZAOZI_TEXTS = (
    "怎麼会有人不喜歡棗子姐呢 今天也是想棗子姐的一天 棗子姐 嘿嘿嘿 本人真的想棗子姐想的要發瘋了 "
    "本人躺在床上会想棗子姐 本人洗澡会想棗子姐 本人出門会想棗子姐 本人走路会想棗子姐 "
    "本人坐車会想棗子姐 本人上班会想棗子姐 本人開会会想棗子姐 本人摸魚会想棗子姐 "
    "本人放工会想棗子姐 本人喝酒会想棗子姐 本人喝醉了会想棗子姐 "
    "本人盯着切片裏的棗子姐看 本人盯着谷子裏的棗子姐看 本人盯着本子裏的棗子姐看 "
    "本人盯着插畫裏的棗子姐看 本人盯着手辦裏的棗子姐看 本人盯着星光咖啡館与死神之蝶裏的四季夏目看 "
    "看的本人真的覚得自己像中邪了一樣，本人対棗子姐的念想似乎都是病態的了 "
    "本人好孤獨啊！真的好孤獨啊！ 你知道嗎？ 每到深夜 本人渾身滾燙滾燙 本人發病了 本人要瘋狂 "
    "棗子姐…… 嘿嘿嘿……棗子姐…… 棗子姐…… 嘿嘿嘿……棗子姐…… 棗子姐…… 嘿嘿嘿……棗子姐…… "
    "棗子姐…… 嘿嘿嘿……棗子姐……棗子姐……嘿嘿嘿……棗子姐……棗子姐…… 嘿嘿嘿……棗子姐……",
)
_NATSUME_ALL_TEXTS = (
    _NATSUME_HOLY_TEXTS
    + _NATSUME_NEW_TEXTS
    + _NATSUME_XIAHEXIAO_TEXTS
    + _NATSUME_ZAOZI_TEXTS
)


def _natsume_response(pool: tuple[str, ...] | None = None) -> str:
    return (
        random.choice(pool or _NATSUME_HOLY_TEXTS)
        + "\n\n—— ネタ来源：＠中江学会長門(@Nagato_KKO)"
    )


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


def _collection_alias_source(keyword: str) -> str | None:
    """图鉴关键词映射到固定会社入口（yuzu/key/saga/purple）。"""
    aliases = {
        "yuzu": "yuzu",
        "柚子": "yuzu",
        "柚子社": "yuzu",
        "key": "key",
        "键": "key",
        "键社": "key",
        "saga": "saga",
        "sagaplanets": "saga",
        "saga planets": "saga",
        "行星社": "saga",
        "purple": "purple",
        "purplesoftware": "purple",
        "purple software": "purple",
        "紫": "purple",
        "紫社": "purple",
        "front": "front",
        "frontwing": "front",
        "前翼": "front",
        "前翼社": "front",
        "crystal": "crystal",
        "crystalia": "crystal",
        "晶": "crystal",
        "hook": "hook",
        "hooksoft": "hook",
        "钩": "hook",
        "smee": "smee",
        "asa": "asa",
        "asaproject": "asa",
        "asa project": "asa",
        "mado": "mado",
        "madosoft": "mado",
        "窗": "mado",
        "窗社": "mado",
        "pal": "pal",
        "palette": "pal",
        "调色板": "pal",
        "调色板社": "pal",
        "favo": "favo",
        "favorite": "favo",
        "f社": "favo",
        "makura": "makura",
        "maku": "makura",
        "枕": "makura",
        "august": "august",
        "aug": "august",
        "八月": "august",
        "八月社": "august",
        "nitro": "nitro",
        "nitroplus": "nitro",
        "nitro plus": "nitro",
        "n+": "nitro",
        "n+社": "nitro",
        "qruppo": "qruppo",
        "qroppo": "qruppo",
        "qr": "qruppo",
    }
    return aliases.get((keyword or "").strip().lower())


_PAGE_RE = re.compile(r"(?:^|\s)page\s+(\d+)\s*$", re.IGNORECASE)
_SEARCH_PREFIX_RE = re.compile(r"^(?:search|搜索|查找)\s+(.+)$", re.IGNORECASE)
_SEARCH_ONLY_WORDS = {"search", "搜索", "查找"}


def _extract_page(value: str) -> tuple[str, int]:
    """从图鉴参数末尾解析「page N」，返回（去掉页码的参数, 页码）。"""
    text = (value or "").strip()
    match = _PAGE_RE.search(text)
    if match is None:
        return text, 1
    page = max(1, int(match.group(1)))
    return text[: match.start()].strip(), page


def _parse_collection_keyword(
    text: str,
) -> tuple[str, str | None, bool]:
    """解析图鉴参数：会社前缀、search 前缀与搜索词。"""
    keyword = (text or "").strip()
    alias_source: str | None = None
    if keyword:
        first, _, rest = keyword.partition(" ")
        alias = _collection_alias_source(first)
        if alias:
            alias_source = alias
            keyword = rest.strip()
    search_mode = False
    if keyword:
        if keyword.lower() in _SEARCH_ONLY_WORDS:
            return "", alias_source, True
        match = _SEARCH_PREFIX_RE.match(keyword)
        if match:
            search_mode = True
            keyword = match.group(1).strip()
    return keyword, alias_source, search_mode


def _company_pool_hint() -> str:
    return (
        "【卡池提示】下次想指定会社吗？例如 /waifu yuzu、/waifu hook；"
        "原有 /yuzuwaifu 等指令也保留。"
    )


def _repeat_note(existing: dict) -> str:
    """每日额度已被占用时的重复展示提示（按来源区分入口）。"""
    source = str(existing.get("source") or "waifu")
    if source in companies.FIXED_WAIFU_COMPANIES:
        command = companies.FIXED_WAIFU_COMMANDS[source]
        label = companies.FIXED_WAIFU_LABELS[source]
        return (
            f"你今天已经抽过 {command} 了，"
            f"这是你今天的{label}老婆（重复展示）"
        )
    return "你今天已经抽过 /waifu 了，这是你今天的每日老婆（重复展示）"


waifu_short = on_command("waifu", rule=_is_slash_waifu, priority=1, block=True)
yuzuwaifu_short = on_command(
    "yuzuwaifu", rule=_is_slash_yuzuwaifu, priority=1, block=True
)
nagato_short = on_command(
    "nagato", rule=_is_slash_nagato, priority=1, block=True
)
keywaifu_short = on_command(
    "keywaifu", rule=_is_slash_keywaifu, priority=1, block=True
)
sagawaifu_short = on_command(
    "sagawaifu", rule=_is_slash_sagawaifu, priority=1, block=True
)
purplewaifu_short = on_command(
    "purplewaifu", rule=_is_slash_purplewaifu, priority=1, block=True
)
frontwaifu_short = on_command(
    "frontwaifu", rule=_is_slash_frontwaifu, priority=1, block=True
)
crystalwaifu_short = on_command(
    "crystalwaifu", rule=_is_slash_crystalwaifu, priority=1, block=True
)
hookwaifu_short = on_command(
    "hookwaifu", rule=_is_slash_hookwaifu, priority=1, block=True
)
madowaifu_short = on_command(
    "madowaifu", rule=_is_slash_madowaifu, priority=1, block=True
)
palwaifu_short = on_command(
    "palwaifu", rule=_is_slash_palwaifu, priority=1, block=True
)
favowaifu_short = on_command(
    "favowaifu", rule=_is_slash_favowaifu, priority=1, block=True
)
smeewaifu_short = on_command(
    "smeewaifu", rule=_is_slash_smeewaifu, priority=1, block=True
)
asawaifu_short = on_command(
    "asawaifu", rule=_is_slash_asawaifu, priority=1, block=True
)
makurawaifu_short = on_command(
    "makurawaifu", rule=_is_slash_makurawaifu, priority=1, block=True
)
augustwaifu_short = on_command(
    "augustwaifu", rule=_is_slash_augustwaifu, priority=1, block=True
)
nitroplus_short = on_command(
    "nitroplus", rule=_is_slash_nitroplus, priority=1, block=True
)
qruppowaifu_short = on_command(
    "qruppowaifu", rule=_is_slash_qruppowaifu, priority=1, block=True
)


def _help_text() -> str:
    return """【每日老婆】
- /waifu —— 抽今日老婆；/waifu <会社> 指定会社（如 yuzu、hook、makura、august、nitro）
- /waifu 2025 —— 2025 新收录作品池
- /waifu collection [page N|search <关键词>] —— 查看/搜索图鉴
- /waifu collection @某人 [page N] —— 查看他人图鉴（仅管理员）
- /waifu list [@某人|<QQ号>] —— 查看今天抽到的老婆
- /waifu trade @对方 / accept / reject / cancel —— 今日老婆交易
- 管理员：/waifu settings（含群会社/年代后门）、reset、undo、check、set
- 会社专属入口：/yuzuwaifu、/keywaifu、/makurawaifu、/augustwaifu、/nitroplus、/qruppowaifu 等（共享每日额度，支持 collection/trade）"""


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


_WAIFU_SUBCOMMANDS = (
    "list",
    "trade",
    "collection",
    "accept",
    "reject",
    "cancel",
)


async def _handle_fixed_waifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message,
    source: str,
    command_name: str,
) -> None:
    """会社专属入口的公共处理：子命令复用交易/图鉴/排行实现。"""
    if not _plugin_enabled_for_event(event):
        await matcher.finish("该群已禁用每日老婆功能")
    value = (arg.extract_plain_text() or "").strip()
    if value:
        first, _, rest = value.partition(" ")
        first = first.lower()
        if first in _WAIFU_SUBCOMMANDS:
            await _handle_yuzu_trade(
                matcher, event, first, rest.strip(), source=source
            )
            return
    try:
        await _cmd_waifu(matcher, event, value, source=source)
    except (http.HttpError, RuntimeError) as exc:
        await matcher.finish(f"{command_name} 抽卡失败，请稍后再试（{exc}）")


@yuzuwaifu_short.handle()
async def handle_yuzuwaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    value = (arg.extract_plain_text() or "").strip()
    await _handle_fixed_waifu_short(
        event, matcher, arg, "yuzu", "yuzuwaifu"
    )


@nagato_short.handle()
async def handle_nagato(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    if not _plugin_enabled_for_event(event):
        await matcher.finish("该群已禁用每日老婆功能")
    value = (arg.extract_plain_text() or "").strip()
    parts = value.split(maxsplit=1)
    if parts and parts[0].lower() == "limit":
        if not permissions.is_admin(event.user_id):
            await matcher.finish("仅管理员可设置长文触发上限")
        if len(parts) < 2 or not parts[1].strip():
            await matcher.finish(
                f"当前每人每天上限：{natsume_state.limit()} 次（0=不限）"
                "\n用法：/nagato limit <次数>"
            )
        raw = parts[1].strip()
        if not raw.isdigit():
            await matcher.finish("用法：/nagato limit <次数>（0=不限）")
        new_limit = natsume_state.set_limit(int(raw))
        await matcher.finish(
            "已将 /nagato 的每人每天上限"
            f"设为 {new_limit} 次（0=不限）"
        )
    allowed, used, limit = natsume_state.consume(event.user_id)
    if not allowed:
        await matcher.finish(
            f"今天的长文次数已用完（每人每天上限 {limit} 次），明天再来吧。"
        )
    await matcher.finish(_natsume_response(_NATSUME_ALL_TEXTS))


@keywaifu_short.handle()
async def handle_keywaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "key", "keywaifu"
    )


@sagawaifu_short.handle()
async def handle_sagawaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "saga", "sagawaifu"
    )


@purplewaifu_short.handle()
async def handle_purplewaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "purple", "purplewaifu"
    )


@frontwaifu_short.handle()
async def handle_frontwaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "front", "frontwaifu"
    )


@crystalwaifu_short.handle()
async def handle_crystalwaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "crystal", "crystalwaifu"
    )


@hookwaifu_short.handle()
async def handle_hookwaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "hook", "hookwaifu"
    )


@madowaifu_short.handle()
async def handle_madowaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "mado", "madowaifu"
    )


@palwaifu_short.handle()
async def handle_palwaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "pal", "palwaifu"
    )


@favowaifu_short.handle()
async def handle_favowaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "favo", "favowaifu"
    )


@smeewaifu_short.handle()
async def handle_smeewaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "smee", "smeewaifu"
    )


@asawaifu_short.handle()
async def handle_asawaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "asa", "asawaifu"
    )


@makurawaifu_short.handle()
async def handle_makurawaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "makura", "makurawaifu"
    )


@augustwaifu_short.handle()
async def handle_augustwaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "august", "augustwaifu"
    )


@nitroplus_short.handle()
async def handle_nitroplus_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "nitro", "nitroplus"
    )


@qruppowaifu_short.handle()
async def handle_qruppowaifu_short(
    event: MessageEvent,
    matcher: Matcher,
    arg: Message = CommandArg(),
) -> None:
    await _handle_fixed_waifu_short(
        event, matcher, arg, "qruppo", "qruppowaifu"
    )


def _image_segment(url_or_base64: str | None) -> MessageSegment | None:
    if not url_or_base64:
        return None
    if url_or_base64.startswith("http"):
        return MessageSegment.image(url_or_base64)
    if url_or_base64.startswith("base64://"):
        return MessageSegment.image(url_or_base64)
    return MessageSegment.image(f"base64://{url_or_base64}")


def _collection_note(user_id: int, record: dict) -> str:
    """抽卡后的图鉴提示：新收录显示进度；已有角色引导交易。"""
    try:
        is_new = collection_book.rec_collect(user_id, record)
    except Exception:
        return ""
    if not is_new:
        name = str(record.get("name") or record.get("original") or "")
        return (
            f"📖 「{name}」已在你的图鉴中（不重复收录）\n"
            f"查看：/waifu collection ｜ 可以送出：/waifu trade @对方"
        )
    size = collection_book.collection_size(user_id)
    return (
        f"📖 新角色已收录进你的图鉴！当前共 {size} 位\n"
        f"查看：/waifu collection ｜ 重复抽到可交易送出"
    )


def _display_name(entry: dict) -> str:
    """图鉴条目展示名：中文名优先，其次日文名，最后 ID。"""
    cn_name = str(entry.get("cn_name") or "").strip()
    name = str(entry.get("name") or entry.get("original") or "").strip()
    if cn_name:
        return cn_name
    return name or str(entry.get("character_id") or "")


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
    """老婆信息只在卡片图片中展示；文本仅附加说明（如重复展示/管理员操作）。"""
    return note


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
        source = str(record.get("source") or "")
        company_key = companies.FIXED_WAIFU_COMPANIES.get(source)
        company_ids = (
            await _company_ids(company_key) if company_key else []
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
    game_ids: list[str] | None = None,
) -> library.LibraryCharacter | None:
    """从 final_company_library 抽卡：优先群会社后门，其次全局会社池。

    全局会社池为随机单会社，可能随机到库内无可用角色的会社
    （如 2010+ 年代过滤后为空），此时重新随机会会社重试，最多 8 次。
    game_ids 非空时只在指定作品内抽取（如 /waifu 2025 限定新收录作品）。
    """
    year_from = 0 if group_settings["year_off"] else settings.get("year_from", 0)
    year_to = 0 if group_settings["year_off"] else settings.get("year_to", 0)
    company_key = companies.FIXED_WAIFU_COMPANIES.get(source)
    if company_key:
        company_ids = await _company_ids(company_key)
        if not company_ids:
            return None
        lru = False
    elif game_ids:
        company_ids = None
        lru = True
    elif group_settings["company_ids"]:
        company_ids = [str(item) for item in group_settings["company_ids"]]
        lru = True
    else:
        company_ids = None
        lru = True
    for _ in range(8 if company_ids is None else 1):
        if company_ids is None:
            _, company_ids = _pick_pool_company(settings)
        character = await asyncio.to_thread(
            library.random_character,
            company_ids=company_ids or None,
            year_from=year_from,
            year_to=year_to,
            lru=lru,
            exclude_ids=exclude_ids,
            game_ids=game_ids,
        )
        if character is not None:
            return character
        if company_ids is not None:
            company_ids = None
    return None


async def _draw_character_with_fallback(
    settings: dict,
    group_settings: dict,
    source: str,
    exclude_ids: set[str] | None = None,
):
    """本地库优先；本地无对应会社/角色时回退 VNDB。"""
    local = await _draw_local_character(
        settings, group_settings, source, exclude_ids
    )
    if local is not None:
        return "local", local
    character = await _draw_waifu_character(
        settings, group_settings, source, exclude_ids
    )
    if character is not None:
        return "vndb", character
    return None, None


async def _cmd_waifu(
    matcher: Matcher,
    event: MessageEvent,
    value: str,
    source: str = "waifu",
) -> None:
    user_id = int(getattr(event, "user_id", 0))
    group_id = getattr(event, "group_id", None)
    value = (value or "").strip()
    # /waifu <会社> 等价于对应会社入口，如 /waifu yuzu == /yuzuwaifu
    if source == "waifu":
        first, _, rest = value.partition(" ")
        company_source = _collection_alias_source(first)
        if company_source:
            source = company_source
            value = rest.strip()
    command, _, arg = value.partition(" ")
    command = command.lower()

    if command in ("help", "帮助"):
        await matcher.finish(_help_text())

    if command in (
        "list",
        "trade",
        "accept",
        "reject",
        "cancel",
    ):
        # 全角色交易：所有入口共用一套实现
        await _handle_yuzu_trade(
            matcher, event, command, arg.strip(), source=source
        )
        return

    if command in ("collection", "图鉴"):
        keyword, page = _extract_page(arg)
        keyword, alias_source, search_mode = _parse_collection_keyword(keyword)
        if alias_source is None and source in companies.FIXED_WAIFU_COMPANIES:
            alias_source = source
        target_user_id = user_id
        viewing_other = False
        # 管理员可查看他人图鉴：@某人 或直接发 QQ 号
        at_ids = _at_user_ids(event)
        if at_ids and not permissions.is_admin(user_id):
            await matcher.finish("只有管理员可以查看他人图鉴")
        if at_ids and permissions.is_admin(user_id):
            target_user_id = at_ids[0]
            viewing_other = True
        elif (
            not search_mode
            and keyword.isdigit()
            and permissions.is_admin(user_id)
            and collection_book.user_collection(int(keyword))
        ):
            target_user_id = int(keyword)
            viewing_other = True
        # 补全旧图鉴条目的中文名/罗马音（本地库读取较慢，后台线程执行）
        await asyncio.to_thread(
            collection_book.enrich_from_library, target_user_id
        )
        # 补录遗漏：交易获得的角色等（同步该用户当前 waifu_state 记录）
        collection_book.sync_from_state(target_user_id)
        if viewing_other:
            page_command = f"/waifu collection {target_user_id}"
        elif alias_source:
            page_command = (
                f"{companies.FIXED_WAIFU_COMMANDS[alias_source]} collection"
            )
        else:
            page_command = "/waifu collection"
        if search_mode and not keyword:
            if viewing_other:
                await matcher.finish(
                    "用法：/waifu collection @某人 search <关键词>"
                )
            await matcher.finish(
                f"用法：{page_command} search <关键词>"
            )
        if alias_source and not keyword:
            await matcher.finish(
                collection_book.collection_text(
                    target_user_id,
                    company_source=alias_source,
                    page=page,
                    command=page_command,
                )
            )
        if keyword in ("usage", "help", "用法", "帮助"):
            await matcher.finish(collection_book.usage_text())
        if keyword:
            # 纯 QQ 号且已切换目标：直接展示对方图鉴列表，避免把 QQ 号当检索词
            if viewing_other and keyword.isdigit() and not search_mode:
                await matcher.finish(
                    "【他人的图鉴】\n"
                    + collection_book.collection_text(
                        target_user_id,
                        page=page,
                        command=page_command,
                    )
                )
            matches = collection_book.search_collection(
                target_user_id, keyword, company_source=alias_source
            )
            if not matches:
                prefix = "他人图鉴" if viewing_other else "图鉴"
                await matcher.finish(
                    f"{prefix}里没有找到「{keyword}」相关的角色，"
                    "试试更短的名字或作品名"
                )
            if len(matches) > 1:
                lines = [f"找到 {len(matches)} 个匹配角色："]
                for match in matches[:8]:
                    index = collection_book.collection_index(
                        target_user_id,
                        str(match.get("character_id") or ""),
                        company_source=alias_source,
                    )
                    name_prefix = f"{index}. " if index else "- "
                    lines.append(name_prefix + _display_name(match))
                if len(matches) > 8:
                    lines.append(
                        f"……另有 {len(matches) - 8} 个匹配，请缩小关键词"
                    )
                if viewing_other:
                    lines.append("请输入更精确的名字继续搜索")
                else:
                    lines.append(
                        f"发序号或更精确的名字查看卡片："
                        f"{page_command} <序号|名字>"
                    )
                await matcher.finish("\n".join(lines))
            # 唯一匹配：渲染角色卡片
            record = matches[0]
            reply_image = await _record_reply_image(record)
            note = (
                f"{'【他人图鉴】' if target_user_id != user_id else ''}"
                f"图鉴角色：{_display_name(record)}"
                f"（收录于 {collection_book.user_collection(target_user_id).get(str(record.get('character_id')), {}).get('first_seen', '')[:10]}）"
            )
            await matcher.finish(_waifu_reply(event, reply_image, _waifu_text(record, note)))
        header_note = "【他人的图鉴】" if target_user_id != user_id else ""
        await matcher.finish(
            header_note
            + "\n"
            + collection_book.collection_text(
                target_user_id,
                page=page,
                command=page_command,
            )
        )

    if command == "virus":
        await matcher.finish(
            "Special Thanks to 病毒@kitsurato. "
            "病毒@kitsurato様のご協力誠にありがとうございます。"
        )

    if command == "2025":
        # 新收录作品池：与普通 /waifu 共享每日额度
        existing = waifu.get_today_waifu(user_id)
        if existing:
            reply_image = await _record_reply_image(existing)
            repeat_note = _repeat_note(existing)
            await matcher.finish(
                _waifu_reply(
                    event,
                    reply_image,
                    _waifu_text(existing, repeat_note),
                )
            )
        settings = waifu.load_settings()
        group_settings = _event_group_settings(event)
        exclude_ids = (
            waifu.taken_character_ids(group_id, user_id)
            if group_id is not None
            else set()
        )
        local = await _draw_local_character(
            settings,
            group_settings,
            "waifu",
            exclude_ids,
            game_ids=NEW_GAME_IDS,
        )
        if local is None:
            await matcher.finish("新收录作品池暂时抽不到老婆，请稍后再试")
        character = _to_vndb_character(local)
        record = waifu.save_waifu(
            user_id,
            character,
            source="waifu",
            library_path=_library_path(local),
            group_id=group_id,
            role=str(local.data.get("role") or ""),
        )
        waifu_usage.mark_used(character.id)
        image_url = await _local_reply_image(local, record.get("image_url") or "")
        note = "【2025 新收录作品池】" + _collection_note(user_id, record)
        await matcher.finish(
            _waifu_reply(
                event,
                image_url,
                _waifu_text(record, note),
            )
        )

    if command == "settings":
        await _handle_waifu_settings(matcher, event, arg.strip())
        return

    is_admin = permissions.is_admin(user_id)

    if command == "undo":
        if not is_admin:
            await matcher.finish("只有管理员可以撤销 reset")
        info = waifu.undo_last_reset()
        if info is None:
            await matcher.finish("没有可撤销的 reset 记录")
        if info.get("kind") == "all":
            label = "全部用户"
        else:
            label = f"用户 {info.get('target')}"
        text = (
            f"已撤销最近一次 reset（{label}）："
            f"恢复 {info.get('restored', 0)} 人"
        )
        skipped = int(info.get("skipped", 0))
        if skipped:
            text += f"，跳过 {skipped} 人（重置后已重新抽卡）"
        await matcher.finish(text)

    if not value:
        existing = waifu.get_today_waifu(user_id)
        if existing:
            reply_image = await _record_reply_image(existing)
            repeat_note = _repeat_note(existing)
            await matcher.finish(
                _waifu_reply(
                    event,
                    reply_image,
                    _waifu_text(existing, repeat_note),
                )
            )
        settings = waifu.load_settings()
        group_settings = _event_group_settings(event)
        exclude_ids = (
            waifu.taken_character_ids(group_id, user_id)
            if group_id is not None
            else set()
        )
        kind = None
        drawn = None
        if source == "yuzu":
            # omikuji 先抽时，yuzuwaifu 沿用其当天选中的角色
            local = await asyncio.to_thread(
                waifu.omikuji_yuzu_character, user_id
            )
            if local is not None:
                kind, drawn = "local", local
        if drawn is None:
            kind, drawn = await _draw_character_with_fallback(
                settings, group_settings, source, exclude_ids
            )
        if drawn is None:
            await matcher.finish("今天暂时抽不到老婆，请稍后再试")
        if kind == "local":
            local = drawn
            character = _to_vndb_character(local)
            record = waifu.save_waifu(
                user_id,
                character,
                source=source,
                library_path=_library_path(local),
                group_id=group_id,
                role=str(local.data.get("role") or ""),
            )
            image_url = await _local_reply_image(
                local, record.get("image_url") or ""
            )
        else:
            character = drawn
            record = waifu.save_waifu(
                user_id, character, source=source, group_id=group_id
            )
            image_url = await _record_reply_image(record)
        if source not in companies.FIXED_WAIFU_COMPANIES:
            waifu_usage.mark_used(character.id)
        note = _collection_note(user_id, record)
        if source == "waifu":
            hint = _company_pool_hint()
            note = f"{note}\n{hint}" if note else hint
        await matcher.finish(
            _waifu_reply(event, image_url, _waifu_text(record, note))
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
        kind, drawn = await _draw_character_with_fallback(
            settings, group_settings, source, exclude_ids
        )
        if drawn is None:
            await matcher.finish("更换失败，请稍后再试")
        if kind == "local":
            local = drawn
            character = _to_vndb_character(local)
            record = waifu.save_waifu(
                user_id,
                character,
                source=source,
                library_path=_library_path(local),
                group_id=group_id,
                role=str(local.data.get("role") or ""),
            )
            image_url = await _local_reply_image(
                local, record.get("image_url") or ""
            )
        else:
            character = drawn
            record = waifu.save_waifu(
                user_id, character, source=source, group_id=group_id
            )
            image_url = await _record_reply_image(record)
        if source not in companies.FIXED_WAIFU_COMPANIES:
            waifu_usage.mark_used(character.id)
        await matcher.finish(
            _waifu_reply(
                event,
                image_url,
                _waifu_text(record, ""),
            )
        )
    elif command == "set":
        keyword = arg.strip()
        target_user_id = user_id
        at_ids = _at_user_ids(event)
        if at_ids:
            target_user_id = at_ids[0]
        else:
            first, _, rest = keyword.partition(" ")
            if first.isdigit() and rest:
                target_user_id = int(first)
                keyword = rest.strip()
        if target_user_id != user_id and not is_admin:
            await matcher.finish("只有管理员可以指定每日老婆")
        if (
            target_user_id == user_id
            and not is_admin
            and not shoukeni_state.has_token(user_id)
        ):
            await matcher.finish("只有管理员可以指定每日老婆")
        if not keyword:
            await matcher.finish(
                "用法：/waifu set [@某人|<QQ号>] <角色名或VNDB ID>"
            )
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
            image_url = await _record_reply_image(record)
        if not is_admin:
            shoukeni_state.consume_token(user_id)
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
        at_ids = _at_user_ids(event)
        target = arg.strip()
        if at_ids:
            target_user_id = at_ids[0]
        elif target.isdigit() and int(target) > 0:
            target_user_id = int(target)
        else:
            await matcher.finish(
                "用法：/waifu check @某人 或 /waifu check <QQ号>"
            )
        existing = waifu.get_today_waifu(target_user_id)
        if existing is None:
            await matcher.finish(f"用户 {target_user_id} 今天还没有每日老婆")
        reply_image = await _record_reply_image(existing)
        existing_source = str(existing.get("source") or "waifu")
        source_command = companies.FIXED_WAIFU_COMMANDS.get(
            existing_source, "/waifu"
        )
        note = (
            f"用户 {target_user_id} 今天抽的是 "
            f"{source_command}（管理员查看）"
        )
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
        at_ids = _at_user_ids(event)
        target_user_id: int | None = None
        if at_ids:
            target_user_id = at_ids[0]
        elif target.isdigit() and int(target) > 0:
            target_user_id = int(target)
        if target_user_id is None and (not target or target.lower() == "all"):
            count, can_undo = waifu.reset_waifu_with_undo(None)
            suffix = "，可用 /waifu undo 撤销" if can_undo else ""
            await matcher.finish(
                f"已重置全部用户的每日老婆（{count} 人），今天可以重新抽取{suffix}"
            )
        if target_user_id is not None:
            count, can_undo = waifu.reset_waifu_with_undo(target_user_id)
            if count:
                suffix = "，可用 /waifu undo 撤销" if can_undo else ""
                await matcher.finish(
                    f"已重置用户 {target_user_id} 的每日老婆{suffix}"
                )
            await matcher.finish(
                f"用户 {target_user_id} 今天还没有每日老婆"
            )
        await matcher.finish("用法：/waifu reset [all|@某人|<QQ号>]")
    else:
        await matcher.finish(
            "用法：/waifu [reroll|set [@某人|<QQ号>] <角色名>|"
            "check [@某人|<QQ号>]|2025|collection [yuzu]|"
            "settings|reset [all|@某人|<QQ号>]|undo]"
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
_fixed_company_ids_cache: dict[str, list[str]] = {}


async def _yuzusoft_ids() -> list[str]:
    global _yuzusoft_ids_cache
    if _yuzusoft_ids_cache is None:
        search_names = [
            str(name) for name in companies.fixed_search_names("yuzusoft")
        ]
        ids = library.resolve_company_ids(search_names)
        if not ids:
            try:
                ids = await vndb.resolve_company_ids(search_names)
            except Exception:
                ids = []
        _yuzusoft_ids_cache = ids or ["p98", "p12215"]
    return _yuzusoft_ids_cache


async def _company_ids(company_key: str) -> list[str]:
    """解析固定会社的 VNDB 厂商 ID（本地库优先，VNDB 兜底）。"""
    if company_key == "yuzusoft":
        return await _yuzusoft_ids()
    cached = _fixed_company_ids_cache.get(company_key)
    if cached is not None:
        return cached
    search_names = companies.fixed_search_names(company_key)
    ids = library.resolve_company_ids(search_names)
    if not ids:
        try:
            ids = await vndb.resolve_company_ids(search_names)
        except Exception:
            ids = []
    if ids:
        _fixed_company_ids_cache[company_key] = ids
    return ids


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

    company_key = companies.FIXED_WAIFU_COMPANIES.get(source)
    if company_key:
        cache_key: str | None = company_key
        company_ids = await _company_ids(company_key)
        if not company_ids:
            label = companies.FIXED_WAIFU_LABELS.get(source, source)
            raise RuntimeError(f"无法解析 {label} 的厂商 ID")
    elif group_settings["company_ids"]:
        cache_key = (
            group_settings["companies"][0]
            if group_settings["companies"]
            else None
        )
        company_ids = group_settings["company_ids"]
    else:
        cache_key, company_ids = _pick_pool_company(settings)

    use_lru = source not in companies.FIXED_WAIFU_COMPANIES
    character: VNDBCharacter | None = None
    if cache_key and waifu_cache.is_fresh(cache_key):
        character = waifu_cache.pick_character(
            cache_key, popular, year_from, year_to, lru=use_lru
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
                    cache_key, popular, year_from, year_to, lru=use_lru
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
        lines.append("可设置的默认池（waifu 专用，会社专属入口不受影响）：")
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
    if action == "exclude":
        if len(parts) < 2 or parts[1].lower() not in ("add", "remove", "list"):
            await matcher.finish(
                "用法：/waifu settings exclude add|remove <角色ID> | list"
            )
        sub = parts[1].lower()
        if sub == "list":
            ids = sorted(library.excluded_ids())
            if not ids:
                await matcher.finish("抽卡黑名单为空")
            lines = ["【抽卡黑名单】"] + [f"- {cid}" for cid in ids]
            await matcher.finish("\n".join(lines))
        if len(parts) < 3 or not parts[2]:
            await matcher.finish("请提供角色 ID（如 c155769）")
        cid = parts[2].strip()
        if sub == "add":
            library.add_excluded(cid)
            await matcher.finish(f"已将 {cid} 加入抽卡黑名单（不再被抽到）")
        if library.remove_excluded(cid):
            await matcher.finish(f"已将 {cid} 移出抽卡黑名单")
        await matcher.finish(f"{cid} 不在黑名单中")
    await matcher.finish(
        "用法：/waifu settings [popular <N>|year <起始年> [结束年]|"
        "exclude add|remove <角色ID>|exclude list|"
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
    else:
        lines.append("你还没抽今天的每日老婆（/waifu 或会社专属入口）")
    if their_record is not None:
        lines.append(f"【用户 {target_user_id} 今天的每日老婆】")
        lines.append(collection.waifu_display(their_record))
    else:
        lines.append(f"用户 {target_user_id} 今天还没抽每日老婆")
    lines.append("互换请发：/waifu trade @对方")
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
    source: str = "yuzu",
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
                command = companies.FIXED_WAIFU_COMMANDS.get(
                    source, "/waifu"
                )
                await matcher.finish(
                    f"你还没抽今天的每日老婆，发 {command} 抽一张吧"
                )
            lines = [
                "【你今天的每日老婆】",
                collection.waifu_display(my_record),
                "互换请发：/waifu trade @对方",
            ]
            await matcher.finish("\n".join(lines))
        await matcher.finish(_trade_pick_hint(user_id, target_user_id))

    if action == "collection":
        # 会社专属图鉴：检索/序号都限定在该会社内
        company_source = (
            source if source in companies.FIXED_WAIFU_COMPANIES else None
        )
        label = companies.FIXED_WAIFU_LABELS.get(company_source or "", "")
        command = companies.FIXED_WAIFU_COMMANDS.get(
            company_source or "", "/waifu"
        )
        keyword, page = _extract_page(value)
        if keyword:
            if keyword.lower() in _SEARCH_ONLY_WORDS:
                await matcher.finish(
                    f"用法：{command} collection search <关键词>"
                )
            search_match = _SEARCH_PREFIX_RE.match(keyword)
            if search_match:
                keyword = search_match.group(1).strip()
                if not keyword:
                    await matcher.finish(
                        f"用法：{command} collection search <关键词>"
                    )
        await asyncio.to_thread(collection_book.enrich_from_library, user_id)
        if keyword in ("usage", "help", "用法", "帮助"):
            suffix = f"\n（当前为{label}图鉴模式）" if label else ""
            await matcher.finish(collection_book.usage_text() + suffix)
        if keyword:
            matches = collection_book.search_collection(
                user_id, keyword, company_source=company_source
            )
            if not matches:
                await matcher.finish(
                    f"{label or ''}图鉴里没有找到「{keyword}」相关的角色，"
                    "试试更短的名字或作品名"
                )
            if len(matches) > 1:
                lines = [f"找到 {len(matches)} 个{label}匹配角色："]
                for match in matches[:8]:
                    index = collection_book.collection_index(
                        user_id,
                        str(match.get("character_id") or ""),
                        company_source=company_source,
                    )
                    name_prefix = f"{index}. " if index else "- "
                    lines.append(name_prefix + _display_name(match))
                if len(matches) > 8:
                    lines.append(
                        f"……另有 {len(matches) - 8} 个匹配，请缩小关键词"
                    )
                lines.append(
                    f"发序号或更精确的名字查看卡片："
                    f"{command} collection <序号|名字>"
                )
                await matcher.finish("\n".join(lines))
            record = matches[0]
            reply_image = await _record_reply_image(record)
            note = (
                f"{label}图鉴角色：{_display_name(record)}"
                f"（收录于 {collection_book.user_collection(user_id).get(str(record.get('character_id')), {}).get('first_seen', '')[:10]}）"
            )
            await matcher.finish(_waifu_reply(event, reply_image, _waifu_text(record, note)))
        await matcher.finish(
            collection_book.collection_text(
                user_id,
                company_source=company_source,
                page=page,
                command=f"{command} collection",
            )
        )

    if action == "trade":
        if not at_ids:
            await matcher.finish(
                "用法：/waifu trade @对方（交换双方今天的每日老婆）"
            )
        target_user_id = at_ids[0]
        try:
            trade = collection.propose_trade(user_id, target_user_id)
        except ValueError as exc:
            await matcher.finish(str(exc))
        my_record = waifu.get_today_waifu(user_id)
        their_record = waifu.get_today_waifu(target_user_id)
        group_id = getattr(event, "group_id", None)
        notified = False
        if group_id is not None:
            notice = (
                f" 收到来自 {user_id} 的每日老婆交易提议 #{trade['id']}\n"
                "对方给出：\n"
                f"{collection.waifu_display(my_record)}\n"
                "你需要给出：\n"
                f"{collection.waifu_display(their_record)}\n"
                "10 分钟内回复：/waifu accept（拒绝：/waifu reject）"
            )
            try:
                await matcher.send(
                    Message(
                        [
                            MessageSegment.at(target_user_id),
                            MessageSegment.text(notice),
                        ]
                    )
                )
                notified = True
            except Exception as exc:
                nonebot.logger.warning("waifu 交易提醒发送失败：{}", exc)
        if notified:
            hint = "已在群里 @ 提醒对方，等待对方在 10 分钟内确认"
        else:
            hint = "请让对方在 10 分钟内发送 /waifu accept"
        lines = [
            f"交易提议 #{trade['id']}",
            "你给出：",
            collection.waifu_display(my_record),
            "你想换取：",
            collection.waifu_display(their_record),
            hint,
            "接受：/waifu accept（由对方操作）",
            "拒绝：/waifu reject（由对方操作）",
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
            "发 /waifu list 查看你现在的每日老婆"
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
