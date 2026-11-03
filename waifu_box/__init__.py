"""每日老婆独立插件：/waifu 与会社专属入口。

/waifu 与所有会社专属入口（yuzu/key/saga/purple/front/crystal/hook/
mado/pal/favo/makura/august/nitro/qruppo/cube/cuffs）都基于本地 final_company_library 抽卡并生成
角色信息卡片，全部共享每日额度；会社专属入口固定从对应会社抽卡，普通
/waifu 支持 LRU
轮换、群级后门与会社池；每日老婆支持用户间互换（展示与交易读取同一
数据源 waifu_state.json）。
"""

from nonebot.plugin import PluginMetadata

from . import commands, shoukeni  # noqa: F401
from .scheduler import setup_cache_refresh

__plugin_meta__ = PluginMetadata(
    name="每日老婆（waifu-box）",
    description=(
        "本地 final_company_library 角色卡 /waifu 与 18 个会社专属入口，"
        "共享每日额度、LRU 轮换、群级后门与会社池；每日老婆支持互换交易"
    ),
    usage=(
        "/waifu、/waifu <会社>、/yuzuwaifu、/keywaifu、/sagawaifu、"
        "/purplewaifu、/frontwaifu、/crystalwaifu、/hookwaifu、"
        "/smeewaifu、/asawaifu、"
        "/madowaifu、/palwaifu、/favowaifu、"
        "/makurawaifu、/augustwaifu、/nitroplus、/qruppowaifu、/cubewaifu、"
        "/cuffswaifu、"
        "/waifu settings、/waifu reset、/waifu undo、"
        "/waifu settings group=<群号> kaisha=<会社key|off>、"
        "/waifu list、/waifu trade @对方、"
        "/waifu accept|reject <交易号>"
    ),
    type="application",
    homepage="",
    supported_adapters={"~onebot.v11"},
)

setup_cache_refresh()
