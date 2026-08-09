"""每日老婆会社名单：可筛选的会社及其旗下品牌搜索名。

选择某个会社时会一并解析其旗下品牌（search 列表）对应的 VNDB 厂商 ID，
例如选 Yuzusoft 会包含 Yuzusoft SOUR，选 HOOKSOFT 会包含 SMEE / ASa Project。
"""

from __future__ import annotations

COMPANIES: dict[str, dict[str, object]] = {
    "yuzusoft": {"display": "Yuzusoft（柚子社）", "search": ["Yuzusoft", "Yuzusoft SOUR"]},
    "madosoft": {"display": "Madosoft（窗社）", "search": ["Madosoft"]},
    "smee": {"display": "SMEE", "search": ["SMEE"]},
    "favorite": {"display": "FAVORITE（F社）", "search": ["FAVORITE"]},
    "purplesoftware": {
        "display": "Purple software（紫社）",
        "search": ["Purple software"],
    },
    "key": {"display": "Key（键社）", "search": ["Key"]},
    "palette": {"display": "PALETTE（调色板社）", "search": ["PALETTE", "Clear"]},
    "sagaplanets": {"display": "SAGA PLANETS（行星社）", "search": ["SAGA PLANETS"]},
    "toneworks": {"display": "Tone Work's", "search": ["Tone Work's", "Toneworks"]},
    "lumpofsugar": {
        "display": ".Lump of Sugar（方糖社）",
        "search": [".Lump of Sugar", "Lump of Sugar"],
    },
    "asaproject": {"display": "ASa Project", "search": ["ASa Project"]},
    "whirlpool": {"display": "Whirlpool（漩涡社）", "search": ["Whirlpool"]},
    "laplacian": {"display": "Laplacian", "search": ["Laplacian"]},
    "clochette": {"display": "Clochette", "search": ["Clochette"]},
    "august": {"display": "August（八月社）", "search": ["August"]},
    "sprite": {"display": "sprite（雪碧社）", "search": ["sprite"]},
    "navel": {"display": "Navel（柠檬社）", "search": ["Navel", "Lime"]},
    "frontwing": {
        "display": "Frontwing（前翼社）",
        "search": ["Frontwing", "Front Wing"],
    },
    "typemoon": {"display": "Type-Moon（型月）", "search": ["Type-Moon", "TYPE-MOON"]},
    "aquaplusleaf": {
        "display": "AQUAPLUS / Leaf（叶社）",
        "search": ["AQUAPLUS", "Aquaplus", "Leaf"],
    },
    "nitroplus": {"display": "Nitroplus（N+社）", "search": ["Nitroplus", "Nitro Plus"]},
    "circus": {"display": "CIRCUS（马戏团）", "search": ["CIRCUS", "Marble"]},
    "minatosoft": {"display": "Minato Soft（凑社）", "search": ["Minato Soft"]},
    "nekoworks": {"display": "NEKO WORKs", "search": ["NEKO WORKs", "Neko Works"]},
    "lose": {"display": "Lose", "search": ["Lose"]},
    "hooksoft": {
        "display": "HOOKSOFT",
        "search": ["HOOKSOFT", "Hooksoft", "SMEE", "ASa Project"],
    },
    "cuffs": {"display": "CUFFS", "search": ["CUFFS", "CUBE", "Sphere", "MintCUBE"]},
    "azarashisoft": {
        "display": "Azarashisoft（あざらしそふと）",
        "search": ["Azarashisoft"],
    },
    "alicesoft": {
        "display": "AliceSoft（アリスソフト）",
        "search": ["AliceSoft", "Alice Soft", "アリスソフト"],
    },
    "keroq": {
        "display": "KeroQ（ケロQ）",
        "search": ["KeroQ", "ケロQ"],
    },
    "makura": {
        "display": "Makura（枕）",
        "search": ["Makura", "Makurasoft", "枕"],
    },
    "cabbagesoft": {
        "display": "Cabbage Soft（きゃべつそふと）",
        "search": ["Cabbage Soft", "きゃべつそふと"],
    },
    "acacia": {"display": "Acacia", "search": ["Acacia"]},
    "crystalia": {"display": "CRYSTALiA", "search": ["CRYSTALiA"]},
    "cube": {"display": "CUBE", "search": ["CUBE"]},
    "hermit": {"display": "HERMIT", "search": ["HERMIT"]},
    "heliodor": {"display": "Heliodor", "search": ["Heliodor"]},
    "innocentgrey": {
        "display": "Innocent Grey",
        "search": ["Innocent Grey"],
    },
    "mages": {"display": "MAGES.（MAGES）", "search": ["MAGES."]},
    "overdrive": {"display": "OVERDRIVE", "search": ["OVERDRIVE"]},
    "pulltop": {"display": "PULLTOP", "search": ["PULLTOP"]},
    "qruppo": {"display": "Qruppo", "search": ["Qruppo"]},
    "tactics": {"display": "Tactics", "search": ["Tactics"]},
    "elf": {"display": "elf（エルフ）", "search": ["elf"]},
    "akabeisoft2": {
        "display": "AKABEiSOFT2（あかべぇそふとつぅ）",
        "search": ["AKABEiSOFT2", "あかべぇそふとつぅ"],
    },
    "akabeisoft3": {
        "display": "AKABEiSOFT3（あかべぇそふとすりぃ）",
        "search": ["AKABEiSOFT3", "あかべぇそふとすりぃ"],
    },
    "syangrila": {"display": "Syangrila（しゃんぐりら）", "search": ["Syangrila"]},
    "uguisukagura": {
        "display": "Uguisu Kagura（ウグイスカグラ）",
        "search": ["Uguisu Kagura"],
    },
    "eushully": {
        "display": "Eushully（エウシュリー）",
        "search": ["Eushully", "エウシュリー"],
    },
    "silkyplusdolce": {
        "display": "SILKY'S PLUS DOLCE",
        "search": ["SILKY'S PLUS DOLCE"],
    },
    "silkypluswasabi": {
        "display": "SILKY'S PLUS WASABI",
        "search": ["SILKY'S PLUS WASABI"],
    },
    "totometori": {
        "display": "Totometori（トトメトリ）",
        "search": ["Totometori"],
    },
    "flyingshine": {
        "display": "FlyingShine（フライングシャイン）",
        "search": ["FlyingShine", "フライングシャイン"],
    },
    "kogado": {
        "display": "Kogado Studio（工画堂スタジオ）",
        "search": ["Kogado Studio", "工画堂スタジオ"],
    },
    "giga": {"display": "GIGA（戯画）", "search": ["GIGA", "戯画"]},
    "akatsuki": {
        "display": "Akatsuki WORKS（暁WORKS）",
        "search": ["Akatsuki WORKS", "暁WORKS"],
    },
    "entergram": {
        "display": "ENTERGRAM（エンターグラム）",
        "search": ["ENTERGRAM", "エンターグラム"],
    },
}


