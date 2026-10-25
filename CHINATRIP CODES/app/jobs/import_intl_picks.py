"""国际旅行网站中国荐点种子导入（TripAdvisor/Lonely Planet/Viator）。

用户指令 2026-10-25：搜集主流旅行网站与代理商的中国推荐景点并入
pois 库，并逐条标注推荐来源。铁律 #9：外部源仅写骨架（名称/城市/
类别/标签）——坐标、营业时间、票价等时间敏感字段一律留给高德/携程
回源链（这些无 hours 新行会自然进入 refresh_pois 的 stale 窗口）。

来源标记（榜单页实测抓取 2026-10-25）：
  ta      = TripAdvisor 中国 Attractions 榜（全国 Top15 + 城市页摘要）
  lp      = Lonely Planet 13 best places / 8 best things / 城市榜系列
  viator  = Viator China things-to-do 摘要（黄山/布达拉宫/张家界）
  curated = 榜单只点到城市（LP「苏州园林运河」「重庆赛博朋克」），
            具体点位按国际游客通识补全，待回源链核实后转正

行内动作：库内已有正名/别名行 → 追加 intl+来源 tags（不覆盖原
source）；查无 → 插入 source='intl' 骨架行。子场所行（如
「豫园星空梦幻馆」「熊猫小匠研学基地」）不碰——正名行另行插入。

用法：
    python -m app.jobs.import_intl_picks [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid

from app.models import Poi

logger = logging.getLogger(__name__)

# (city, name_zh, name_en, sites, aliases)
# aliases = 库内已有的等价正名（优先合并标签而非重复插入）
_INTL_PICKS: list[tuple[str, str, str, list[str], list[str]]] = [
    # --- 北京（TA 全国榜 + LP 14 things） ---
    ("北京", "故宫博物院", "The Palace Museum (Forbidden City)", ["ta", "lp"], []),
    ("北京", "慕田峪长城", "Mutianyu Great Wall", ["ta", "lp"], []),
    ("北京", "八达岭长城", "Badaling Great Wall", ["ta", "lp"], []),
    ("北京", "颐和园", "Summer Palace", ["ta", "lp"], ["颐和园景区"]),
    ("北京", "天坛公园", "Temple of Heaven Park", ["ta", "lp"], ["天坛"]),
    ("北京", "天安门广场", "Tiananmen Square", ["ta", "lp"], []),
    ("北京", "景山公园", "Jingshan Park", ["lp"], []),
    ("北京", "钟鼓楼", "Drum & Bell Towers", ["lp"], ["鼓楼"]),
    ("北京", "南锣鼓巷", "Nanluoguxiang Hutong", ["lp"], []),
    ("北京", "明十三陵", "Ming Tombs", ["lp"], ["十三陵"]),
    ("北京", "潘家园旧货市场", "Panjiayuan Antique Market", ["lp"], ["潘家园"]),
    ("北京", "798艺术区", "798 Art District", ["ta"], []),
    # --- 上海（LP 16 things + TA 城市榜） ---
    ("上海", "外滩", "The Bund", ["ta", "lp"], []),
    ("上海", "豫园", "Yu Garden", ["ta", "lp"], []),
    (
        "上海",
        "东方明珠",
        "Oriental Pearl TV Tower",
        ["ta", "lp"],
        ["东方明珠广播电视塔"],
    ),
    ("上海", "上海中心大厦", "Shanghai Tower", ["lp"], []),
    ("上海", "田子坊", "Tianzifang", ["lp"], []),
    ("上海", "新天地", "Xintiandi", ["lp"], []),
    ("上海", "武康路", "Wukang Road & Former French Concession", ["lp"], []),
    ("上海", "静安寺", "Jing'an Temple", ["lp"], []),
    ("上海", "南京东路步行街", "East Nanjing Rd Pedestrian Street", ["lp"], []),
    ("上海", "上海博物馆", "Shanghai Museum", ["lp"], []),
    ("上海", "M50创意园", "M50 Art District", ["lp"], []),
    ("上海", "上海迪士尼乐园", "Shanghai Disneyland", ["lp"], []),
    (
        "上海",
        "中共一大纪念馆",
        "Site of the First CPC National Congress",
        ["lp"],
        ["中国共产党一大·二大·四大纪念馆景区"],
    ),
    ("上海", "朱家角古镇", "Zhujiajiao Water Town", ["lp"], ["朱家角古镇景区"]),
    (
        "上海",
        "黄浦江游览",
        "Huangpu River Cruise",
        ["lp"],
        ["黄浦江游览（东方明珠码头）"],
    ),
    # --- 苏州（LP detour 点到城市，点位通识补全） ---
    ("苏州", "拙政园", "Humble Administrator's Garden", ["lp"], []),
    ("苏州", "苏州博物馆", "Suzhou Museum", ["curated"], []),
    ("苏州", "平江路历史街区", "Pingjiang Road Historic Block", ["curated"], []),
    ("苏州", "七里山塘", "Shantang Street", ["curated"], ["山塘街"]),
    ("苏州", "虎丘山风景名胜区", "Tiger Hill Scenic Area", ["curated"], ["虎丘"]),
    ("苏州", "周庄古镇", "Zhouzhuang Water Town", ["curated"], ["周庄"]),
    # --- 杭州 ---
    ("杭州", "西湖风景名胜区", "West Lake", ["ta", "lp"], ["杭州西湖文化景观", "西湖"]),
    (
        "杭州",
        "灵隐飞来峰",
        "Lingyin Temple & Feilai Peak",
        ["curated"],
        ["飞来峰", "灵隐飞来峰景区", "灵隐寺"],
    ),
    ("杭州", "龙井村", "Longjing Tea Village", ["lp"], ["龙井问茶"]),
    (
        "杭州",
        "清河坊历史街区",
        "Qinghefang (Hefang St) Historic Block",
        ["curated"],
        ["清河坊街", "河坊街"],
    ),
    (
        "杭州",
        "拱宸桥·桥西历史文化街区",
        "Grand Canal: Gongchen Bridge & Qiaoxi Block",
        ["curated"],
        [],
    ),
    (
        "杭州",
        "西溪国家湿地公园",
        "Xixi National Wetland Park",
        ["curated"],
        ["西溪湿地"],
    ),
    # --- 南京 ---
    (
        "南京",
        "中山陵园风景区",
        "Sun Yat-sen Mausoleum",
        ["curated"],
        ["中山陵景区", "中山陵"],
    ),
    ("南京", "明孝陵", "Ming Xiaoling Mausoleum", ["curated"], []),
    (
        "南京",
        "夫子庙秦淮风光带",
        "Confucius Temple & Qinhuai River",
        ["ta"],
        ["南京夫子庙-秦淮风光带-长干里", "夫子庙"],
    ),
    (
        "南京",
        "南京城墙（中华门）",
        "Nanjing City Wall (Zhonghua Gate)",
        ["curated"],
        ["中华门瓮城", "南京城墙"],
    ),
    ("南京", "南京总统府", "Presidential Palace", ["curated"], ["总统府"]),
    ("南京", "南京博物院", "Nanjing Museum", ["curated"], []),
    (
        "南京",
        "侵华日军南京大屠杀遇难同胞纪念馆",
        "Nanjing Massacre Memorial Hall",
        ["ta"],
        [],
    ),
    # --- 广州（TA 城市榜 + LP） ---
    ("广州", "广州塔", "Canton Tower", ["ta"], []),
    ("广州", "沙面岛", "Shamian Island", ["ta"], ["沙面", "沙面公园"]),
    ("广州", "长隆野生动物世界", "Chimelong Safari Park", ["ta"], ["长隆野生动物园"]),
    (
        "广州",
        "珠江夜游",
        "Pearl River Night Cruise",
        ["ta", "lp"],
        ["珠江夜游广州塔财富码头"],
    ),
    ("广州", "陈家祠", "Chen Clan Ancestral Hall", ["curated"], ["陈家祠旅游区"]),
    ("广州", "光孝寺", "Guangxiao Temple", ["lp"], []),
    # --- 深圳 ---
    ("深圳", "世界之窗", "Window of the World", ["curated"], []),
    ("深圳", "华侨城创意文化园", "OCT-LOFT Creative Culture Park", ["lp"], []),
    ("深圳", "深圳湾公园", "Shenzhen Bay Park", ["curated"], []),
    ("深圳", "大梅沙海滨公园", "Dameisha Beach", ["curated"], ["大梅沙海滨浴场"]),
    # --- 成都（LP 两篇） ---
    (
        "成都",
        "成都大熊猫繁育研究基地",
        "Chengdu Research Base of Giant Panda Breeding",
        ["ta", "lp"],
        ["大熊猫繁育研究基地"],
    ),
    ("成都", "宽窄巷子", "Kuanzhai Alley (Wide & Narrow Alleys)", ["lp"], []),
    ("成都", "锦里古街", "Jinli Ancient Street", ["curated"], ["锦里"]),
    ("成都", "武侯祠", "Wuhou Shrine", ["curated"], ["成都武侯祠"]),
    ("成都", "杜甫草堂", "Du Fu Thatched Cottage", ["curated"], ["成都杜甫草堂"]),
    ("成都", "成都市人民公园", "People's Park (Heming Teahouse)", ["lp"], ["人民公园"]),
    ("成都", "金沙遗址博物馆", "Jinsha Site Museum", ["lp"], ["成都金沙遗址博物馆"]),
    (
        "成都",
        "都江堰景区",
        "Dujiangyan Irrigation System",
        ["curated"],
        ["都江堰水利工程", "都江堰风景区"],
    ),
    # --- 重庆（LP cyberpunk + 通识） ---
    ("重庆", "洪崖洞民俗风貌区", "Hongyadong (Hongya Cave)", ["ta", "lp"], ["洪崖洞"]),
    ("重庆", "长江索道", "Yangtze River Cableway", ["ta"], ["重庆长江索道"]),
    ("重庆", "磁器口古镇", "Ciqikou Ancient Town", ["curated"], ["磁器口"]),
    (
        "重庆",
        "李子坝轻轨站",
        "Liziba Station (Metro through Building)",
        ["curated"],
        ["李子坝站"],
    ),
    ("重庆", "两江夜游", "Two Rivers Night Cruise", ["curated"], ["朝天门两江夜游"]),
    # --- 武汉 ---
    ("武汉", "黄鹤楼", "Yellow Crane Tower", ["curated"], ["黄鹤楼公园"]),
    ("武汉", "湖北省博物馆", "Hubei Provincial Museum", ["curated"], []),
    (
        "武汉",
        "东湖生态旅游风景区",
        "East Lake Scenic Area",
        ["curated"],
        ["武汉东湖", "东湖风景区"],
    ),
    ("武汉", "昙华林", "Tanhualin Historic Block", ["curated"], ["昙华林历史文化街区"]),
    # --- Tier B：库未覆盖城市骨架（未来城市扩展信号） ---
    (
        "西安",
        "秦始皇帝陵博物院（兵马俑）",
        "Terracotta Warriors",
        ["ta", "lp"],
        ["秦始皇兵马俑博物馆", "兵马俑"],
    ),
    ("西安", "西安城墙", "Xi'an City Wall", ["lp"], ["西安明城墙"]),
    ("西安", "大雁塔", "Giant Wild Goose Pagoda", ["lp"], ["大雁塔大唐芙蓉园景区"]),
    ("西安", "回民街", "Muslim Quarter (Beiyuanmen)", ["lp"], ["北院门历史文化街区"]),
    ("西安", "西安钟楼", "Xi'an Bell Tower", ["lp"], ["钟楼"]),
    ("西安", "华清宫", "Huaqing Palace", ["curated"], ["华清池"]),
    (
        "乐山",
        "乐山大佛",
        "Leshan Giant Buddha",
        ["lp"],
        ["市中区乐山大佛景区", "乐山大佛景区"],
    ),
    ("敦煌", "莫高窟", "Mogao Grottoes", ["lp"], ["敦煌莫高窟"]),
    (
        "张掖",
        "张掖七彩丹霞景区",
        "Zhangye Rainbow Danxia",
        ["lp"],
        ["七彩丹霞", "张掖丹霞"],
    ),
    ("嘉峪关", "嘉峪关", "Jiayuguan Fort", ["lp"], ["嘉峪关文物景区"]),
    ("桂林", "漓江", "Li River", ["ta", "lp"], ["漓江风景区"]),
    ("桂林", "龙脊梯田", "Longji Rice Terraces", ["lp"], ["龙胜龙脊梯田"]),
    ("阳朔", "遇龙河", "Yulong River", ["lp"], ["阳朔遇龙河"]),
    ("阳朔", "阳朔西街", "West Street (Yangshuo)", ["lp"], ["西街"]),
    (
        "张家界",
        "张家界国家森林公园",
        "Zhangjiajie National Forest Park",
        ["ta", "viator"],
        ["武陵源"],
    ),
    ("张家界", "天门山", "Tianmen Mountain", ["lp"], ["武陵源天门山旅游区"]),
    ("丽江", "虎跳峡", "Tiger Leaping Gorge", ["lp"], []),
    (
        "丽江",
        "丽江古城",
        "Lijiang Old Town",
        ["lp"],
        ["古城区丽江古城景区", "大研古城"],
    ),
    ("哈尔滨", "哈尔滨冰雪大世界", "Harbin Ice and Snow World", ["lp"], ["冰雪大世界"]),
    ("哈尔滨", "圣索菲亚大教堂", "Saint Sophia Cathedral", ["lp"], ["圣索菲亚教堂"]),
    ("厦门", "鼓浪屿", "Gulangyu Island", ["lp"], ["思明区鼓浪屿风景名胜区"]),
    (
        "厦门",
        "福建土楼（永定高北土楼群）",
        "Fujian Tulou (Gaobei Cluster)",
        ["lp"],
        ["福建土楼", "永定土楼", "高北土楼群"],
    ),
    (
        "黄山",
        "黄山风景区",
        "Yellow Mountains (Huangshan)",
        ["ta", "viator"],
        ["黄山区黄山风景区"],
    ),
    ("拉萨", "布达拉宫", "Potala Palace", ["ta", "viator"], ["城关区布达拉宫景区"]),
    ("香港", "太平山顶", "Victoria Peak (The Peak)", ["ta"], ["太平山"]),
]


def _same_city(row_city: str | None, want: str) -> bool:
    rc = (row_city or "").strip()
    return bool(rc) and (want in rc or rc in want)


def apply_picks(session, *, dry_run: bool = False) -> dict:
    """对全部 INTL_PICKS 做幂等 merge/insert，返回统计。"""
    rows = session.query(Poi).all()
    stats = {"insert": 0, "merge": 0, "skip": 0, "errors": 0}
    for city, name_zh, name_en, sites, aliases in _INTL_PICKS:
        try:
            names = {name_zh, *aliases}
            hit = next(
                (r for r in rows if _same_city(r.city, city) and r.name_zh in names),
                None,
            )
            add_tags = ["intl", *sites]
            if hit is not None:
                merged = [t for t in add_tags if t not in (hit.tags or [])]
                if not merged:
                    stats["skip"] += 1
                    continue
                hit.tags = [*(hit.tags or []), *merged]
                if hit.tags_source is None:
                    hit.tags_source = "intl"
                stats["merge"] += 1
                logger.info(
                    "intl merge %s/%s onto source=%s tags+=%s",
                    city,
                    hit.name_zh,
                    hit.source,
                    merged,
                )
            else:
                row = Poi(
                    id=uuid.uuid4(),
                    source="intl",
                    source_poi_id=f"intl:{city}:{name_zh}"[:100],
                    city=city,
                    name_zh=name_zh,
                    name_en=name_en,
                    category="attraction",
                    status="active",
                    tags=add_tags,
                    tags_source="intl",
                )
                session.add(row)
                rows.append(row)  # 同批去重：别名重复项不会二次插入
                stats["insert"] += 1
                logger.info("intl insert %s/%s sites=%s", city, name_zh, sites)
        except Exception:
            stats["errors"] += 1
            logger.exception("intl pick failed: %s/%s", city, name_zh)
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="intl 荐点种子导入（幂等）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from app.db import get_session_factory

    with get_session_factory()() as session:
        stats = apply_picks(session, dry_run=args.dry_run)
    print(json.dumps(stats, ensure_ascii=True))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
