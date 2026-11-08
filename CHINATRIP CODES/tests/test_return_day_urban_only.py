# -*- coding: utf-8 -*-
"""返程日市区圈回归（2026-11-08 拍板「回城当天有多余时间也只排市区内
小点或 CityWalk——最后一天不适合华清宫/兵马俑这类重要或远的地方」）。

「重要」翼（tier≤2/>80min）已由 _edge_blocked/_can_join/_no_return_day
三层布防；本组锚「远」翼（_RETURN_URBAN_KM=15km 市区圈）：

1. 多城口径：远郊轻点（非王牌≤80min——只有「远」翼能拦）不上返程
   日，让位中段天照排；
2. 单城镜像：无城际腿行程末日=返程日（tail_return_days 通道）；
3. 退化软放：两天窗全边日（到达+返程）远郊件照排——排得上优先于
   排得轻；
4. 再平衡镜像：超载分流不把远郊件挪进返程日；
5. 回填镜像：返程日空载回填只收圈内件；
6. 终装镜像：紧簇归位不把远郊件聚进返程宿主日。

坐标口径：西安钟楼 (108.943,34.261) 市区簇；华清宫 (109.212,34.366)
实测 ~27km 出圈；市区小点相互 >1km（不结原子族）、对锚全在 15km 内。
"""

from __future__ import annotations

