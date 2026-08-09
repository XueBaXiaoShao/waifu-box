"""每日老婆独立插件：/waifu 与 /yuzuwaifu。

/waifu 基于本地 final_company_library 抽卡并生成角色信息卡片，/yuzuwaifu
保持柚子社 VNDB 原行为；支持 LRU 轮换、每日缓存刷新、群级后门与会社池。
"""

from nonebot.plugin import PluginMetadata

from . import commands  # noqa: F401
from .scheduler import setup_cache_refresh

__plugin_meta__ = PluginMetadata(
    name="每日老婆（waifu-box）",
    description=(
        "本地 final_company_library 角色卡 /waifu 与柚子社 /yuzuwaifu，"
        "LRU 轮换、本地缓存、每日定时刷新"
    ),
    usage=(
        "/waifu、/yuzuwaifu、/waifu settings、/waifu reset、"
        "/waifu settings group=<群号> kaisha=<会社key|off>"
    ),
    type="application",
    homepage="",
    supported_adapters={"~onebot.v11"},
)

setup_cache_refresh()
