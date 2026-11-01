"""会社名单测试。"""

from __future__ import annotations

from waifu_box import companies


def test_catalog_contains_expected_companies() -> None:
    expected = {
        "yuzusoft",
        "madosoft",
        "smee",
        "favorite",
        "purplesoftware",
        "key",
        "palette",
        "sagaplanets",
        "toneworks",
        "lumpofsugar",
        "asaproject",
        "whirlpool",
        "laplacian",
        "clochette",
        "august",
        "sprite",
        "navel",
        "frontwing",
        "typemoon",
        "aquaplusleaf",
        "nitroplus",
        "circus",
        "minatosoft",
        "nekoworks",
        "lose",
        "hooksoft",
        "cuffs",
        "azarashisoft",
        "alicesoft",
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
    }
    assert set(companies.COMPANIES) == expected


def test_waifu_pool_keys_cover_requested_companies() -> None:
    pool = companies.WAIFU_POOL_KEYS
    assert "yuzusoft" in pool
    assert "key" in pool
    assert "august" in pool
    assert "alicesoft" in pool
    assert "aquaplusleaf" in pool
    assert "frontwing" in pool
    assert "palette" in pool
    assert "sagaplanets" in pool
    assert "favorite" in pool
    assert "purplesoftware" in pool
    assert "navel" in pool
    assert "circus" in pool
    assert "keroq" in pool
    assert "makura" in pool
    assert "cabbagesoft" in pool
    assert "mages" in pool
    assert "crystalia" in pool
    assert "entergram" in pool


def test_fixed_waifu_includes_new_special_pools() -> None:
    """Makura / August / Nitroplus 作为特殊卡池会社入口。"""
    assert companies.FIXED_WAIFU_COMPANIES["makura"] == "makura"
    assert companies.FIXED_WAIFU_COMPANIES["august"] == "august"
    assert companies.FIXED_WAIFU_COMMANDS["makura"] == "/makurawaifu"
    assert companies.FIXED_WAIFU_COMMANDS["august"] == "/augustwaifu"
    assert "Makura" in companies.FIXED_WAIFU_LABELS["makura"]
    assert "August" in companies.FIXED_WAIFU_LABELS["august"]
    assert companies.FIXED_WAIFU_COMPANIES["nitro"] == "nitroplus"
    assert companies.FIXED_WAIFU_COMMANDS["nitro"] == "/nitroplus"
    assert "Nitroplus" in companies.FIXED_WAIFU_LABELS["nitro"]
    assert companies.FIXED_WAIFU_COMPANIES["qruppo"] == "qruppo"
    assert companies.FIXED_WAIFU_COMMANDS["qruppo"] == "/qruppowaifu"
    assert companies.FIXED_WAIFU_LABELS["qruppo"] == "Qruppo"


def test_fixed_waifu_search_splits_hooksoft_brands() -> None:
    """固定入口按品牌拆分：HOOKSOFT 本体、SMEE、ASa Project 各自独立。"""
    assert companies.fixed_search_names("hooksoft") == ["HOOKSOFT", "Hooksoft"]
    assert "SMEE" not in companies.fixed_search_names("hooksoft")
    assert companies.fixed_search_names("smee") == ["SMEE"]
    assert companies.fixed_search_names("asaproject") == ["ASa Project"]


def test_catalog_includes_subsidiary_search_names() -> None:
    assert "Yuzusoft SOUR" in companies.COMPANIES["yuzusoft"]["search"]
    assert "SMEE" in companies.COMPANIES["hooksoft"]["search"]
    assert "CUBE" in companies.COMPANIES["cuffs"]["search"]
    assert "Lime" in companies.COMPANIES["navel"]["search"]


def test_display_names_joins_selected_keys() -> None:
    text = companies.display_names(["yuzusoft", "smee"])
    assert "Yuzusoft（柚子社）" in text
    assert "SMEE" in text
