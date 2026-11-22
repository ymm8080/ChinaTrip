# -*- coding: utf-8 -*-
"""尾城日降级后回填（2026-11-22 北京 Day8 案）。

事故：北京→成都→重庆→北京 8 天，尾城北京填 2 天。收尾补点往第 8 天塞了
慕田峪长城（离城心 60km，11:38 起），随后时刻链判它排不进 → 卡面变成
``start_time=None`` 的灰卡，出口层再把它剔除进 unplaced（reason=
``untimed_demoted``）。于是第 8 天 13:00–19:00 只剩「自由活动」，而同城
的颐和园/天坛这类近点一个都没顶上（补点已被「已补过」短路口关死）。

口径（2026-11-22 拍板）：降级不能只留痕——撤下灰卡的同一天要按市区圈
（≤_CITY_FILL_KM）重开补点，远郊件不得再进尾城日。
"""

from __future__ import annotations

from datetime import time

from app.services.agent.plan import (
    _demote_untimed_sights,
    _fill_leftover_with_diverse_sights,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    UnplacedCandidate,
    VisitItem,
)

# 城心参照（北京）；颐和园 15km、天坛 5km、慕田峪/八达岭 60km+
_CITY = GeoPoint(lon=116.407, lat=39.904)
_YIHEYUAN = GeoPoint(lon=116.275, lat=39.999)
_TIANTAN = GeoPoint(lon=116.410, lat=39.882)
_MUTIANYU = GeoPoint(lon=116.570, lat=40.432)


def _card(item_id, name, start, end, *, cat="sight", loc=None, city="北京", **kw):
    return VisitItem(
        item_id=item_id,
        name=name,
        city=city,
        day=2,
        category=cat,
        duration_minutes=kw.pop("dur", 60 if start is None else 0),
        location=loc,
        start_time=start,
        end_time=end,
        **kw,
    )


def _tail_day(*, with_untimed_far: bool = True) -> DayPlan:
    """尾城日骨架：晨卡 11:30、午饭 12:00-13:00、晚饭 19:00、夜卡 21:00、
    21:30 返程腿；中间 13:00-19:00 是空档。"""
    items = [
        _card(
            "hotel-morning-d2",
            "🏨 从酒店出发（今日起点）",
            time(11, 30),
            time(11, 30),
            cat="hotel",
        ),
        _card(
            "food-lunch-ph-d2",
            "午饭（自由安排）",
            time(12, 0),
            time(13, 0),
            cat="food",
            dur=60,
        ),
        _card(
            "food-dinner-ph-d2",
            "晚饭（自由安排）",
            time(19, 0),
            time(20, 30),
            cat="food",
            dur=90,
        ),
        _card(
            "hotel-night-d2",
            "🏨 回酒店·夜间休息",
            time(21, 0),
            time(22, 0),
            cat="hotel",
        ),
        TransferItem(
            item_id="t-return",
            day=2,
            seq=1,
            from_city="北京",
            to_city="返程地",
            mode="flight",
            start_time=time(21, 30),
            end_time=time(23, 30),
            duration_minutes=120,
        ),
    ]
    if with_untimed_far:
        # 已被判定排不进时刻的远郊灰卡（降级后仍留在 day.items 里）
        items.append(
            _card(
                "extras-2-慕田峪长城",
                "慕田峪长城",
                None,
                None,
                cat="historic",
                loc=_MUTIANYU,
                dur=200,
            )
        )
    return DayPlan(day=2, base_city="北京", items=items)


def _plan(day: DayPlan) -> ItineraryPlan:
    # 单尾城日夹具：本组用例只验证「降级→市区圈重开补点」，其它天的
    # 补点行为另有 test_leftover_fill 覆盖。
    return ItineraryPlan(
        itinerary_id="t-demoted",
        cities=["北京"],
        days=[day],
    )


def _cand(name, loc, dur, *, cat="sight"):
    return UnplacedCandidate(
        name=name,
        category=cat,
        duration_minutes=dur,
        location=loc,
        city="北京",
        poi_id=name,
    )


def _timed_names(plan: ItineraryPlan) -> list[str]:
    return [
        i.name
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.start_time is not None
    ]


def test_demoted_far_sight_leaves_the_day_and_is_traced():
    """降级灰卡必须从当天撤下、进 unplaced（reason=untimed_demoted）并披露
    ——不能既不算进行程又不留痕。"""
    plan = _plan(_tail_day())
    days, notes = _demote_untimed_sights(plan)
    assert days == [2]
    assert "慕田峪长城" not in [getattr(i, "name", "") for i in plan.days[0].items]
    row = next(u for u in plan.unplaced if u.name == "慕田峪长城")
    assert row.reason == "untimed_demoted"
    assert row.day_hint == 2
    assert any("慕田峪长城" in str(n) for n in notes)


def test_demoted_tail_day_refills_with_city_sight():
    """降级后的空档要按市区圈补回近点（颐和园/天坛），13:00–19:00 不再空。"""
    plan = _plan(_tail_day())
    _demote_untimed_sights(plan)
    bench = [_cand("颐和园", _YIHEYUAN, 150), _cand("天坛公园", _TIANTAN, 90)]
    notes = _fill_leftover_with_diverse_sights(plan, bench=bench, reopen_days={2})
    placed = _timed_names(plan)
    assert "颐和园" in placed or "天坛公园" in placed
    assert notes
    filled = next(
        i
        for i in plan.days[0].items
        if isinstance(i, VisitItem) and i.name in ("颐和园", "天坛公园")
    )
    assert filled.start_time >= time(13, 0)
    assert filled.end_time <= time(19, 0)


def test_refill_day_rejects_far_sight_even_when_pool_only_has_it():
    """重开日只认市区圈：池里只剩远郊件时宁空勿塞（慕田峪/八达岭 60km 照拒）。"""
    plan = _plan(_tail_day())
    _demote_untimed_sights(plan)
    bench = [_cand("八达岭长城", GeoPoint(lon=116.02, lat=40.36), 200)]
    _fill_leftover_with_diverse_sights(plan, bench=bench, reopen_days={2})
    assert "八达岭长城" not in _timed_names(plan)


def test_filled_mark_does_not_block_refill_of_demoted_day():
    """整份行程已有「按类型多样性补了」短路口时，降级日仍要能补——旧口径
    一补过就整份关死，尾城日下午永远空着。"""
    plan = _plan(_tail_day())
    plan.assumptions.append("第2天还有空档，按类型多样性补了「慕田峪长城」（11:38）")
    _demote_untimed_sights(plan)
    bench = [_cand("天坛公园", _TIANTAN, 90)]
    _fill_leftover_with_diverse_sights(plan, bench=bench, reopen_days={2})
    assert "天坛公园" in _timed_names(plan)


def test_refill_is_idempotent():
    """反复开档不越补越多。"""
    plan = _plan(_tail_day())
    _demote_untimed_sights(plan)
    bench = [_cand("天坛公园", _TIANTAN, 90)]
    _fill_leftover_with_diverse_sights(plan, bench=bench, reopen_days={2})
    before = len(_timed_names(plan))
    _fill_leftover_with_diverse_sights(plan, reopen_days={2})
    assert len(_timed_names(plan)) == before
