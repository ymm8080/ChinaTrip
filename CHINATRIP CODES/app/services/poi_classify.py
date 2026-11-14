"""POI 确定性分类与时长地板（enrich_heuristics / poi_seed 共用）。

2026-10-25 拍板（用户指令）：新 POI 行插入即分类填列——category /
indoor / rain_ok + suggested_duration_min 地板，duration_source=
'heuristic'；地板是「规划下限」不是事实主张，真值源（ctrip/qunar/
llm_web）可升级覆盖 heuristic 值（duration_upgradable），真值之间
仍只填空、不互覆。

映射原则（宁缺毋滥）：
  * indoor=True 仅限明确室内馆；indoor=False 仅限明确户外；混合体
    （古镇/街区/寺庙群）一律留 None 给未来真数据；
  * rain_ok=True=雨天可游；False=雨天体验受损；拿不准留 None。
"""

from __future__ import annotations

# 受控类别 → (indoor, rain_ok)；不在表内的类别两属性都不碰
_CATEGORY_META: dict[str, tuple[bool | None, bool | None]] = {
    "museum": (True, True),
    "gallery": (True, True),
    "theme_park": (False, False),
    "zoo": (False, False),
    "park": (False, False),
    "garden": (False, None),
    "nature": (False, False),
    "viewpoint": (False, None),
    "attraction": (None, None),
    "temple": (False, None),
    "church": (None, None),
    "castle": (False, None),
    "memorial": (None, None),
    "ruins": (False, None),
    "historic": (None, None),
    "ancient_town": (False, None),
    # 街区漫步（2026-11-07 拍板：宽窄巷子/春熙路/锦里武侯祠=CITYWALK，
    # 同城互为替代一行程一个）：户外为主；雨日软硬语义由规划层按名字判
    "citywalk": (False, None),
    # 茶体验（2026-11-07 拍板：人民公园=茶体验，归 attraction 体验族）：
    # 室内外混合（鹤鸣茶社半露天）indoor 不判；茶桌有檐雨日可坐
    "tea_experience": (None, True),
    # 住宿：名称守卫命中即归此类（2026-10-31），不参与行程规划读取
    "hotel": (True, None),
}

_DURATION_FLOOR: dict[str, int] = {
    "museum": 120,
    "gallery": 60,
    "theme_park": 240,
    "zoo": 180,
    "park": 90,
    "garden": 60,
    "nature": 180,
    "viewpoint": 30,
    "attraction": 90,
    "temple": 60,
    "church": 30,
    "castle": 90,
    "memorial": 60,
    "ruins": 90,
    "historic": 90,
    "ancient_town": 180,
    "citywalk": 120,
    "tea_experience": 60,
}

# 演出/戏班名称标记（2026-11-07 用户指令）：SHOW/ENTERTAINMENT 优先级
# 大于 MUSEUM——名称同时命中演出词与馆词（如 剧社×非遗馆）按演出归
# entertainment，不落 museum。
_SHOW_HINTS = (
    "剧场",
    "剧院",
    "戏院",
    "戏台",
    "戏楼",
    "剧社",
    "梨园",
    "变脸",
    "川剧",
    "相声",
    "演出",
)
#: 场演基准时长（import_shows.SHOW_DURATION_MIN 同值，含入场余量）
_SHOW_DURATION_FLOOR = 80

# 名称关键词 → 判定；顺序即优先级（首个命中即停）
_INDOOR_HINTS = (
    "博物馆",
    "纪念馆",
    "美术馆",
    "科技馆",
    "海洋馆",
    "水族馆",
    "展览馆",
    "陈列馆",
    "天文馆",
    " Planetarium",
    "蜡像馆",
    "规划馆",
    "博物院",
)
_THEME_HINTS = (
    "乐园",
    "游乐园",
    "动物园",
    "野生动物",
    "欢乐谷",
    "方特",
    "水上世界",
    "海洋公园",
    "文旅城",
)
# 风景区类名称标记（2026-10-31 用户指令两档：市区默认 180 / 城市外
# 默认 240）。独立于类别地板：名称命中即在类别地板之上抬到对应档；
# 真值源仍可按 duration_upgradable 升级覆盖。priority 在 heritage 之
# 前——「中山陵风景区」「灵隐飞来峰景区」这类大块头按景区口径，不
# 落 60/90 档。
_SCENIC_MARKS = ("风景名胜区", "旅游景区", "旅游区", "风景区", "景区", "名胜区")
_SCENIC_URBAN_MIN = 180
_SCENIC_SUBURB_MIN = 240

