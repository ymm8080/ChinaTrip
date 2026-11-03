"""同类型兄弟对选一个测试（2026-11-03 拍板「同类型得选一个就好了。比如
大雁塔，小雁塔」）。

大/小 前缀同核心词的两个点（大雁塔/小雁塔、大昭寺/小昭寺）是一次行程
里的同类型二选一：站级判定（_same_visit）收拢 → 行程级 dedupe 只留
一张卡（pinned 防御 > 「大」字号旗舰）；心愿覆盖（_name_dup）刻意
不收（用户点名大雁塔不得被小雁塔冒充）；回填守卫与候选记账同口径。
与秦陵同馆桶（tests/test_plan_dedupe_gate.py）同款分层接线，不动评分器。
"""

from datetime import time

from app.services.agent.plan import (
    _cand_twin,
    _dup_blocks_item,
    _name_dup,
    _same_visit,
    _sibling_core,
    _sibling_dup,
    dedupe_plan_visits,
)
from app.services.itinerary import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.models import GeoPoint

DY_LOC = GeoPoint(lon=108.9640, lat=34.2185)  # 大雁塔
XY_LOC = GeoPoint(lon=108.9437, lat=34.2419)  # 小雁塔（同城 ~3.5km）
FAR_LOC = GeoPoint(lon=116.4000, lat=39.9000)  # 异地 >30km 闸外


def _visit(item_id: str, name: str, **kw) -> VisitItem:
    base = dict(item_id=item_id, name=name, city="西安", day=2)
    base.update(kw)
    return VisitItem(**base)


def _visit_names(plan: ItineraryPlan) -> list[str]:
    return [i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)]


# --- 名字通道 ---------------------------------------------------------------


def test_sibling_dup_name_channel():
    """核心对：大/小 前缀剥除后核心词相等即同类型兄弟；方位词不剥、
    城市短名剥不动、无关对/同内容家族不误收。"""
    assert _sibling_dup("大雁塔", "小雁塔") is True
    assert _sibling_dup("大昭寺", "小昭寺") is True
    assert _sibling_dup("大雁塔", "雁塔") is True  # 单侧剥过也受理（别名行）
    assert _sibling_dup("大雁塔景区", "小雁塔") is True  # norm 已剥景区尾巴
    assert _sibling_dup("西湖", "东湖") is False  # 方位前缀不剥
    assert _sibling_dup("兵马俑", "秦始皇陵") is False
    assert _sibling_dup("大足石刻博物馆", "大足区大足石刻景区") is False
    # 2 字城市名剥完剩 1 字不剥（大理/大同 防线）
    assert _sibling_core("大理") == ("大理", False)
    assert _sibling_dup("大理", "小理") is False


def test_name_dup_excludes_sibling_channel():
    """心愿覆盖防线：_name_dup 不收兄弟对——心愿「大雁塔」不得被已排的
    「小雁塔」冒充覆盖（两个是不同的点，用户点名哪个就排哪个）。"""
    assert _name_dup("大雁塔", "小雁塔") is False


# --- 站级判定（_same_visit）与地理闸 -----------------------------------------


def test_same_visit_sibling_with_geo_gate():
    pagoda = _visit("v1", "大雁塔", category="sight", location=DY_LOC)
    small = _visit("v2", "小雁塔", category="sight", location=XY_LOC)
    assert _same_visit(pagoda, small) is True  # ~3.5km 同城兄弟

    far = _visit("v3", "小雁塔", category="sight", location=FAR_LOC)
    assert _same_visit(pagoda, far) is False  # >30km 闸外

    no_loc = _visit("v4", "小雁塔", category="sight")
    assert _same_visit(pagoda, no_loc) is True  # 缺坐标维持名字判定


def test_food_category_siblings_exempt():
    """品类豁免：餐饮/演出/酒店/交通不参与同类型二选一——大小同名家族
    馆是两家店，各有各的一顿。"""
    big = _visit("v1", "大龙火锅", category="food", location=DY_LOC)
    small = _visit("v2", "小龙火锅", category="food", location=XY_LOC)
    assert _sibling_dup("大龙火锅", "小龙火锅") is True  # 名字层成立
    assert _same_visit(big, small) is False  # 品类豁免拦下


# --- 行程级收口（dedupe_plan_visits 唯一入口） -------------------------------


