# -*- coding: utf-8 -*-
"""远郊必去占一天 + 引擎钉住必去的接驳腿 + 重日多类型补位（2026-11-15）。

用户实录（2 天 5 必去：天安门/故宫/天坛/慕田峪/颐和园）：
* day1 颐和园 300 分钟 + 非必去恭王府 120 分钟（同类堆叠）；
* day2 天安门 08:34 散场 → 故宫 09:00（26 分钟，需 30）；
* 故宫 11:00 → 天坛 11:00（0 分钟）；
* 慕田峪被挤到 day2 14:30 下午档。
本文件锁三件事：①引擎钉住的远郊必去也打 remote 标并独占一天；②引擎钉住的
必去在接驳链里可后移（用户手钉不动）；③重日补位只补体验类，不再堆同类观光点。
"""

from datetime import time as _t

from app.services.agent.plan import (
    PlanningAgent,
    _clamp_chain_gaps,
    _mark_remote_visits,
    _separate_remote_must_days,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

TD = (116.41033485880789, 39.91149906588831)  # 天安门广场
GG = (116.40965974331732, 39.92549569079433)  # 故宫博物院
TT = (116.41283971321243, 39.88360247943743)  # 天坛
YHY = (116.27494430074763, 39.99872644169878)  # 颐和园
MTY = (116.55980232499265, 40.426661851582196)  # 慕田峪长城


def _v(item_id, name, *, dur, lon, lat, day=1, **kw):
    base = dict(
        item_id=item_id,
        name=name,
        city="北京",
        day=day,
        duration_minutes=dur,
        category="sight",
        location=GeoPoint(lon=lon, lat=lat),
    )
    base.update(kw)
    return VisitItem(**base)


def _plan(days):
    return ItineraryPlan(
        itinerary_id="it-test",
        cities=["北京"],
        days=days,
        assumptions=[],
    )


def test_engine_pinned_must_keeps_remote_tag():
    # pinned+must 是引擎钉（不是用户手钉）：远郊标必须打上；用户手钉才豁免。
    mt = _v(
        "mt",
        "慕田峪长城",
        dur=180,
        lon=MTY[0],
        lat=MTY[1],
        must=True,
        pinned=True,
        start_time=_t(8, 30),
        end_time=_t(11, 30),
    )
    user = _v(
        "u",
        "古北水镇",
        dur=120,
        lon=MTY[0],
        lat=MTY[1],
        must=False,
        pinned=True,
        start_time=_t(13, 0),
        end_time=_t(15, 0),
    )
    plan = _plan([DayPlan(day=1, base_city="北京", items=[mt, user])])
    assert _mark_remote_visits(plan) == 1
    assert mt.remote is True
    assert user.remote is False


def test_remote_must_gets_its_own_day():
    # day1 颐和园 + 慕田峪：远郊那趟独占一天，城心必去挪到另一天。
    yhy = _v("yhy", "颐和园", dur=300, lon=YHY[0], lat=YHY[1], must=True)
    mt = _v("mt", "慕田峪长城", dur=180, lon=MTY[0], lat=MTY[1], must=True)
    td = _v("td", "天安门广场", dur=90, lon=TD[0], lat=TD[1], must=True, day=2)
    plan = _plan(
        [
            DayPlan(day=1, base_city="北京", items=[yhy, mt]),
            DayPlan(day=2, base_city="北京", items=[td]),
        ]
    )
    _mark_remote_visits(plan)
    notes = _separate_remote_must_days(plan)
    assert notes
    d1 = next(d for d in plan.days if d.day == 1)
    d2 = next(d for d in plan.days if d.day == 2)
    sights_d1 = [v for v in d1.items if v.category not in ("food", "hotel")]
    assert [v.item_id for v in sights_d1] == ["mt"]
    assert any(v.item_id == "yhy" for v in d2.items)
    assert mt.day == 1 and yhy.day == 2


def test_clamp_shifts_engine_pinned_musts_for_legs():
    td = _v(
        "td",
        "天安门广场",
        dur=90,
        lon=TD[0],
        lat=TD[1],
        must=True,
        pinned=True,
        start_time=_t(7, 4),
        end_time=_t(8, 34),
        fixed_sessions=[_t(7, 4)],
        day=2,
    )
    gg = _v(
        "gg",
        "故宫博物院",
        dur=120,
        lon=GG[0],
        lat=GG[1],
        must=True,
        pinned=True,
        start_time=_t(9, 0),
        end_time=_t(11, 0),
        day=2,
    )
    tt = _v(
        "tt",
        "天坛",
        dur=60,
        lon=TT[0],
        lat=TT[1],
        must=True,
        pinned=True,
        start_time=_t(11, 0),
        end_time=_t(12, 0),
        day=2,
    )
    plan = _plan([DayPlan(day=2, base_city="北京", items=[td, gg, tt])])
    _clamp_chain_gaps(plan)
    assert _t(9, 0) < gg.start_time <= _t(9, 34)
    assert tt.start_time >= _t(11, 30)


def test_clamp_never_moves_user_pin():
    td = _v(
        "td",
        "天安门广场",
        dur=90,
        lon=TD[0],
        lat=TD[1],
        must=True,
        pinned=True,
        start_time=_t(7, 4),
        end_time=_t(8, 34),
        day=1,
    )
    user = _v(
        "u",
        "我想九点到这里",
        dur=60,
        lon=GG[0],
        lat=GG[1],
        must=False,
        pinned=True,
        start_time=_t(9, 0),
        end_time=_t(10, 0),
        day=1,
    )
    plan = _plan([DayPlan(day=1, base_city="北京", items=[td, user])])
    _clamp_chain_gaps(plan)
    assert user.start_time == _t(9, 0)


def test_heavy_day_trim_drops_optional_sight_keeps_experience():
    picked = [
        {
            "name": "颐和园",
            "day": 1,
            "category": "park",
            "duration_minutes": 300,
            "must": True,
        },
        {
            "name": "西城区恭王府景区",
            "day": 1,
            "category": "attraction",
            "duration_minutes": 120,
            "must": False,
        },
        {
            "name": "梵高星空艺术馆",
            "day": 1,
            "category": "entertainment",
            "duration_minutes": 90,
            "must": False,
        },
    ]
    kept, dropped = PlanningAgent._trim_optional_sights_on_heavy_days(picked)
    names = {s["name"] for s in kept}
    assert "西城区恭王府景区" not in names
    assert "梵高星空艺术馆" in names
    assert dropped