# 普通 waifu 的全局默认池：与 /yuzuwaifu 无关
WAIFU_POOL_KEYS = (
    "yuzusoft",
    "key",
    "august",
    "alicesoft",
    "aquaplusleaf",
    "frontwing",
    "palette",
    "sagaplanets",
    "favorite",
    "purplesoftware",
    "navel",
    "circus",
    "keroq",
    "makura",
    "cabbagesoft",
    "acacia",
    "crystalia",
    "cube",
    "hermit",
    "heliodor",
    "innocentgrey",
    "mages",
    "overdrive",
    "pulltop",
    "qruppo",
    "tactics",
    "elf",
    "akabeisoft2",
    "akabeisoft3",
    "syangrila",
    "uguisukagura",
    "eushully",
    "silkyplusdolce",
    "silkypluswasabi",
    "totometori",
    "flyingshine",
    "kogado",
    "giga",
    "akatsuki",
    "entergram",
    "sprite",
    "minatosoft",
    "azarashisoft",
    "whirlpool",
    "laplacian",
    "typemoon",
    "nitroplus",
)

# 旧版默认池：用于自动迁移到全量本地会社池
LEGACY_WAIFU_POOL_KEYS = (
    "yuzusoft",
    "key",
    "august",
    "alicesoft",
    "aquaplusleaf",
    "frontwing",
    "palette",
    "sagaplanets",
    "favorite",
    "purplesoftware",
    "navel",
    "circus",
    "keroq",
    "makura",
    "cabbagesoft",
)


def display_names(keys: list[str]) -> str:
    """把会社 key 列表转成展示名。"""
    names = [str(COMPANIES[key]["display"]) for key in keys if key in COMPANIES]
    return "、".join(names) if names else "不限"
