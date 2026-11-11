# -*- coding: utf-8 -*-
"""看熊猫顺路换苑闸锚（2026-11-11 拍板「雨天默认繁育研究基地；非雨天默认
繁育基地，除非那天安排了都江堰，就顺路逛都江堰熊猫馆」）：替代组正主
（基地）已排、同城腿已有含都江堰/青城山的干日 → 看熊猫件改绑都江堰中华
大熊猫苑并挪到该日。

闸口径（类级）：
① 显式点名不动——心愿词自带站点词素（基地/谷/苑/乐园）全程跳过；
② 雨日不动——目标日落雨保留基地（雨天看熊猫走基地室内展区口径）；
③ 无都江堰日/候选池无苑行/苑行无坐标 → 宁缺勿滥不动；
④ 目标日 4/日帽与 480min 账先算，trial 换绑挪日重排后 validate 无
   error 才接受；
⑤ 换绑保留 item_id/pinned/must（心愿身份不随选址变）。
"""

from __future__ import annotations

from datetime import time

from app.services.agent.plan import _panda_waypoint_pass
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

_CITY = "成都"
_QINGCHENG = GeoPoint(lat=30.90, lon=103.57)
_YARD = GeoPoint(lat=30.92, lon=103.62)
_BASE = GeoPoint(lat=30.73, lon=104.15)
_CENTER = GeoPoint(lat=30.66, lon=104.06)

_YARD_CAND = {
    "name": "都江堰中华大熊猫苑(原熊猫乐园)",
    "city": _CITY,
    "source_poi_id": "B-PANDA-YARD",
    "category": "theme_park",
    "location": {"lon": _YARD.lon, "lat": _YARD.lat},
    "rain_ok": "partial",
    "source": "4a",
    "suggested_duration_min": 180,
}


def _v(
    item_id: str,
    name: str,
    day: int,
    *,
    loc: GeoPoint | None = None,
    cat: str = "attraction",
    dur: int = 120,
    st: time | None = None,
    en: time | None = None,
    pinned: bool = False,
    must: bool = False,
) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=name,
        city=_CITY,
        day=day,
        category=cat,
        location=loc,
        duration_minutes=dur,
        start_time=st,
        end_time=en,
        pinned=pinned,
        must=must,
    )


def _plan_with_dujianyan_day() -> ItineraryPlan:
    """Day1=青城山（都江堰日），Day2=基地正主（心愿钉选）。"""
    return ItineraryPlan(
        itinerary_id="it-test",
        cities=[_CITY],
        start_date="2026-11-20",
        days=[
            DayPlan(
                day=1,
                base_city=_CITY,
                items=[
                    _v("qc", "青城山", 1, loc=_QINGCHENG, dur=240),
                    _v(
                        "d1lunch",
                        "午饭（自由安排）",
                        1,
                        cat="food",
                        st=time(12, 0),
                        en=time(13, 30),
                    ),
                ],
            ),
            DayPlan(
                day=2,
                base_city=_CITY,
                items=[
                    _v(
                        "panda",
                        "成都大熊猫繁育研究基地",
                        2,
                        loc=_BASE,
                        dur=180,
                        pinned=True,
                        must=True,
                    ),
                    _v("kx", "宽窄巷子", 2, loc=_CENTER, dur=90),
                    _v(
                        "d2lunch",
                        "午饭（自由安排）",
                        2,
                        cat="food",
                        st=time(12, 0),
                        en=time(13, 30),
                    ),
                ],
            ),
        ],
    )


def _cands() -> dict[str, dict]:
    return {_YARD_CAND["name"]: dict(_YARD_CAND)}


def test_moves_base_to_yuan_on_dry_dujianyan_day():
    plan = _plan_with_dujianyan_day()
    notes = _panda_waypoint_pass(plan, _cands(), {}, "2026-11-20")
    assert notes, "顺路换苑应留披露"
    panda = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.item_id == "panda"
    )
    assert panda.name == _YARD_CAND["name"]
    assert panda.day == 1
    assert panda.location == _YARD
    assert panda.poi_id == "B-PANDA-YARD"
    assert panda.pinned and panda.must  # 身份不随选址变
    day1 = next(d for d in plan.days if d.day == 1)
    assert all(
        not (isinstance(i, VisitItem) and i.item_id == "panda")
        for d in plan.days
        if d.day != 1
        for i in d.items
    )
    assert "青城山" in next(i.name for i in day1.items if isinstance(i, VisitItem))


def test_rainy_dujianyan_day_keeps_base():
    plan = _plan_with_dujianyan_day()
    notes = _panda_waypoint_pass(plan, _cands(), {_CITY: {1}}, "2026-11-20")
    assert not notes
    panda = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.item_id == "panda"
    )
    assert panda.name == "成都大熊猫繁育研究基地"
    assert panda.day == 2


def test_explicit_site_wish_skips():
    plan = _plan_with_dujianyan_day()
    notes = _panda_waypoint_pass(
        plan,
        _cands(),
        {},
        "2026-11-20",
        wish_words={"想去熊猫基地玩"},
    )
    assert not notes
    panda = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.item_id == "panda"
    )
    assert panda.day == 2


def test_generic_panda_wish_moves():
    plan = _plan_with_dujianyan_day()
    notes = _panda_waypoint_pass(
        plan, _cands(), {}, "2026-11-20", wish_words={"想看大熊猫"}
    )
    assert notes
    panda = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.item_id == "panda"
    )
    assert panda.day == 1


def test_no_dujianyan_day_noop():
    plan = _plan_with_dujianyan_day()
    # 把青城山改名成非都江堰点
    for i in plan.days[0].items:
        if isinstance(i, VisitItem) and i.name == "青城山":
            i.name = "人民公园"
    notes = _panda_waypoint_pass(plan, _cands(), {}, "2026-11-20")
    assert not notes


def test_target_absent_from_pool_noop():
    plan = _plan_with_dujianyan_day()
    notes = _panda_waypoint_pass(plan, {}, {}, "2026-11-20")
    assert not notes


def test_capacity_gate_rejects_full_day():
    plan = _plan_with_dujianyan_day()
    day1 = plan.days[0]
    for k in range(3):
        day1.items.insert(
            0,
            _v(f"filler{k}", f"填充点{k}", 1, loc=_CENTER, dur=60),
        )
    notes = _panda_waypoint_pass(plan, _cands(), {}, "2026-11-20")
    assert not notes
    panda = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.item_id == "panda"
    )
    assert panda.day == 2


def test_target_without_coordinates_noop():
    plan = _plan_with_dujianyan_day()
    bad = {k: dict(v) for k, v in _cands().items()}
    bad[_YARD_CAND["name"]]["location"] = None
    notes = _panda_waypoint_pass(plan, bad, {}, "2026-11-20")
    assert not notes
