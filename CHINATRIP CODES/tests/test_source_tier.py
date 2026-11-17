"""source_tier 共享模块守卫测试（2026-11-13 名录序：国际站 > unesco > 5A）。

catalog_rank 全档判定 / order_source_tags 展示序 / source_tag_key
unesco 前缀族 / tags_source_wins 权威闸 / SOURCE_PRIORITY 15 项铁律
（2026-11-12 需求驱动重排）
（CLAUDE.md Iron rule 精确全文）。"""

from app.services.source_tier import (
    SOURCE_PRIORITY,
    catalog_rank,
    order_source_tags,
    source_tag_key,
    tags_source_wins,
)

# --- catalog_rank：名录档序号（0 起小值优先），每档一例 ----------------------


def test_catalog_rank_each_tier():
    assert catalog_rank("tripadvisor", []) == 0  # 05 国际旅行网站（2026-11-13 升首档）
    assert catalog_rank("baidu", ["curated"]) == 0  # curated 算国际网站档
    assert catalog_rank("unesco", []) == 1  # 08 世界遗产
    assert catalog_rank("5a", []) == 2  # 02 5A
    assert catalog_rank("sygic", []) == 3  # 10 国际平台
    assert catalog_rank("tiktok", []) == 4  # 11 短视频
    assert catalog_rank("youtube", []) == 4
    assert catalog_rank("xiaohongshu", []) == 5  # 12 小红书
    assert catalog_rank("street", ["街区"]) == 6  # 01 街区
    assert catalog_rank("scenic", ["风景名胜"]) == 7  # 04 风景名胜
    assert catalog_rank("baidu", ["4a"]) == 8  # 13 4A
    assert catalog_rank("4a", []) == 8
    assert catalog_rank("museum1", []) is None  # 名录外 → 消费口径自定「其他」
    assert catalog_rank(None, None) is None


def test_catalog_rank_unesco_prefix_family():
    # unesco_* 前缀族（丝路/明清陵寝/喀斯特…）视同 unesco，压过行上 5a
    assert catalog_rank("baidu", ["unesco_silk_road"]) == 1
    assert catalog_rank("5a", ["unesco_ming_tombs"]) == 1
    assert catalog_rank(None, ["unesco_karst"]) == 1


def test_catalog_rank_specific_site_beats_umbrella_intl():
    # 'intl' 伞标 05/10 两路 import 都写，只有站点明细能区分归属：
    # 带明站的行不被伞标抢先——['intl','tiktok']=短视频档、
    # ['sygic','tiktok']=平台档、裸 ['intl']=平台档（既有约定）
    assert catalog_rank(None, ["intl", "tiktok"]) == 4
    assert catalog_rank(None, ["sygic", "tiktok"]) == 3
    assert catalog_rank(None, ["intl"]) == 3
    assert catalog_rank(None, ["ta", "intl"]) == 0


def test_catalog_rank_xiaohongshu_chinese_tag():
    assert catalog_rank("baidu", ["小红书"]) == 5


# --- order_source_tags：tags 展示序（unesco 族最先，未知垫底） ---------------


def test_order_source_tags_new_catalog_order():
    tags = [
        "klook",
        "ta",
        "4a",
        "unesco_silk_road",
        "lp",
        "tiktok",
        "sygic",
        "国家一级博物馆",
    ]
    assert order_source_tags(tags) == [
        "unesco_silk_road",  # unesco 前缀族视同 unesco 最先
        "ta",
        "lp",
        "sygic",
        "klook",
        "tiktok",
        "4a",
        "国家一级博物馆",  # 未列标签垫底
    ]


def test_order_source_tags_unesco_exact_first():
    assert order_source_tags(["5a", "unesco", "ta"])[0] == "unesco"


def test_source_tag_key_prefixed_unesco_and_unknown():
    assert source_tag_key("unesco_ming_tombs") == source_tag_key("unesco")
    assert source_tag_key("unesco") == 0
    assert source_tag_key("nope") == 99


# --- tags_source_wins：归因权威闸（大值=高权威，相等放行保幂等） --------------


def test_tags_source_wins_authority_gate():
    assert not tags_source_wins("glm", "mct")  # 官方归因不被市场口径冒充
    assert not tags_source_wins("ctrip", "mohurd")
    assert not tags_source_wins("glm", "show")  # show 名录对市场口径仍权威
    assert tags_source_wins("glm", "ctrip")  # 平级放行（幂等重跑）
    assert tags_source_wins("ctrip", "glm")
    assert tags_source_wins("glm", None)  # 旧值空放行
    assert not tags_source_wins("unknown_new", "glm")  # 未知源按 0
    assert tags_source_wins("mct", "glm")


# --- SOURCE_PRIORITY：字段回填铁律全序（2026-11-12 需求驱动重排） ------


def test_source_priority_iron_rule_full_list():
    assert SOURCE_PRIORITY == (
        "curated",
        "lonelyplanet",
        "tripadvisor",
        "viator",
        "unesco",
        "5a",
        "museum1",
        "museum2",
        "museum3",
        "artmuseum",
        "street",
        "histown",
        "amap",
        "chinatravel",
        "osm",
    )
