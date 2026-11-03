"""来源档位共享常量（全站唯一定义点）。

名录采纳优先序（用户 2026-11-03 拍板，编号=DESIGN/POIS DATASOURCE 名录文件序）：

    08 世界遗产(unesco) > 02 5A(5a)
        > 05 国际旅行网站推荐(ta/lp/viator/curated)
        > 10 国际平台中国推荐(sygic/klook/... 16 站)
        > 11 短视频与社媒(tiktok/instagram/youtube)
        > 12 小红书(xiaohongshu)
        > 01 国家级旅游休闲街区(street)
        > 04 国家级风景名胜(scenic)
        > 13 4A(4a)
        > 其他（库序）

三个消费口径全部从这里取，不得各抄一份：

- 读侧评分 hit_tier / apply_tier_tag / _TIER_BOOST（app/services/poi_details.py）
- 规划选点 _source_tier（app/services/agent/plan.py）
- 字段回填铁律 _SOURCE_PRIORITY（app/jobs/*，见 CLAUDE.md Iron rule；拼写 chinatravel）
"""

from __future__ import annotations

# ---------------------------------------------------------------- 名录档位判定

INTL_SITE_SOURCES = frozenset({"tripadvisor", "lonelyplanet", "viator", "curated"})
INTL_SITE_TAGS = frozenset({"ta", "lp", "viator", "curated"})

# 10 号名录：国际平台（AI 规划师与各国 Agency，import_intl_platforms 19 站点
# 去掉短视频三站与小红书）。裸 "intl" 伞标签行（无站点明细）按平台档计——
# 05/10 两路 import 都写 intl 伞标，只有站点明细能区分，沿用既有约定。
INTL_PLATFORM_SOURCES = frozenset(
    {
        "sygic",
        "klook",
        "kkday",
        "waug",
        "mindtrip",
        "layla",
        "culturetrip",
        "watchmojo",
        "tui",
        "liontravel",
        "his",
        "jtb",
        "itaka",
        "tourtrans",
        "yanolja",
        "wonderplan",
    }
)
INTL_PLATFORM_TAGS = frozenset(
    {
        "intl",
        "sygic",
        "klook",
        "kkday",
        "waug",
        "mindtrip",
        "layla",
        "culturetrip",
        "watchmojo",
        "tui",
        "liontravel",
        "his",
        "jtb",
        "itaka",
        "tourtrans",
        "yanolja",
        "wonderplan",
    }
)

# 11 号名录：短视频与社媒（入库标签即站点码，无 douyin）
SHORTVIDEO_SOURCES = frozenset({"tiktok", "instagram", "youtube"})
SHORTVIDEO_TAGS = SHORTVIDEO_SOURCES


def catalog_rank(
    source: str | None,
    tags: list[str] | tuple[str, ...] | set[str] | None,
) -> int | None:
    """名录档序号（0 起，小值优先）：0=unesco ... 8=4a。

    返回 None = 不在名录序（museum*/3a/show/amap/osm 等其他源），
    由各消费口径决定「其他」档怎么落。判定先走明站（具体站点标签）
    再走伞标兜底：'intl' 伞标签 05/10 两路 import 都写，只有站点明细
    能区分归属，带明站的行不被伞标抢先（['intl','tiktok']=短视频档，
    ['sygic','tiktok']=平台档，裸 ['intl']=平台档——沿用既有约定）。
    """
    src = str(source or "").strip().lower()
    tagset = {str(t).strip().lower() for t in (tags or [])}
    if src == "unesco" or any(t == "unesco" or t.startswith("unesco_") for t in tagset):
        return 0
    if src == "5a" or "5a" in tagset:
        return 1
    if src in INTL_SITE_SOURCES or tagset & INTL_SITE_TAGS:
        return 2
    platform_specific_tags = INTL_PLATFORM_TAGS - {"intl"}
    if src in INTL_PLATFORM_SOURCES or tagset & platform_specific_tags:
        return 3
    if src in SHORTVIDEO_SOURCES or tagset & SHORTVIDEO_TAGS:
        return 4
    if src == "xiaohongshu" or "xiaohongshu" in tagset or "小红书" in " ".join(tagset):
        return 5
    if src == "street" or "街区" in " ".join(tagset):
        return 6
    if src == "scenic" or "风景名胜" in " ".join(tagset):
        return 7
    if src == "4a" or "4a" in tagset:
        return 8
    if "intl" in tagset:
        return 3
    return None


# ---------------------------------------------------------------- tags 打标序

# 多来源打标序（用户 2026-11-03 名录序取代 2026-10-26「国外榜单放前」）：
# 展示 tags 列表时按此排，未列出的走垫底；unesco_* 前缀族（silk_road/
# ming_tombs/karst/whc_NNNN）视同 unesco。
SOURCE_TAG_ORDER: dict[str, int] = {
    "unesco": 0,
    "5a": 1,
    "ta": 2,
    "lp": 3,
    "viator": 4,
    "curated": 5,
    "intl": 6,
    "sygic": 7,
    "klook": 8,
    "kkday": 9,
    "waug": 10,
    "mindtrip": 11,
    "layla": 12,
    "culturetrip": 13,
    "watchmojo": 14,
    "tui": 15,
    "liontravel": 16,
    "his": 17,
    "jtb": 18,
    "itaka": 19,
    "tourtrans": 20,
    "yanolja": 21,
    "tiktok": 22,
    "instagram": 23,
    "youtube": 24,
    "xiaohongshu": 25,
    "street": 26,
    "scenic": 27,
    "4a": 28,
    "3a": 29,
}

_UNKNOWN_TAG_RANK = 99


def source_tag_key(tag: str) -> int:
    t = str(tag).strip().lower()
    if t in SOURCE_TAG_ORDER:
        return SOURCE_TAG_ORDER[t]
    if t.startswith("unesco"):
        return SOURCE_TAG_ORDER["unesco"]
    return _UNKNOWN_TAG_RANK


def order_source_tags(tags: list[str]) -> list[str]:
    return sorted(tags, key=source_tag_key)


# ---------------------------------------------------------------- 字段回填铁律

# CLAUDE.md Iron rule 全文（canonical order，一个字不改；拼写 chinatravel）。
# 各回填 job 必须 import 本常量，不得手抄短表；池里有而此表没有的源，
# 由该 job 以「元组拼接追加在尾部」的方式带上（同 change 内追加是规矩）。
SOURCE_PRIORITY: tuple[str, ...] = (
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

# ---------------------------------------------------------------- tags_source 权威闸

# 大值 = 高权威。官方名录归因（mct 文旅部 / mohurd 住建部）不被市场口径
# （glm/ctrip 抽取）与国际商业站点归因冒充；show 名录对市场口径仍权威。
# 闸语义：新归因权威 **严格低于** 已有归因时不得改写 tags_source
# （相等放行保幂等重跑；tags 并集不受此闸，只管归因列）。
TAGS_SOURCE_AUTHORITY: dict[str, int] = {
    "mct": 3,
    "mohurd": 3,
    "show": 2,
    "glm": 1,
    "ctrip": 1,
}


def tags_source_wins(new_source: str, old_source: str | None) -> bool:
    """新归因是否可写：权威 >= 既有（未知源按 0）。"""
    return TAGS_SOURCE_AUTHORITY.get(str(new_source or "").strip().lower(), 0) >= (
        TAGS_SOURCE_AUTHORITY.get(str(old_source or "").strip().lower(), 0)
    )