from app.services.agent.plan import (
    PlanningAgent,
    _reunite_tight_kin,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

_XA = (108.943, 34.261)  # 钟楼（市区簇锚）
_XA2 = (108.937, 34.241)  # 小雁塔 ~2.3km
_XA3 = (108.964, 34.218)  # 大雁塔 ~5.6km
_XA4 = (108.957, 34.285)  # 大明宫 ~2.9km
_HQG = (109.212, 34.366)  # 华清宫 ~27km 出圈
_LISHAN = (109.225, 34.374)  # 骊山（华清宫 ~1.4km，非原子族）
_URBAN = {"钟楼小点", "小雁塔小点", "大雁塔小点", "大明宫小点"}
_FAR_NAMES = {"华清宫远点", "骊山远点"}


def _cand(name, *, minutes=60, loc=None, rating=4.5, cat="sight", tags=None):
    c = {
        "name": name,
        "city": "西安",
        "category": cat,
        "location": loc,
        "rating": rating,
        "rating_count": 100,
    }
    if minutes is not None:
        c["suggested_duration_min"] = minutes
    if tags is not None:
        c["tags"] = tags
    return c


def _pool():
    return [
        _cand("华清宫远点", loc=_HQG),
        _cand("骊山远点", loc=_LISHAN),
        _cand("钟楼小点", loc=_XA),
        _cand("小雁塔小点", loc=_XA2),
        _cand("大雁塔小点", loc=_XA3),
        _cand("大明宫小点", loc=_XA4),
    ]


def _by_day(items: list[dict]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for it in items:
        out.setdefault(it["day"], []).append(it["name"])
    return out


# --- ① 多城口径：远郊轻点不上返程日 ---------------------------------------


def test_far_light_points_avoid_return_day_multi_city():
    """远郊轻点（非王牌、≤80min）此前的所有返程闸都拦不住——只有新的
    市区圈「远」翼能拦。必须让位中段且仍然排上（宁挪勿缺）。"""
    items = PlanningAgent._deterministic_selection(
        _pool(),
        4,
        {"西安": (1, 4)},
        transfer_days={1, 4},
        arrival_days={1},
    )
    days = {it["name"]: it["day"] for it in items}
    for n in _FAR_NAMES:
        assert n in days, f"远郊点「{n}」被整体丢弃——应让位他日而非出局"
        assert days[n] != 4, f"远郊点「{n}」落返程日 day4——市区圈闸失效"


def test_return_day_keeps_urban_only_multi_city():
    items = PlanningAgent._deterministic_selection(
        _pool(),
        4,
        {"西安": (1, 4)},
        transfer_days={1, 4},
        arrival_days={1},
    )
    by_day = _by_day(items)
    assert by_day.get(4), "返程日零参访——市区圈内轻点应保底"
    for n in by_day[4]:
        assert n not in _FAR_NAMES, f"返程日落远郊点「{n}」"


# --- ② 单城镜像：无城际腿行程末日=返程日 -----------------------------------


def test_far_light_points_avoid_tail_day_single_city():
    """单城无城际腿：transfer_days 空、tail_return_days={days} 是唯一的
    返程日信号（生产 caller 单城分支注入）。"""
    items = PlanningAgent._deterministic_selection(
        _pool(),
        4,
        {"西安": (1, 4)},
        transfer_days=set(),
        arrival_days={1},
        tail_return_days={4},
    )
    days = {it["name"]: it["day"] for it in items}
    for n in _FAR_NAMES:
        assert n in days
        assert days[n] != 4, f"单城末日落远郊点「{n}」——tail 镜像失效"


def test_single_city_dict_location_shape_same_gate():
    """dict 形 location（出库形态）与元组形同闸（_cxy 双形解析）。"""
    pool = []
    for c in _pool():
        c = dict(c)
        lon, lat = c["location"]
        c["location"] = {"lon": lon, "lat": lat}
        pool.append(c)
    items = PlanningAgent._deterministic_selection(
        pool,
        4,
        {"西安": (1, 4)},
        transfer_days=set(),
        arrival_days={1},
        tail_return_days={4},
    )
    days = {it["name"]: it["day"] for it in items}
    for n in _FAR_NAMES:
        assert days.get(n) != 4


# --- ③ 退化软放：全边日窗远郊件照排 ----------------------------------------


def test_all_edge_days_far_still_schedules():
    """两天窗全是边日（day1 到达 + day2 返程）无替代日——软闸放行，
    排得上优先于排得轻（软偏好语义不变）。"""
    items = PlanningAgent._deterministic_selection(
        _pool(),
        2,
        {"西安": (1, 2)},
        transfer_days={1, 2},
        arrival_days={1},
    )
    names = {it["name"] for it in items}
    assert "华清宫远点" in names, "全边日窗远郊件被硬拦出局——应软放"


# --- ④ 再平衡镜像 -----------------------------------------------------------


def _spec(name, day, minutes, loc):
    return {
        "name": name,
        "city": "西安",
        "category": "sight",
        "day": day,
        "duration_minutes": minutes,
        "location": {"lon": loc[0], "lat": loc[1]},
    }


def test_rebalance_divert_keeps_far_off_return_day():
    """day2 超载分流：远郊对（≤2km 成组）宁可去到达日 day1 也不落返程
    日 day3——组搬/单飞两路同闸。"""
    picked = [
        _spec("钟楼小点", 1, 60, _XA),
        _spec("华清宫远点", 2, 60, _HQG),
        _spec("骊山远点", 2, 60, _LISHAN),
        _spec("小雁塔小点", 2, 90, _XA2),
        _spec("大雁塔小点", 2, 90, _XA3),
        _spec("大明宫小点", 2, 90, _XA4),
    ]
    out, _notes = PlanningAgent._rebalance_days(
        picked,
        [],
        3,
        {"西安": (1, 3)},
        transfer_days={1, 3},
        arrival_days=set(),
    )
    days = {p["name"]: p["day"] for p in out}
    for n in _FAR_NAMES:
        assert days[n] != 3, f"分流把远郊点「{n}」挪进返程日 day3"


def test_rebalance_backfill_urban_only_on_return_day():
    """返程日空载回填：远郊候选不进 day2（返程日），市区轻点补位。"""
    picked = [
        {
            "name": "系统茶位",
            "city": "西安",
            "category": "food",
            "day": 1,
            "duration_minutes": 210,
            "location": {"lon": _XA[0], "lat": _XA[1]},
        }
    ]
    cands = [
        _cand("华清宫远点", loc={"lon": _HQG[0], "lat": _HQG[1]}, rating=4.7),
        _cand("钟楼小点", loc={"lon": _XA[0], "lat": _XA[1]}, rating=4.7),
    ]
    out, _notes = PlanningAgent._rebalance_days(
        picked,
        cands,
        2,
        {"西安": (1, 2)},
        transfer_days={2},
        arrival_days=set(),
    )
    by_day = _by_day(out)
    assert "华清宫远点" not in by_day.get(2, []), "回填把远郊点补进返程日"
    assert "钟楼小点" in by_day.get(2, []), "返程日空载应由市区轻点补位"


# --- ⑤ 终装镜像：紧簇归位不聚远郊件进返程宿主日 -----------------------------


def _visit(vid, name, day, loc, *, minutes=60):
    return VisitItem(
        item_id=vid,
        name=name,
        city="西安",
        day=day,
        duration_minutes=minutes,
        category="sight",
        location=GeoPoint(lon=loc[0], lat=loc[1]),
    )


def test_reunite_keeps_far_kin_off_return_host_day():
    """骊山已悬返程日、华清宫在其紧簇：归位通道想把它俩聚到 day4 宿主
    ——市区圈闸拦下，改聚 day2（远郊对在非返程日团聚）。"""
    days = [
        DayPlan(day=1, base_city="西安", items=[_visit("v1", "钟楼小点", 1, _XA)]),
        DayPlan(
            day=2,
            base_city="西安",
            items=[
                _visit("v2", "小雁塔小点", 2, _XA2),
                _visit("v3", "华清宫远点", 2, _HQG),
            ],
        ),
        DayPlan(day=3, base_city="西安", items=[_visit("v4", "大雁塔小点", 3, _XA3)]),
        DayPlan(day=4, base_city="西安", items=[_visit("v5", "骊山远点", 4, _LISHAN)]),
    ]
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=days)
    _reunite_tight_kin(plan)
    d4 = [i.name for i in plan.days[3].items]
    assert "华清宫远点" not in d4, "归位把远郊件聚进返程宿主日——闸失效"
    d2 = [i.name for i in plan.days[1].items]
    assert "骊山远点" in d2, "远郊对应改聚非返程日 day2（归位语义保留）"
