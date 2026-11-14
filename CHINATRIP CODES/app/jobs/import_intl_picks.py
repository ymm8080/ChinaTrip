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

行内动作：库内已有正名/别名行 → 追加 intl+来源 tags，tags_source 写
主站点（2026-10-26 用户指令：source 要明细站点名 tripadvisor/
lonelyplanet 等，不要笼统 intl）。既有行的 source 列保留原值——
enrich_amap_detail 只处理 source='amap' 行、tier 名单互含读
source in (unesco,5a)、refresh 升级键绑定 (source, source_poi_id)，
覆写会断三条活链；明细站点落在 tags（ta/lp/viator）+ tags_source。
查无 → 插入 source=主站点 骨架行（主站点优先级 ta>lp>viator>
curated）；旧版 source='intl' 行重跑时自动升级为明细站点。tags 打标
序统一走 app.services.source_tier.SOURCE_TAG_ORDER（2026-11-03 名录
序：unesco/5a → ta/lp/viator/curated → intl/平台站 → 短视频/小红书
→ street/scenic/4a/3a → 其余垫底；多来源全打）。
tags_source 带权威闸（2026-11-03 铁律「导入不降权威」）：官方名录
归因（mct/mohurd）不被商业站点归因冒充——新归因权威严格低于既有
时保留旧 tags_source，tags 并集照写（闸见 source_tier.tags_source_wins）。
子场所行（如主馆属下的子体验/研学基地类场所行）不碰——正名行
另行插入。他源作业整覆 tags 掉了 intl 标时重跑本作业即修复。

_CURATED_PICKS（2026-11-07 用户点名指令）：用户直接点名的 SITE/RESTRANT
高优先级种子，HIGH PRIORITY = curated 标（名录档 2，与 ta/lp/viator
同梯位，选点 boost 1.5）。行内 category 显式跟行（餐饮行归 food——
10 号 intl_platforms 作业按产品规则排除餐饮，restaurant 种子只能走本
作业）；在库同名行走 merge 不重插（用户「SKIP IF THERE IS」），merge
时既有行类别为空/other 的随种子类别升级（点名即定类，amap 泛类型
不覆写点名知识）。点名对象已在库（amap attraction）→ 种子不收，
自动跳过。

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
from app.services.best_visit import apply_rules
from app.services.source_tier import order_source_tags, tags_source_wins

logger = logging.getLogger(__name__)