def test_dedupe_plan_keeps_one_pagoda_flagship():
    """端到端（用户事故形状）：D2 小雁塔 + D4 大雁塔双卡 → 全程只留一张
    ——平手偏好「大」字号旗舰（大雁塔是外国游客认知的那个），即使小雁塔
    先入列；假设区「已合并重复站点」留痕。"""
    plan = ItineraryPlan(
        itinerary_id="it-pagoda",
        cities=["西安"],
        days=[
            DayPlan(
                day=2,
                base_city="西安",
                items=[
                    _visit(
                        "v1",
                        "小雁塔",
                        day=2,
                        category="sight",
                        poi_id="unesco_xy",
                        location=XY_LOC,
                    )
                ],
            ),
            DayPlan(
                day=4,
                base_city="西安",
                items=[
                    _visit(
                        "v2",
                        "大雁塔",
                        day=4,
                        category="sight",
                        poi_id="unesco_dy",
                        location=DY_LOC,
                    )
                ],
            ),
        ],
    )
    dropped = dedupe_plan_visits(plan)
    assert _visit_names(plan) == ["大雁塔"]
    assert dropped == ["小雁塔"]
    assert any("已合并重复站点" in a for a in plan.assumptions)


def test_pinned_sibling_defends():
    """钉住防御（铁律 19 同款）：用户钉了小雁塔（pinned+有时刻），引擎
    池里的大雁塔后到 → 保留小雁塔——用户点名压过旗舰偏好。"""
    plan = ItineraryPlan(
        itinerary_id="it-pin",
        cities=["西安"],
        days=[
            DayPlan(
                day=2,
                base_city="西安",
                items=[
                    _visit(
                        "v1",
                        "小雁塔",
                        day=2,
                        category="sight",
                        poi_id="unesco_xy",
                        pinned=True,
                        start_time=time(9, 0),
                        location=XY_LOC,
                    ),
                    _visit(
                        "v2",
                        "大雁塔",
                        day=2,
                        category="sight",
                        poi_id="unesco_dy",
                        location=DY_LOC,
                    ),
                ],
            ),
        ],
    )
    dedupe_plan_visits(plan)
    assert _visit_names(plan) == ["小雁塔"]


# --- 回填守卫与候选记账 -------------------------------------------------------


def test_dup_blocks_item_sibling_backfill():
    """回填族守卫（晨间保底/借出日回填/干日回填共用）：已排大雁塔时
    小雁塔候选不得回填第二张卡；异地同名兄弟放行；无关候选放行。"""
    scheduled = _visit(
        "v1", "大雁塔", category="sight", poi_id="unesco_dy", location=DY_LOC
    )
    near_cand = {
        "name": "小雁塔",
        "source_poi_id": "unesco_xy",
        "category": "sight",
        "location": {"lon": XY_LOC.lon, "lat": XY_LOC.lat},
    }
    assert _dup_blocks_item(near_cand, scheduled) is True

    far_cand = {
        "name": "小雁塔",
        "source_poi_id": "poi_far",
        "category": "sight",
        "location": {"lon": FAR_LOC.lon, "lat": FAR_LOC.lat},
    }
    assert _dup_blocks_item(far_cand, scheduled) is False

    unrelated = {"name": "西安城墙", "source_poi_id": "5a_1", "category": "sight"}
    assert _dup_blocks_item(unrelated, scheduled) is False


def test_cand_twin_sibling_accounting():
    """候选层孪生记账（选点预算只数孪生胜者，与 _same_visit 同义）：
    兄弟对算孪生；餐饮豁免不算。"""
    dy = {
        "name": "大雁塔",
        "category": "attraction",
        "location": {"lon": DY_LOC.lon, "lat": DY_LOC.lat},
    }
    xy = {
        "name": "小雁塔",
        "category": "attraction",
        "location": {"lon": XY_LOC.lon, "lat": XY_LOC.lat},
    }
    assert _cand_twin(dy, xy) is True

    food_a = {
        "name": "大龙火锅",
        "category": "food",
        "location": {"lon": DY_LOC.lon, "lat": DY_LOC.lat},
    }
    food_b = {
        "name": "小龙火锅",
        "category": "food",
        "location": {"lon": XY_LOC.lon, "lat": XY_LOC.lat},
    }
    assert _cand_twin(food_a, food_b) is False
