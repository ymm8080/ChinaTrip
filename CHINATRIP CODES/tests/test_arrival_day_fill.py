# -*- coding: utf-8 -*-
"""到达日补位（2026-11-13 六拍：用户报「到达日整天没有安排」）。

两条修正：
① 餐卡：转场日不再整日豁免——`_ensure_meal_cards` 按 fixed 窗（落地 +150 /
   发车 −90）找空隙，落地后有空档就补晚餐卡，落不进才跳过并披露。
② 空到达日：`_endpoint_day_light_sweep` 的 ② 留白前补一段「城市漫步（自由
   安排）」占位卡（锚=酒店，落地后到夜卡之间 ≥90 分钟空窗才插），并按合法
   端点内容认它（重跑不补第二张）。
"""

from datetime import time

from app.services.agent.plan import (
    _endpoint_day_light_sweep,
    _retime_meal_placeholders,
    heal_arrival_light,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)

_C0 = GeoPoint(lon=108.9400, lat=34.2600)
_C1 = GeoPoint(lon=108.9410, lat=34.2605)
_C2 = GeoPoint(lon=108.9420, lat=34.2610)


def _transfer(day: int = 1, *, start=time(9, 0), end=time(12, 0)) -> TransferItem:
    return TransferItem(
        item_id=f"t-{day}",
        day=day,
        seq=1,
        mode="flight",
        from_city="上海",
        to_city="西安",
        start_time=start,
        end_time=end,
    )


def _hotel(day: int = 1, *, start=time(13, 30), end=time(14, 30)) -> VisitItem:
    return VisitItem(
        item_id=f"h-{day}",
        name="🏨 酒店入住（放行李·休整）",
        city="西安",
        day=day,
        duration_minutes=60,
        category="hotel",
        start_time=start,
        end_time=end,
    )


def _visit(name: str, dur: int, loc: GeoPoint, day: int, **kw) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}-{day}",
        name=name,
        city="西安",
        day=day,
        duration_minutes=dur,
        location=loc,
        **kw,
    )


def _plan(*days: DayPlan) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-arrival-fill", cities=["西安"], days=list(days)
    )


def _day(day: int, *items) -> DayPlan:
    return DayPlan(day=day, base_city="西安", items=list(items))


def test_empty_arrival_day_gets_free_citywalk_placeholder():
    """落地 12:00 + 酒店 13:30-14:30 → 空到达日补一段酒店周边自由漫步。"""
    d1 = _day(1, _transfer(), _hotel())
    d2 = _day(
        2,
        _visit("城件一", 60, _C0, 2, tier=9),
        _visit("城件二", 60, _C1, 2, tier=9),
        _visit("城件三", 60, _C2, 2, tier=9),
    )
    plan = _plan(d1, d2)
    _endpoint_day_light_sweep(plan, frozenset())

    walk = next((i for i in d1.items if i.item_id.startswith("citywalk-ph-d")), None)
    assert walk is not None, "空到达日应补自由漫步占位"
    assert walk.category == "citywalk"
    assert walk.start_time is not None and walk.end_time is not None
    assert walk.start_time >= time(15, 0), "不得压到落地/入住窗口"
    assert any("自由漫步" in str(a) for a in plan.assumptions)


def test_arrival_day_with_street_card_does_not_get_placeholder():
    """到达日已有简单街区卡（合法端点内容）→ 不再补占位。"""
    id = "回民街"
    street = _visit("回民街", 90, _C1, 1, tier=4, category="citywalk")
    d1 = _day(1, _transfer(), _hotel(), street)
    plan = _plan(d1, _day(2, _visit("城件一", 60, _C0, 2, tier=9)))
    _endpoint_day_light_sweep(plan, frozenset())

    assert not any(i.item_id.startswith("citywalk-ph-d") for i in d1.items), id
    assert not any("自由漫步" in str(a) for a in plan.assumptions)


