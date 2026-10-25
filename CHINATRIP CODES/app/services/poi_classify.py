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
}

_DURATION_FLOOR: dict[str, int] = {
    "museum": 90,
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
}

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
_URBAN_HINTS = (
    "古镇",
    "古街",
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
    name: str, category: str | None = None
) -> tuple[str | None, bool | None, bool | None, int | None]:
    """返回 (category, indoor, rain_ok, duration_floor)；拿不准的为 None。

    category 已有则直接按类别表映射属性；category 为空时按名称高置信
    关键词分类（宁缺毋滥，低置信名全部 None）。
    """
    cat = category
    indoor = rain_ok = None
    if cat in _CATEGORY_META:
        indoor, rain_ok = _CATEGORY_META[cat]
    if indoor is None and cat is None:
        # 高置信室内：名称带明确馆字
        if any(h in name for h in _INDOOR_HINTS):
            cat, indoor, rain_ok = "museum", True, True
        elif any(h in name for h in _THEME_HINTS):
            cat, indoor, rain_ok = "theme_park", False, False
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
    floor = _DURATION_FLOOR.get(cat) if cat is not None else None
    return cat, indoor, rain_ok, floor


def duration_upgradable(row) -> bool:
    """真值时长源（ctrip/qunar/llm_web）可否写入该行。

    2026-10-25 拍板：heuristic 地板质量不高，真值可覆盖（update 优于
    留脏）；已有其它真值源则维持只填空语义，真值之间不互覆。
    """
    if getattr(row, "suggested_duration_min", None) is None:
        return True
    return getattr(row, "duration_source", None) == "heuristic"