#: 城外行政区/聚落标记——名称或地址命中任一即按城市外档，都不命中
#: 按市区档。零联网口径下的保守判定，漏判（如 长白山景区 名称地址
#: 皆无标记）落市区 180 地板，真值源可升级覆盖。
_SUBURB_MARKS = (
    "县",
    "自治州",
    "旗",
    "盟",
    "镇",
    "乡",
    "村",
    "林场",
    "农场",
    "牧场",
    "水库",
)

# 住宿名称标记（2026-10-31 用户拍板清洗）：名称命中即认定住宿，不再
# 按名称/上游类别归 景点/park——「桔子水晶北京朝阳公园酒店」「南京
# 竹官园宾馆」曾因裸「园」hint 被误归 park 污染公园池。不含「度假
# 村」（温泉/景区度假村常即目的地本身，歧义大不进守卫）。
_ACCOMMODATION_HINTS = (
    "酒店",
    "饭店",
    "宾馆",
    "民宿",
    "公寓",
    "客栈",
    "旅馆",
    "招待所",
    "青旅",
)


def is_accommodation(name: str) -> bool:
    """名称是否命中住宿标记（import_chinatravel 跳过闸 / 分类守卫共用）."""
    return any(h in (name or "") for h in _ACCOMMODATION_HINTS)


_HERITAGE_HINTS = (
    "宫",
    "庙",
    "廟",
    "寺",
    "道观",
    "祠",
    "庵",
    "塔",
    "陵",
    "墓",
    "碑",
    "故居",
    "故里",
    "遗址",
    "遗迹",
    "牌坊",
    "教堂",
    "清真寺",
    "大学",
    "酒庄",
    "温泉",
    "阁",
    "閣",
    "殿",
    "王府",
)
_OUTDOOR_HINTS = (
    "山",
    "峡",
    "谷",
    "岛",
    "湖",
    "海",
    "滩",
    "草原",
    "湿地",
    "花海",
    "漂流",
    "瀑布",
    "森林公园",
    "雪场",
    "滑雪",
    "热雪",
    "雪山",
    "长城",
)
_CAVE_HINTS = ("溶洞", "洞窟", "石窟", "窟")
_PARK_HINTS = ("公园", "园林", "园", "園")

# 茶饮场所名称标记（2026-11-12 类级口径）：语素级判定，任意城市生效
# （成都/杭州/苏州等产茶区通用）——不再靠 (城市,名) 覆盖表逐城点名。
# 只收场所后缀语素（茶馆/茶楼/茶室…）：裸「茶」不收（茶卡盐湖/茶餐厅
# /茶叶博物馆皆含「茶」非茶饮场所）；indoor 不判（露天茶桌常见）、
# rain_ok 同 _CATEGORY_META 的 tea_experience 档（茶桌有檐雨日可坐）、
# 时长地板 60 走 _DURATION_FLOOR。语义 genuinely 歧义的点名（成都人民
# 公园=鹤鸣茶社）仍由 _NAME_CITY_OVERRIDES 管。
_TEA_HINTS = ("茶馆", "茶楼", "茶室", "茶社", "茶寮", "茶轩", "茶艺馆")

# 名字×城市精确覆盖（2026-11-07 用户拍板）：关键词词典是概率推断，个别
# 点位按拍板点名归档，重导入/重建也保持同一口径。键=(城市去「市」后缀,
# 名字原样)——城市限定防同名异地误伤（人民公园全国同名多处，只有成都
# 鹤鸣茶社语义是茶体验；异地人民公园仍走「公园」hint 落 park）。覆盖在
# accommodation 守卫之后、类别表映射之前生效，上游类别照样被压过
# （street 源「武侯祠·锦里」上游 historic 也要落 citywalk）。
_NAME_CITY_OVERRIDES: dict[tuple[str, str], str] = {
    ("成都", "人民公园"): "tea_experience",
    ("成都", "宽窄巷子"): "citywalk",
    ("成都", "春熙路"): "citywalk",
    ("成都", "西蜀第一街牌坊"): "citywalk",
    ("成都", "锦里古街"): "citywalk",
    ("成都", "武侯祠·锦里"): "citywalk",
}