def test_repeated_sweep_does_not_stack_placeholders():
    """重跑清扫不得补第二张（占位卡按合法端点内容认）。"""
    d1 = _day(1, _transfer(), _hotel())
    plan = _plan(d1, _day(2, _visit("城件一", 60, _C0, 2, tier=9)))
    _endpoint_day_light_sweep(plan, frozenset())
    _endpoint_day_light_sweep(plan, frozenset())

    walks = [i for i in d1.items if i.item_id.startswith("citywalk-ph-d")]
    assert len(walks) == 1


def test_transfer_day_gets_dinner_card_when_window_allows():
    """转场日不再整日豁免餐卡：落地 12:00 的到达日应补上晚餐卡。"""
    d1 = _day(1, _transfer(), _hotel())
    plan = _plan(d1)
    _retime_meal_placeholders(plan, ensure_cards=True)

    foods = [i for i in d1.items if getattr(i, "category", "") == "food"]
    assert foods, "到达日应补一张晚餐卡（旧口径转场日整日豁免）"
    dinner = [i for i in foods if "晚饭" in str(i.name)]
    assert dinner, "应是晚餐卡而不是硬塞午餐（落地 12:00 + 150 分钟缓冲）"
    assert dinner[0].start_time is not None
    assert dinner[0].start_time >= time(16, 30)


def test_transfer_day_in_air_all_day_gets_no_meal_card():
    """整天在飞机上（09:00-21:00）→ 餐窗全被占，不硬塞餐卡。"""
    d1 = _day(1, _transfer(start=time(9, 0), end=time(21, 0)))
    plan = _plan(d1)
    _retime_meal_placeholders(plan, ensure_cards=True)

    assert not [i for i in d1.items if getattr(i, "category", "") == "food"]


def test_late_dinner_card_when_evening_blocked_until_2040():
    """「至少晚餐不应该豁免」：晚窗被占到 20:40 也要走迟场补 45 分钟晚卡。"""
    # _day_fixed_windows 对已排块前后各留 30 分钟缓冲：16:40-20:15 占成
    # 16:10-20:45，常窗（≤20:30 起、≥45 分钟）全撞窗，只有迟场放得下。
    busy = VisitItem(
        item_id="v-busy",
        name="晚间长块",
        city="西安",
        day=1,
        duration_minutes=215,
        category="citywalk",
        start_time=time(16, 40),
        end_time=time(20, 15),
        location=_C0,
    )
    d1 = _day(1, busy)
    plan = _plan(d1)
    _retime_meal_placeholders(plan, ensure_cards=True)

    dinner = [i for i in d1.items if "晚饭" in str(i.name)]
    assert dinner, "晚窗被占也要补迟场晚卡"
    assert dinner[0].start_time >= time(20, 30)
    assert dinner[0].duration_minutes >= 30


def test_heal_arrival_light_fills_old_plan_and_is_idempotent():
    """出站自愈：旧行程的空到达日补自由漫步 + 晚卡；重跑幂等。"""
    d1 = _day(1, _transfer(), _hotel())
    plan = _plan(d1, _day(2, _visit("城件一", 60, _C0, 2, tier=9)))
    heal_arrival_light(plan)
    walks = [i for i in d1.items if i.item_id.startswith("citywalk-ph-d")]
    assert len(walks) == 1, "旧行程空到达日应补自由漫步"
    assert [i for i in d1.items if getattr(i, "category", "") == "food"], "晚卡也要补"
    heal_arrival_light(plan)
    assert len([i for i in d1.items if i.item_id.startswith("citywalk-ph-d")]) == 1


def test_heal_arrival_light_leaves_days_with_content_alone():
    """到达日已有参访件 → 自愈不动它。"""
    street = _visit("回民街", 90, _C1, 1, tier=4, category="citywalk")
    d1 = _day(1, _transfer(), _hotel(), street)
    plan = _plan(d1)
    heal_arrival_light(plan)
    assert not any(i.item_id.startswith("citywalk-ph-d") for i in d1.items)
