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


def test_families_group_by_five_km_three_families():
    """5km 单链聚族：市区三件套 / 颐和园 / 慕田峪 三族（用户 2026-11-15 拍板）。"""
    plan = _beijing_two_days()
    fams = _must_visit_families(plan)
    names = [tuple(sorted(v.name for v in f)) for f in fams]
    city = next(n for n in names if "天安门广场" in n)
    assert set(city) == {"天安门广场", "故宫博物院", "天坛"}
    assert ("颐和园",) in names
    assert ("慕田峪长城",) in names


def test_remote_sight_gets_its_own_day_others_join_the_city_cluster():
    """市区三件套独占一天；颐和园按距离并入同一天；慕田峪单独一天且宽松。"""
    plan = _beijing_two_days()
    _assign_must_family_days(plan)
    day_of = {}
    for d in plan.days:
        for i in d.items:
            if isinstance(i, VisitItem) and i.must:
                day_of[i.name] = d.day
    assert day_of["天安门广场"] == day_of["故宫博物院"] == day_of["天坛"]
    assert day_of["颐和园"] == day_of["天安门广场"]  # 离市区族 14km，比 53km 外顺路
    assert day_of["慕田峪长城"] != day_of["天安门广场"]


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

def test_meal_card_yields_before_the_sight_when_day_is_impossible():
    """整日只剩饭点那一格时，宁可动餐卡（必去压到饭点，餐卡随后改时刻/缩
    时长），也不缩景点时长、不删景点（用户 2026-11-15「整日完全无法放下
    景点族，可以调整餐卡的开始时间，长短的调整」）。"""
    d1 = DayPlan(
        base_city="北京",
        day=1,
        items=[
            _visit("v-gg", "故宫博物院", dur=60, day=1, rank=0, loc=GUGONG),
            _visit(
                "v-b1",
                "国家博物馆",
                dur=150,
                day=1,
                rank=50,
                loc=GUGONG,
                start=time(9, 0),
                must=False,
                pinned=True,
                hours="09:00-17:00",
            ),
            _visit(
                "v-b2",
                "首都博物馆",
                dur=480,
                day=1,
                rank=51,
                loc=GUGONG,
                start=time(13, 30),
                must=False,
                pinned=True,
                hours="09:00-17:00",
            ),
        ],
    )
    plan = _plan([d1])
    _pin_musts_by_importance(plan)
    _, gg = _timed(plan, "故宫博物院")
    assert gg.start_time is not None
    assert gg.start_time.hour == 12  # 压进午饭档，餐卡让位
    assert gg.duration_minutes == 60  # 景点时长不缩
    assert not plan.unplaced  # 没删任何景点


def test_sight_duration_and_day_start_are_never_shrunk():
    """必去时长与 08:30 日始是本通道的固定输入，不会为塞下而改。"""
    assert not hasattr(P, "_must_pin_attempts")
    d1 = DayPlan(
        base_city="北京",
        day=1,
        items=[
            _visit("v-gg", "故宫博物院", dur=150, day=1, rank=0, loc=GUGONG),
            _visit(
                "v-b1",
                "国家博物馆",
                dur=600,
                day=1,
                rank=50,
                loc=GUGONG,
                start=time(9, 0),
                must=False,
                pinned=True,
                hours="09:00-17:00",
            ),
        ],
    )
    plan = _plan([d1])
    _pin_musts_by_importance(plan)
    _, gg = _timed(plan, "故宫博物院")
    assert gg.duration_minutes == 150
    if gg.start_time is not None:
        assert gg.start_time.hour * 60 + gg.start_time.minute >= P.DAY_START_MINUTES


def test_weather_day_penalty_ladder_matches_user_ruling():
    """不下雨工作日(0) < 下雨工作日(室内 60) < 不下雨周末(90) < 下雨周末。"""
    plan = _beijing_two_days()
    plan.start_date = "2026-11-16"  # 周一
    outdoor = [
        _visit("o1", "慕田峪长城", dur=180, rank=0, loc=MUTIANYU, cat="nature"),
        _visit("o2", "司马台长城", dur=180, rank=1, loc=MUTIANYU, cat="nature"),
    ]
    indoor = [
        _visit("i1", "故宫博物院", dur=120, rank=0, loc=GUGONG, cat="museum"),
        _visit("i2", "国家博物馆", dur=120, rank=1, loc=GUGONG, cat="museum"),
    ]
    dry_weekday = P._must_weather_day_penalty(plan, outdoor, 3, None)  # 周三
    rainy_weekday_indoor = P._must_weather_day_penalty(
        plan, indoor, 3, {"北京": {3}}
    )
    dry_weekend = P._must_weather_day_penalty(plan, outdoor, 6, None)  # 周六
    rainy_weekend = P._must_weather_day_penalty(plan, outdoor, 6, {"北京": {6}})
    assert dry_weekday == 0
    assert 0 < rainy_weekday_indoor < dry_weekend
    assert dry_weekend < rainy_weekend


def test_remote_outdoor_family_avoids_the_rainy_day():
    """雨天在第一天时，远郊露天族让给室内的，自己排到不下雨的那天。"""
    d1 = DayPlan(
        base_city="北京",
        day=1,
        items=[
            _visit(
                "v-mty", "慕田峪长城", dur=180, day=1, rank=0, loc=MUTIANYU,
                cat="nature",
            ),
        ],
    )
    d2 = DayPlan(
        base_city="北京",
        day=2,
        items=[
            _visit("v-yhy", "颐和园", dur=90, day=2, rank=0, loc=YIHEYUAN),
        ],
    )
    plan = _plan([d1, d2])
    plan.start_date = "2026-11-16"  # 周一 / 周二
    _assign_must_family_days(plan, rain_days={"北京": {1}})
    day_of = {
        i.name: d.day
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.must
    }
    assert day_of["慕田峪长城"] == 2  # 露天远郊避开雨天
    assert day_of["颐和园"] == 1  # 室内的可以接下雨的工作日


def test_meal_card_not_nested_inside_a_two_hour_sight():
    """只有 ≥3 小时的大点才允许「游览途中用餐」吞掉餐卡；2 小时的普通景点
    必须把景点顺延到餐后（否则就是双订）。"""
    lunch = VisitItem(
        item_id=P.LUNCH_PLACEHOLDER_ID_PREFIX + "d1",
        name="午饭（自由安排）",
        category="food",
        city="北京",
        day=1,
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
    )
    short_site = _visit(
        "s2h", "恭王府", dur=120, must=False, loc=GUGONG,
        start=time(11, 30),
    )
    big_site = _visit(
        "s3h", "慕田峪长城", dur=180, must=False, loc=GUGONG,
        start=time(11, 30), cat="nature",
    )
    day_short = DayPlan(base_city="北京", day=1, items=[lunch, short_site])
    assert P._meal_nesting_host(day_short, lunch, 12 * 60, 60) is None
    day_big = DayPlan(base_city="北京", day=1, items=[lunch, big_site])
    assert P._meal_nesting_host(day_big, lunch, 12 * 60, 60) is big_site


def test_remote_family_prefers_a_relaxed_day():
    """远郊族落在「已经很挤」的天要记罚时（宽松优先，不硬塞）。"""
    plan = _beijing_two_days()
    plan.start_date = "2026-11-16"
    remote = [
        _visit("r1", "慕田峪长城", dur=180, rank=0, loc=MUTIANYU, cat="nature"),
    ]
    assert P._family_is_remote(remote, plan) is True
    assert P._MUST_REMOTE_CROWD_PENALTY > 0
