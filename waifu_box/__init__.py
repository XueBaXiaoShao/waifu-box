"""每日老婆独立插件：/waifu 与 /yuzuwaifu。

从 galgame-box 拆出的独立插件：VNDB 角色抽卡、LRU 轮换、本地缓存、
每日定时增量刷新、群级后门与全局会社池。
"""

from nonebot.plugin import PluginMetadata

from . import commands  # noqa: F401
from .scheduler import setup_cache_refresh

__plugin_meta__ = PluginMetadata(
    name="每日老婆（waifu-box）",
    description=(
        "VNDB 角色每日老婆：/waifu 与 /yuzuwaifu，LRU 轮换、本地缓存、"
        "每日定时刷新"
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