def name_city_override(name: str, city: str | None = None) -> str | None:
    """拍板点名覆盖：返回该 (城市, 名字) 的受控类别；未命中 None。"""
    key = ((city or "").strip().removesuffix("市"), (name or "").strip())
    return _NAME_CITY_OVERRIDES.get(key)


_URBAN_HINTS = (
    "古镇",
    "古街",
    "古城",
    "街区",
    "步行街",
    "老街",
    "街",
    "路",
    "巷",
    "城墙",
    "大道",
    "大桥",
    "广场",
    "游船",
    "码头",
    "夜游",
    "轮渡",
    "村",
    "小火车",
    "游艇",
)  # noqa: E501


def classify(
    name: str,
    category: str | None = None,
    address: str | None = None,
    city: str | None = None,
) -> tuple[str | None, bool | None, bool | None, int | None]:
    """返回 (category, indoor, rain_ok, duration_floor)；拿不准的为 None。

    category 已有则直接按类别表映射属性；category 为空时按名称高置信
    关键词分类（宁缺毋滥，低置信名全部 None）。名称带景区标记时地板
    分两档：名称/地址（address 传入时）命中 _SUBURB_MARKS 为城市外
    240，否则市区 180；seed 骨架阶段无 address，仅按名称判。

    拍板点名覆盖（2026-11-07）：city 传入时 (城市, 名字) 精确命中
    _NAME_CITY_OVERRIDES 即采用覆盖类别——优先于上游 category，但仍在
    住宿守卫之后。

    住宿守卫（2026-10-31）：名称命中住宿词即返回 hotel——优先于一切
    名称推断与上游类别（含公园/广场类上游误标），地板恒 None（住宿
    无游憩时长）。
    """
    if is_accommodation(name):
        return "hotel", True, None, None
    ov = name_city_override(name, city)
    if ov is not None:
        category = ov
    cat = category
    indoor = rain_ok = None
    floor: int | None = None
    if cat in _CATEGORY_META:
        indoor, rain_ok = _CATEGORY_META[cat]
    if indoor is None and cat is None:
        # 高置信演出：名称带戏班/剧种词（优先级大于馆词，2026-11-07）
        if any(h in name for h in _SHOW_HINTS):
            cat, indoor, rain_ok = "entertainment", True, True
            floor = _SHOW_DURATION_FLOOR
        # 茶饮场所（2026-11-12 类级）：优先于馆词——「茶馆」含「馆」，
        # 放馆词之后会误归 museum；茶语义高于公园/街区等弱 hints
        elif any(h in name for h in _TEA_HINTS):
            cat, indoor, rain_ok = "tea_experience", None, True
        # 高置信室内：名称带明确馆字
        elif any(h in name for h in _INDOOR_HINTS):
            cat, indoor, rain_ok = "museum", True, True
        elif any(h in name for h in _THEME_HINTS):
            cat, indoor, rain_ok = "theme_park", False, False
        elif any(h in name for h in _SCENIC_MARKS):
            cat, indoor, rain_ok = "nature", False, False
        elif any(h in name for h in _HERITAGE_HINTS):
            cat, indoor, rain_ok = "attraction", False, None
        elif any(h in name for h in _CAVE_HINTS):
            cat, indoor, rain_ok = "nature", False, True
        elif any(h in name for h in _OUTDOOR_HINTS):
            cat, indoor, rain_ok = "nature", False, False
        elif any(h in name for h in _PARK_HINTS):
            cat, indoor, rain_ok = "park", False, None
        elif any(h in name for h in _URBAN_HINTS):
            cat, indoor, rain_ok = "attraction", False, None
    if floor is None:
        floor = _DURATION_FLOOR.get(cat) if cat is not None else None
    if any(m in name for m in _SCENIC_MARKS):
        text = name + (address or "")
        base = (
            _SCENIC_SUBURB_MIN
            if any(m in text for m in _SUBURB_MARKS)
            else _SCENIC_URBAN_MIN
        )
        if floor is None or floor < base:
            floor = base
    return cat, indoor, rain_ok, floor


def duration_upgradable(row) -> bool:
    """真值时长源（ctrip/qunar/llm_web）可否写入该行。

    2026-10-25 拍板：heuristic 地板质量不高，真值可覆盖（update 优于
    留脏）；已有其它真值源则维持只填空语义，真值之间不互覆。
    """
    if getattr(row, "suggested_duration_min", None) is None:
        return True
    return getattr(row, "duration_source", None) == "heuristic"
