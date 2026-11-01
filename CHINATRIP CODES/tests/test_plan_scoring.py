# -*- coding: utf-8 -*-
"""S1 打分器单测（设计稿 §7-S1）：各分量独立可算 + 好计划零分。"""

from datetime import time

from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.scoring import plan_score, score_payload


def _v(
    item_id, *, dur=60, day=1, cat="attraction", city="西安", start=None, end=None, **kw
):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city=city,
        day=day,
        category=cat,
        duration_minutes=dur,
        start_time=start,
        end_time=end,
        **kw,
    )


def _lunch(day=1, start=None):
    return VisitItem(
        item_id=f"lunch-{day}",
        name="午饭（自由安排）",
        category="food",
        city="西安",
        day=day,
        start_time=start or time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        pinned=True,
        soft_pin=True,
    )


def _plan(days):
    return ItineraryPlan(itinerary_id="it1", cities=["西安"], days=days)


def _good_day():
    return DayPlan(
        day=1,
        base_city="西安",
        items=[
            _v("a", dur=120, start=time(9, 0), end=time(11, 0)),
            _lunch(),
            _v("b", dur=60, start=time(14, 0), end=time(15, 0)),
        ],
    )


def test_good_plan_scores_zero():
    sc = plan_score(_plan([_good_day()]))
    assert sc.total == 0
    assert sc.ok
    assert sc.summary() == "total=0"


def test_untimed_card_penalized():
    day = _good_day()
    day.items.append(_v("u", dur=80))
    sc = plan_score(_plan([day]))
    assert sc.hard["untimed"] == -100
    assert sc.counts["untimed"] == 1
    assert not sc.ok


def test_blank_morning_penalized():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _lunch(),
            _v("b", dur=60, start=time(14, 0), end=time(15, 0)),
        ],
    )
    sc = plan_score(_plan([day]))
    assert sc.hard["blank_morning"] == -80
    assert sc.counts["blank_morning"] == 1


def test_rain_exposure_weights():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _v("no1", dur=90, start=time(9, 0), end=time(10, 30), rain_ok="no"),
            _v("pa1", dur=60, start=time(11, 0), end=time(12, 0), rain_ok="partial"),
            _v("yes1", dur=60, start=time(14, 0), end=time(15, 0), rain_ok="yes"),
            _v("unk1", dur=60, start=time(15, 30), end=time(16, 30)),
        ],
    )
    rainy = plan_score(_plan([day]), rain_days={"西安": {1}})
    assert rainy.soft["rain_exposed"] == -25  # -15 露天 -10 半露天
    dry = plan_score(_plan([day]))
    assert dry.soft["rain_exposed"] == 0


def test_budget_overflow_is_soft():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _v("big", dur=240, start=time(9, 0), end=time(13, 0)),
            _v("big2", dur=180, start=time(14, 0), end=time(17, 0)),
        ],
    )
    sc = plan_score(_plan([day]))
    assert sc.counts["budget_overflow_days"] == 1  # 420-390=30 溢出
    assert sc.soft["budget_overflow"] == -3
    assert sc.ok  # 预算=偏好：只扣软分


def test_travel_proxy_penalty():
    day = _good_day()
    day.items[0].distance_to_next_km = 65.0
    sc = plan_score(_plan([day]))
    assert sc.soft["travel"] == -2  # round(65)//30


def test_lunch_drift_beyond_grace():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _v("a", dur=120, start=time(9, 0), end=time(11, 0)),
            _lunch(start=time(13, 30)),
            _v("b", dur=60, start=time(15, 0), end=time(16, 0)),
        ],
    )
    sc = plan_score(_plan([day]))
    assert sc.soft["lunch_drift"] == -6  # (90-30)//10
    assert sc.counts["lunch_drift_min"] == 60


def test_overlap_counts_violation():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _v("a", dur=180, start=time(9, 0), end=time(12, 0)),
            _v("b", dur=60, start=time(11, 0), end=time(12, 0)),
        ],
    )
    sc = plan_score(_plan([day]))
    assert sc.counts["overlaps"] == 1
    assert sc.hard["violations"] == -60


def test_entry_cap_exempt_show_only():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _v("late", dur=60, start=time(16, 30), end=time(17, 30)),
            _v(
                "show",
                dur=60,
                cat="entertainment",
                start=time(18, 0),
                end=time(19, 0),
                best_visit_time="show",
            ),
        ],
    )
    sc = plan_score(_plan([day]))
    assert sc.counts["late_entries"] == 1
    assert sc.hard["violations"] == -60


def test_overrun_counts_violation():
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[_v("night", dur=120, start=time(20, 0), end=time(22, 0))],
    )
    sc = plan_score(_plan([day]))
    assert sc.counts["overruns"] == 1
    assert sc.hard["violations"] == -120  # 超窗 + 该条同时吃入场闸


def test_score_payload_roundtrip():
    day = _good_day()
    day.items.append(_v("u", dur=80))
    plan = _plan([day])
    via_obj = plan_score(plan)
    via_json = score_payload(plan.model_dump())
    assert via_json.total == via_obj.total == -100
    assert via_json.counts["untimed"] == 1


def test_day_balance_penalizes_thin_worst_day():
    day1 = DayPlan(
        day=1,
        base_city="西安",
        items=[_v("a", dur=300, start=time(9, 0), end=time(14, 0))],
    )
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[_v("b", dur=60, start=time(9, 0), end=time(10, 0))],
    )
    sc = plan_score(_plan([day1, day2]))
    assert sc.soft["day_balance"] == -4  # (180-60)//30
    assert sc.counts["worst_day_load"] == 60


def test_day_balance_ignores_transfer_days():
    from app.services.itinerary.models import TransferItem

    day1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            TransferItem(
                item_id="t1",
                day=1,
                seq=1,
                from_city="上海",
                to_city="西安",
                mode="flight",
                start_time=time(9, 0),
                end_time=time(12, 0),
            ),
            _v("a", dur=60, start=time(15, 0), end=time(16, 0)),
        ],
    )
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[_v("b", dur=300, start=time(9, 0), end=time(14, 0))],
    )
    sc = plan_score(_plan([day1, day2]))
    assert sc.soft["day_balance"] == 0  # 交通日豁免：仅 day2 参与均衡
    assert sc.counts["worst_day_load"] == -1
