# -*- coding: utf-8 -*-
"""2026-11-15 用户四段式排程口径回归（「我反复强调这个逻辑很多日子了」）：

①先按地理分组（≤5km 同片区聚族）→ 多成员族独占一天，单点族先塞非核心天；
②再按重要度+约束强度钉时（远郊大点走早段，本地件就近串联）；
③其余相邻景点交给求解器填空档；
④落不下先删最低优先件（天安门 rank10 给故宫 rank0 让位），餐卡最后才调。

锚点文件，防止再退回「必去灰卡/远郊压到本地件后面/无场次演出被提案」。
"""

from datetime import time

import app.services.agent.plan as P
from app.services.agent.plan import (
    _assign_must_family_days,
    _drop_sessionless_shows,
    _must_visit_families,
    _pin_musts_by_importance,
)
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem

# 北京实测坐标（引擎 haversine 口径）
TIANANMEN = (116.3974, 39.9087)
GUGONG = (116.3972, 39.9163)
TIANTAN = (116.4107, 39.8822)
YIHEYUAN = (116.2755, 39.9998)
MUTIANYU = (116.5647, 40.4319)


def _visit(
    item_id,
    name,
    *,
    dur,
    day=1,
    cat="temple",
    start=None,
    must=True,
    pinned=False,
    tier=1,
    rank=0,
    loc=None,
    hours=None,
) -> VisitItem:
    end = None
    if start is not None:
        m = start.hour * 60 + start.minute + dur
        end = time(m // 60 % 24, m % 60)
    return VisitItem(
        item_id=item_id,
        name=name,
        category=cat,
        city="北京",
        day=day,
        start_time=start,
        end_time=end,
        duration_minutes=dur,
        must=must,
        pinned=pinned,
        tier=tier,
        site_rank=rank,
        location=GeoPoint(lon=loc[0], lat=loc[1]) if loc else None,
        opening_hours=hours,
    )


def _plan(days: list[DayPlan]) -> ItineraryPlan:
    return ItineraryPlan(itinerary_id="it-test", cities=["北京"], days=days)


def _beijing_two_days() -> ItineraryPlan:
    d1 = DayPlan(
        base_city="北京",
        day=1,
        items=[
            _visit(
                "v-tam",
                "天安门广场",
                dur=90,
                day=1,
                rank=10,
                loc=TIANANMEN,
                start=time(8, 30),
                pinned=True,
                hours="08:30-16:30",
            ),
            _visit(
                "v-gg",
                "故宫博物院",
                dur=120,
                day=1,
                rank=0,
                loc=GUGONG,
                hours="08:30-17:00",
            ),
            _visit(
                "v-mty",
                "慕田峪长城",
                dur=180,
                day=1,
                rank=0,
                loc=MUTIANYU,
                start=time(12, 0),
                pinned=True,
                cat="nature",
                hours="07:30-18:30（18:00 停止入园）",
            ),
        ],
    )
    d2 = DayPlan(
        base_city="北京",
        day=2,
        items=[
            _visit(
                "v-yhy",
                "颐和园",
                dur=90,
                day=2,
                rank=0,
                loc=YIHEYUAN,
                start=time(9, 0),
                pinned=True,
                hours="06:30-18:00",
            ),
            _visit(
                "v-tt",
                "天坛",
                dur=60,
                day=2,
                rank=0,
                loc=TIANTAN,
                hours="06:00-21:00",
            ),
        ],
    )
    return _plan([d1, d2])


def _timed(plan, name):
    for d in plan.days:
        for i in d.items:
            if isinstance(i, VisitItem) and i.name == name:
                return d, i
    raise AssertionError(f"{name} not in plan")


def test_families_group_by_five_km():
    plan = _beijing_two_days()
    fams = _must_visit_families(plan)
    names = sorted(tuple(sorted(v.name for v in f)) for f in fams)
    assert ("慕田峪长城",) in names
    flat = [n for tup in names for n in tup]
    assert "天安门广场" in flat and "故宫博物院" in flat


def test_downtown_family_takes_one_day_remote_goes_to_the_other():
    plan = _beijing_two_days()
    _assign_must_family_days(plan)
    day_of = {}
    for d in plan.days:
        for i in d.items:
            if isinstance(i, VisitItem) and i.must:
                day_of[i.name] = d.day
    assert day_of["天安门广场"] == day_of["故宫博物院"] == day_of["天坛"]
    assert day_of["慕田峪长城"] != day_of["天安门广场"]
    assert day_of["颐和园"] == day_of["慕田峪长城"]


def test_remote_sight_is_pinned_before_local_in_the_same_day():
    plan = _beijing_two_days()
    _assign_must_family_days(plan)
    _pin_musts_by_importance(plan)
    _, mty = _timed(plan, "慕田峪长城")
    _, yhy = _timed(plan, "颐和园")
    assert mty.start_time is not None and yhy.start_time is not None
    assert mty.start_time < yhy.start_time  # 远郊大点走早段
    assert mty.pinned is True


def test_fillers_yield_before_a_must_visit():
    """当日档位被凑数件占满时，先删凑数件给必去腾位（用户拍板第④步）。"""
    d1 = DayPlan(
        base_city="北京",
        day=1,
        items=[
            _visit(
                "v-tam",
                "天安门广场",
                dur=90,
                day=1,
                rank=10,
                loc=TIANANMEN,
                start=time(8, 30),
                pinned=True,
                hours="08:30-16:30",
            ),
            _visit(
                "v-gg",
                "故宫博物院",
                dur=180,
                day=1,
                rank=0,
                loc=GUGONG,
                must=True,
            ),
            _visit(
                "v-filler",
                "钟鼓楼",
                dur=120,
                day=1,
                rank=40,
                loc=(116.39, 39.94),
                start=time(12, 0),
                hours="09:00-17:00",
                must=False,
            ),
            _visit(
                "v-blocker",
                "恭王府",
                dur=210,
                day=1,
                rank=45,
                loc=(116.38, 39.93),
                start=time(14, 30),
                hours="08:00-17:00",
                must=False,
            ),
            _visit(
                "v-hotel",
                "🏨 回酒店·夜间休息",
                dur=60,
                day=1,
                cat="hotel",
                start=time(20, 30),
                must=False,
                loc=(116.40, 39.91),
            ),
        ],
    )
    plan = _plan([d1])
    _pin_musts_by_importance(plan)
    _, gg = _timed(plan, "故宫博物院")
    assert gg.start_time is not None
    assert gg.pinned is True
    dropped = {u.name: u.reason for u in plan.unplaced}
    assert "恭王府" in dropped  # 最弱凑数件（rank45）先让位
    assert dropped["恭王府"] == "yield_must"
    assert "钟鼓楼" not in dropped  # 让出 210 分钟就够，不再多删


def test_priority_ladder_decides_who_yields():
    """保留最高优先、删最低优先：天安门 rank10 给故宫 rank0 让位。"""
    gg = _visit("v-gg", "故宫博物院", dur=180, rank=0, loc=GUGONG)
    tam = _visit("v-tam", "天安门广场", dur=90, rank=10, loc=TIANANMEN)
    filler = _visit("v-x", "钟鼓楼", dur=60, rank=40, loc=(116.39, 39.94), must=False)
    assert P._must_yield_ok(tam, gg) is True  # 弱必去让强必去
    assert P._must_yield_ok(gg, tam) is False  # 强必去不让弱必去
    assert P._must_yield_ok(filler, gg) is True  # 凑数件最弱
    hotel = _visit("v-h", "🏨 回酒店", dur=60, cat="hotel", must=False, loc=GUGONG)
    assert P._must_yield_ok(hotel, gg) is False  # 酒店卡本通道不碰
    created = _visit("v-c", "手建点", dur=60, must=False, loc=GUGONG)
    created.created = True
    assert P._must_yield_ok(created, gg) is False  # 手建件永不动


def test_sessionless_show_is_dropped_with_disclosure():
    d1 = DayPlan(
        base_city="北京",
        day=1,
        items=[
            _visit(
                "v-ncpa",
                "国家大剧院",
                dur=90,
                day=1,
                cat="entertainment",
                must=False,
                tier=6,
                rank=40,
                loc=(116.383, 39.903),
                hours="场次随排期（档期制，以当日公告为准）",
            ),
            _visit(
                "v-show",
                "蜀风雅韵",
                dur=90,
                day=1,
                cat="entertainment",
                must=False,
                tier=3,
                rank=20,
                loc=(116.40, 39.92),
                hours="19:30-21:00",
            ),
        ],
    )
    plan = _plan([d1])
    notes = _drop_sessionless_shows(plan)
    names = [i.name for d in plan.days for i in d.items]
    assert "国家大剧院" not in names
    assert "蜀风雅韵" in names  # 有具体时段照排
    assert any("国家大剧院" in str(n) for n in notes)
    assert any(u.name == "国家大剧院" for u in plan.unplaced)


def test_assignment_is_idempotent():
    plan = _beijing_two_days()
    _assign_must_family_days(plan)
    snapshot = sorted(
        (d.day, i.name) for d in plan.days for i in d.items if isinstance(i, VisitItem)
    )
    _assign_must_family_days(plan)
    again = sorted(
        (d.day, i.name) for d in plan.days for i in d.items if isinstance(i, VisitItem)
    )
    assert snapshot == again


def test_usable_day_capacity_constant_matches_day_window():
    # 08:30–21:30 扣两餐 150 与酒店卡 60
    assert P._MUST_DAY_USABLE_MIN == (1290 - 510) - 150 - 60