# (city, name_zh, name_en, sites, aliases)
# aliases = 等价正名（命中库内既有行时合并标签不重插；新插行随行
# 存入 name_aliases，跨源去重轮据此归并）
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
    # 正名对齐 2026-11 去重轮终态（00cf11c 草堂归一）：正名行
    # museum1 既有正名行（已在库带 curated/intl 标），旧名收 aliases。
    (
        "成都",
        "成都杜甫草堂博物馆",
        "Du Fu Thatched Cottage",
        ["curated"],
        ["杜甫草堂", "成都杜甫草堂"],
    ),
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
    (
        "重庆",
        "磁器口古镇",
        "Ciqikou Ancient Town",
        ["curated"],
        ["磁器口", "重庆磁器口古镇"],
    ),  # 4a 正名合并, 不插重
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
    # 正名对齐 2026-11 去重轮终态（2bcd323 该馆同实体 5 行归一）：正名行
    # 5a「秦始皇帝陵博物院」，旧种子名收进 aliases 走 merge 不重插。
    (
        "西安",
        "秦始皇帝陵博物院",
        "Terracotta Warriors",
        ["ta", "lp"],
        ["秦始皇帝陵博物院（兵马俑）", "秦始皇兵马俑博物馆", "兵马俑"],
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
    # 正名对齐 2026-11 去重轮终态：5a 正名行「七彩丹霞景区」，旧种子名收 aliases。
    (
        "张掖",
        "七彩丹霞景区",
        "Zhangye Rainbow Danxia",
        ["lp"],
        ["张掖七彩丹霞景区", "七彩丹霞", "张掖丹霞"],
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

# (city, name_zh, name_en, sites, aliases, category) —— 用户点名种子，
# 6 元组比 _INTL_PICKS 多收尾 category（餐饮行归 food，见 docstring）。
_CURATED_PICKS: list[tuple[str, str, str, list[str], list[str], str]] = [
    # 2026-11-07 指令：SITE 用户点名商业综合体 HIGH PRIORITY——在库为 amap
    # other 泛类行，走 merge 打标 + other→attraction 升类，不重插。
    (
        "成都",
        "成都环球中心",
        "Chengdu Global Center",
        ["curated"],
        ["环球中心"],
        "attraction",
    ),
    # SPACELAB 失重餐厅（同商场 4F 店，太空轨道传菜汉堡店）——RESTRANT
    # HIGH PRIORITY；名带分店号对齐图商正名，别名保留裸名可继续命中他源行。
    (
        "成都",
        "失重餐厅(环球中心店)",
        "SPACELAB Restaurant (Chengdu Global Center)",
        ["curated"],
        ["失重餐厅", "SPACELAB失重餐厅"],
        "food",
    ),
    # 红鼎宴（宫廷火锅餐秀，Klook/川媒作「红鼎艳」，Tripadvisor 作
    # 红鼎宴/洪鼎宴）——RESTRANT HIGH PRIORITY；正名从用户指令，
    # 异名收进 aliases 供跨源 merge/后续人工并档。
    (
        "成都",
        "红鼎宴",
        "Hongdingyan Imperial Hotpot Dinner Show",
        ["curated"],
        ["红鼎艳", "洪鼎宴"],
        "food",
    ),
    # 蜀宴赋（东郊记忆沉浸式汉唐宋宴秀，午宴/晚宴双场，Klook 139704
    # 在售）——RESTRANT；在库为 amap 空类行，走 merge 点名即定类
    # food + curated 打标（2026-11-07 体验宴会拾取链修复）。
    (
        "成都",
        "蜀宴赋",
        "Shu Yan Fu Immersive Dinner Show",
        ["curated"],
        [],
        "food",
    ),
    # ---------- 2026-11-07 全国体验性宴会普查入库（32 城，多 agent 调研，
    # 订票平台在售页为最高档证据）。DB 直插行由 tmp_unesco/seed_banquet_curated.py
    # 生成（source='curated'，坐标 baidu/geocode/锚点三级），此处种子保底幂等
    # merge（按 city+name_zh 命中已插行→补 en 名/别名，不产生重复行）。
    (
        "北京",
        "白家大院",
        "Bai Jia Da Yuan Royal Mansion Cuisine",
        ["curated"],
        ["白家大王府"],
        "food",
    ),
    (
        "北京",
        "御仙都·皇家菜博物馆",
        "Yuxiandu Royal Cuisine Museum",
        ["curated"],
        ["御仙都", "皇家菜博物馆"],
        "food",
    ),
    (
        "天津",
        "敘宴·王府宴",
        "Xu Yan Royal Mansion Banquet",
        ["curated"],
        ["叙宴·王府宴", "叙宴"],
        "food",
    ),
    (
        "西安",
        "长安十二时辰·唐宴",
        "Tang Banquet at Chang'an 12 Hours",
        ["curated"],
        ["乐宴·盛唐", "唐宴"],
        "food",
    ),
    (
        "西安",
        "御宴宫",
        "Royal Banquet Hall (Tang Paradise)",
        ["curated"],
        [],
        "food",
    ),
    (
        "洛阳",
        "武皇盛宴",
        "Wu Huang Grand Feast",
        ["curated"],
        ["武皇盛宴·老城十字街店", "武皇盛宴·定鼎门店"],
        "food",
    ),
    (
        "开封",
        "清明上河·宋宴",
        "Song Dynasty Banquet at Millennium City Park",
        ["curated"],
        ["孙羊正店"],
        "food",
    ),
    (
        "敦煌",
        "敦煌盛宴大殿",
        "Dunhuang Silk Road Grand Feast",
        ["curated"],
        [],
        "food",
    ),
    (
        "乌鲁木齐",
        "大巴扎宴艺大剧院",
        "Grand Bazaar Banquet & Arts Theatre",
        ["curated"],
        ["丝绸之路千年印象"],
        "food",
    ),
    (
        "呼和浩特",
        "蒙御宴·火锅餐秀",
        "Meng Yu Yan Mongolian Imperial Feast",
        ["curated"],
        ["蒙御宴"],
        "food",
    ),
    (
        "大同",
        "北魏宫宴",
        "Northern Wei Palace Banquet",
        ["curated"],
        ["北魏宫宴·华严寺店"],
        "food",
    ),
    (
        "重庆",
        "庆渝宴",
        "Qing Yu Banquet Palace Show",
        ["curated"],
        ["庆渝宴·洋炮局1862"],
        "food",
    ),
    (
        "重庆",
        "礼宴巴国·巴国礼乐宴",
        "Ba Kingdom Ceremony Banquet",
        ["curated"],
        ["礼宴巴国", "华礼宴"],
        "food",
    ),
    (
        "昆明",
        "觉宴",
        "Jue Banquet Ancient Dian Show",
        ["curated"],
        [],
        "food",
    ),
    (
        "大理",
        "礼颂宴（天憙园）",
        "Li Song Banquet at Tianxi Garden",
        ["curated"],
        ["礼颂宴", "天憙园"],
        "food",
    ),
    (
        "丽江",
        "丽江御宴",
        "Lijiang Royal Banquet",
        ["curated"],
        [],
        "food",
    ),
    (
        "丽江",
        "云上盛宴·长街宴",
        "Yun Shang Chang Jie Banquet",
        ["curated"],
        ["云上盛宴"],
        "food",
    ),
    (
        "贵阳",
        "玲珑宴会",
        "Linglong Banquet",
        ["curated"],
        [],
        "food",
    ),
    (
        "黔东南",
        "苗家长桌宴（西江千户苗寨）",
        "Miao Long Table Banquet (Xijiang)",
        ["curated"],
        ["西江长桌宴", "长桌宴"],
        "food",
    ),
    (
        "桂林",
        "龙脊长桌宴",
        "Longji Long Table Banquet",
        ["curated"],
        [],
        "food",
    ),
    (
        "阳朔",
        "侗王夜宴（天籁·蝴蝶泉）",
        "Dong King Night Banquet (Butterfly Spring)",
        ["curated"],
        ["天籁·蝴蝶泉", "侗苗盛宴"],
        "food",
    ),
    (
        "广州",
        "荣华楼",
        "Ronghua Lou Cantonese Opera Teahouse",
        ["curated"],
        [],
        "food",
    ),
    (
        "深圳",
        "敘宴·长安赋",
        "Xu Yan Chang'an Fu Tang Banquet",
        ["curated"],
        ["叙宴·长安赋", "叙宴"],
        "food",
    ),
    (
        "厦门",
        "黄都礼宴",
        "Huangdu Li Banquet Palace Show",
        ["curated"],
        [],
        "food",
    ),
    (
        "保亭",
        "槟榔谷黎苗长桌宴",
        "Li & Miao Long Table Banquet (Binlang Valley)",
        ["curated"],
        ["槟榔谷长桌宴"],
        "food",
    ),
    (
        "南宁",
        "漾宴邕城1939",
        "Yang Ban Yongcheng 1939",
        ["curated"],
        [],
        "food",
    ),
    (
        "杭州",
        "宫宴·宋韵沉浸式宫廷御宴",
        "Gong Yan Song Dynasty Imperial Banquet",
        ["curated"],
        ["宫宴"],
        "food",
    ),
    (
        "扬州",
        "长乐盐商宴",
        "Changle Salt Merchant Banquet",
        ["curated"],
        ["扬州宫宴", "长乐客栈"],
        "food",
    ),
    (
        "合肥",
        "叙宴·合肥店",
        "Xu Yan Hefei Tang Banquet (Chang'an Fu)",
        ["curated"],
        ["叙宴", "叙宴·长安赋合肥店"],
        "food",
    ),
    (
        "南昌",
        "滕阁宴·千里逢迎",
        "Tengge Banquet",
        ["curated"],
        ["滕阁宴"],
        "food",
    ),
    (
        "张家界",
        "向王盛宴",
        "Xiang Wang Feast",
        ["curated"],
        [],
        "food",
    ),
    (
        "长沙",
        "鱼王传",
        "Yu Wang Chuan",
        ["curated"],
        [],
        "food",
    ),
    # ---------- 第二轮补种（2026-11-07 沪宁苏锡组调研收口 + 厦门闽南大院） ----------
    (
        "南京",
        "六朝沉浸式晚宴",
        "Immersive Six Dynasties Dining & Show Experience",
        ["curated"],
        ["六朝诗宴"],
        "food",
    ),
    (
        "南京",
        "宴天下·宴乐",
        "Yan Tian Xia Yan Le Immersive Banquet",
        ["curated"],
        ["宴天下·宴乐南京首店"],
        "food",
    ),
    (
        "苏州",
        "吴宫御宴",
        "Suzhou Wugong Imperial Banquet Experience",
        ["curated"],
        ["吴宫御宴酒店"],
        "food",
    ),
    (
        "厦门",
        "闽南大院",
        "Minnan Grand Courtyard",
        ["curated"],
        ["臻府闽南大院"],
        "food",
    ),
]


def _same_city(row_city: str | None, want: str) -> bool:
    rc = (row_city or "").strip()
    return bool(rc) and (want in rc or rc in want)


_SITE_SOURCE = {
    "ta": "tripadvisor",
    "lp": "lonelyplanet",
    "viator": "viator",
    "curated": "curated",
}
_SITE_PRIORITY = ("ta", "lp", "viator", "curated")


def _primary_source(sites: list[str]) -> str:
    """多站同荐时 source/tags_source 取主站点（ta > lp > viator >
    curated；用户 2026-10-26 指令：明细站点名，不要笼统 intl）。"""
    for s in _SITE_PRIORITY:
        if s in sites:
            return _SITE_SOURCE[s]
    return "curated"


_order_tags = order_source_tags  # 多来源打标序（source_tier 名录序单一实现）


def apply_picks(session, *, dry_run: bool = False) -> dict:
    """对全部 INTL_PICKS + CURATED_PICKS 做幂等 merge/insert，返回统计。"""
    rows = session.query(Poi).all()
    stats = {"insert": 0, "merge": 0, "skip": 0, "errors": 0}
    seeds: list[tuple[str, str, str, list[str], list[str], str]] = [
        (city, name_zh, name_en, sites, aliases, "attraction")
        for city, name_zh, name_en, sites, aliases in _INTL_PICKS
    ]
    seeds.extend(_CURATED_PICKS)
    for city, name_zh, name_en, sites, aliases, category in seeds:
        try:
            names = {name_zh, *aliases}
            hits = [r for r in rows if _same_city(r.city, city) and r.name_zh in names]
            add_tags = ["intl", *sites]
            primary = _primary_source(sites)
            if hits:
                # 同名孪生行（天坛 amap + 天坛公园 5a 等）全部统一打标
                # ——只标 next() 首行会因行序漂移漏标孪生
                changed = False
                for hit in hits:
                    if hit.source == "intl":
                        # 旧版（2026-10-25）导入行 source='intl' → 升级为
                        # 明细站点名（2026-10-26 用户指令）
                        hit.source = primary
                        hit.source_poi_id = f"{primary}:{city}:{name_zh}"[:100]
                        changed = True
                    if (
                        (hit.category or "") in ("", "other")
                        and category
                        and hit.category != category
                    ):
                        # 点名即定类（2026-11-07）：种子带显式类别时，
                        # 库内空类/amap 泛类 other 行随种子升级（成图商
                        # 泛类型不覆写点名知识）；真名录行类别不碰。
                        hit.category = category
                        changed = True
                        logger.info(
                            "intl category adopt %s/%s -> %s",
                            city,
                            hit.name_zh,
                            category,
                        )
                    merged = [t for t in add_tags if t not in (hit.tags or [])]
                    desired = _order_tags([*(hit.tags or []), *merged])
                    # 异名并回（2026-11-07，同 xhs12 案口径）：种子名集里
                    # hit 未收的等价名（别名行命中正名行时连正名一并收）
                    # 补进 name_aliases——去重轮跨源同名合并靠它。
                    merged_aliases = [
                        a
                        for a in sorted(names - {hit.name_zh})
                        if a not in (hit.name_aliases or [])
                    ]
                    # 归因权威闸（2026-11-03 铁律「导入不降权威」）：官方名录
                    # 归因（mct/mohurd）不被商业站点归因冒充——权威低于既有
                    # 时 tags_source 保留原值，tags 并集照写。
                    source_wins = tags_source_wins(primary, hit.tags_source)
                    if (
                        not merged
                        and not merged_aliases
                        and desired == (hit.tags or [])
                        and (hit.tags_source == primary or not source_wins)
                    ):
                        continue
                    if merged_aliases:
                        hit.name_aliases = [*(hit.name_aliases or []), *merged_aliases]
                    hit.tags = desired
                    if source_wins:
                        hit.tags_source = primary
                    changed = True
                    logger.info(
                        "intl merge %s/%s onto source=%s tags+=%s",
                        city,
                        hit.name_zh,
                        hit.source,
                        merged,
                    )
                stats["merge" if changed else "skip"] += 1
            else:
                # 骨架行插入时就带时段信号（2026-11-01「两江夜游排在白天」
                # 事故：intl 行导入后从未被回填作业覆盖到，best_visit_time
                # 停留在列默认 any，solver 全天窗把夜游排进白天——插入即
                # 打规则层标签（与回填作业同源），不等回填补课。
                slot = apply_rules(name_zh, category)
                row = Poi(
                    id=uuid.uuid4(),
                    source=primary,
                    source_poi_id=f"{primary}:{city}:{name_zh}"[:100],
                    city=city,
                    name_zh=name_zh,
                    name_en=name_en,
                    name_aliases=[a for a in aliases if a] or None,
                    category=category,
                    status="active",
                    tags=_order_tags(add_tags),
                    tags_source=primary,
                    best_visit_time=slot,
                    best_visit_time_source="heuristic" if slot else None,
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
