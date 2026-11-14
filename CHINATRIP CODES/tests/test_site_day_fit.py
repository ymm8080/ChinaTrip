# -*- coding: utf-8 -*-
"""三轴景点校核回归（2026-11-14 用户拍板「sites should check city, date, weather」）。

现场（h5_state.db rowid 2139，上海→北京 2 天 2026-11-16）：Day1 卡片排成
「07:00 天安门广场 → 09:00 上海→北京航班」——景点排在起飞之前，原因是
升旗时刻锚（_apply_flag_schedule）不看当天转场窗，把天安门钉死在 07:00，
而航班 12:00 才落地。本文件钉住：

  ① 升旗锚的转场日可行性闸（_flag_pin_reachable / _apply_flag_schedule）；
  ② 闭馆日解析（_closed_weekdays：周一闭馆 / 周二至周日 / Closed on Mondays）；
  ③ 终装三轴校核（_enforce_site_day_fit）：城市侧、日期侧、天气侧违规卡的
     同日重排 → 同城换天 → 撤时刻留痕三级修复，以及同名重复卡合并。
"""

from datetime import time

from app.services.agent.plan import (
    _apply_flag_schedule,
    _closed_weekdays,
    _enforce_site_day_fit,
    _flag_pin_reachable,
    _minutes_of,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)

_BJ = GeoPoint(lon=116.41, lat=39.91)
_CD = GeoPoint(lon=116.42, lat=40.43)

GU_HOURS = (
    "周一关闭(法定节假日除外),4月1日至10月31日,周二至周日08:30-17:00(16:00停止检票),"
    "11月1日至3月31日,周二至周日08:30-16:30(15:30停止检票)"
)


def _visit(
    item_id: str,
    name: str,
    *,
    city: str = "北京",
    day: int = 1,
    start: time | None = None,
    dur: int = 90,
    hours: str | None = None,
    rain_ok: str | None = None,
    category: str = "attraction",
    poi_id: str | None = None,
) -> VisitItem:
    end = (
        None
        if start is None
        else time(
            (start.hour * 60 + start.minute + dur) // 60 % 24,
            (start.minute + dur) % 60,
        )
    )
    return VisitItem(
        item_id=item_id,
        name=name,
        city=city,
        day=day,
        category=category,
        duration_minutes=dur,
        start_time=start,
        end_time=end,
        location=_BJ,
        opening_hours=hours,
        rain_ok=rain_ok,
        poi_id=poi_id or f"poi-{item_id}",
    )


def _flight(
    *,
    day: int = 1,
    start: time = time(9, 0),
    end: time = time(12, 0),
) -> TransferItem:
    return TransferItem(
        item_id=f"t-{day}",
        day=day,
        seq=1,
        from_city="上海",
        to_city="北京",
        mode="flight",
        start_time=start,
        end_time=end,
        duration_minutes=(
            (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        ),
    )


# --- ① 升旗锚的转场日闸 ---------------------------------------------------


def test_flag_pin_reachable_blocks_arrival_day():
    item = _visit("v1", "天安门广场")
    day = DayPlan(day=1, base_city="上海", items=[item, _flight()])
    # 07:00 升旗 vs 12:00 落地：人还在上海
    assert _flag_pin_reachable(day, item, time(7, 0)) is False
    # 04:00 起飞 06:00 落地也赶不上（落地 +150 地板）
    early = DayPlan(
        day=1,
        base_city="上海",
        items=[_flight(start=time(4, 0), end=time(6, 0))],
    )
    assert _flag_pin_reachable(early, item, time(7, 0)) is False


def test_flag_pin_reachable_allows_full_day():
    item = _visit("v1", "天安门广场")
    day = DayPlan(day=1, base_city="北京", items=[item])
    assert _flag_pin_reachable(day, item, time(7, 0)) is True


def test_flag_pin_reachable_blocks_departure_day():
    item = _visit("v1", "天安门广场")
    tr = TransferItem(
        item_id="t-out",
        day=2,
        seq=1,
        from_city="北京",
        to_city="上海",
        mode="flight",
        start_time=time(9, 0),
        end_time=time(12, 0),
    )
    day = DayPlan(day=2, base_city="北京", items=[item, tr])
    assert _flag_pin_reachable(day, item, time(7, 0)) is False


def test_apply_flag_schedule_skips_arrival_day(monkeypatch):
    monkeypatch.setattr(
        "app.services.flag_schedule.get_flag_time", lambda *a, **k: time(7, 0)
    )
    item = _visit("v1", "天安门广场", city="北京")
    plan = ItineraryPlan(
        itinerary_id="it-flag",
        cities=["上海", "北京"],
        days=[DayPlan(day=1, base_city="上海", items=[item, _flight()])],
        start_date="2026-11-16",
    )
    _apply_flag_schedule(plan)
    assert not item.fixed_sessions  # 转场日不锁升旗
    assert any("升旗" in str(a) for a in plan.assumptions)


def test_apply_flag_schedule_pins_full_day(monkeypatch):
    monkeypatch.setattr(
        "app.services.flag_schedule.get_flag_time", lambda *a, **k: time(7, 0)
    )
    item = _visit("v1", "天安门广场", day=2)
    plan = ItineraryPlan(
        itinerary_id="it-flag2",
        cities=["北京"],
        days=[DayPlan(day=2, base_city="北京", items=[item])],
        start_date="2026-11-17",
    )
    _apply_flag_schedule(plan)
    assert item.fixed_sessions == [time(7, 0)]


# --- ② 闭馆日解析 ---------------------------------------------------------


def test_closed_weekdays_parsing():
    assert _closed_weekdays(GU_HOURS) == frozenset({0})  # 故宫：周一闭馆
    assert _closed_weekdays("周一至周日 09:30-17:30") == frozenset()
    assert _closed_weekdays("今天06:30-19:00开放（18:00停止入园）") == frozenset()
    assert _closed_weekdays(None) == frozenset()
    assert _closed_weekdays("Closed on Mondays, Tue-Sun 09:00-17:00") == frozenset({0})
    assert _closed_weekdays("Monday to Sunday 09:00-22:00") == frozenset()


# --- ③ 终装三轴校核 -------------------------------------------------------


def test_fit_moves_site_before_flight():
    """2139 实录：07:00 天安门 → 09:00 上海起飞，必须被修成落地之后。"""
    item = _visit("v1", "天安门广场", start=time(7, 0))
    day1 = DayPlan(day=1, base_city="上海", items=[item, _flight()])
    day2 = DayPlan(day=2, base_city="北京", items=[])
    plan = ItineraryPlan(
        itinerary_id="it-fit",
        cities=["上海", "北京"],
        days=[day1, day2],
        start_date="2026-11-16",
    )
    _enforce_site_day_fit(plan)
    placed = [i for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    assert len(placed) == 1
    assert placed[0].start_time is not None
    assert _minutes_of(placed[0].start_time) >= 12 * 60 + 150  # 落地 +150 地板


def test_fit_clears_when_no_day_can_host():
    item = _visit("v1", "天安门广场", start=time(7, 0))
    late = _flight(start=time(17, 0), end=time(20, 0))
    plan = ItineraryPlan(
        itinerary_id="it-fit2",
        cities=["上海", "北京"],
        days=[DayPlan(day=1, base_city="上海", items=[item, late])],
        start_date="2026-11-16",
    )
    notes = _enforce_site_day_fit(plan)
    assert item.start_time is None  # 撤时刻留卡，不交错误时刻
    assert notes and "天安门广场" in notes[0]


def test_fit_moves_closed_weekday_site():
    """2026-11-16 = 周一：故宫当天闭馆，必须挪到周二。"""
    item = _visit("v1", "故宫博物院", day=1, start=time(9, 0), dur=120, hours=GU_HOURS)
    day1 = DayPlan(day=1, base_city="北京", items=[item])
    day2 = DayPlan(day=2, base_city="北京", items=[])
    plan = ItineraryPlan(
        itinerary_id="it-fit3",
        cities=["北京"],
        days=[day1, day2],
        start_date="2026-11-16",
    )
    notes = _enforce_site_day_fit(plan)
    assert item.day == 2
    assert item.start_time is not None
    assert item.start_time <= time(14, 30)  # 16:30 闭馆前排得下
    assert any("改排第2天" in str(n) for n in notes)


def test_fit_moves_rain_outdoor_site():
    item = _visit(
        "v1", "慕田峪长城", start=time(9, 0), dur=180, rain_ok="no", hours=None
    )
    item.location = _CD
    day1 = DayPlan(day=1, base_city="北京", items=[item])
    day2 = DayPlan(day=2, base_city="北京", items=[])
    plan = ItineraryPlan(
        itinerary_id="it-fit4",
        cities=["北京"],
        days=[day1, day2],
        start_date="2026-11-16",
    )
    _enforce_site_day_fit(plan, rain_days={"北京": {1}})
    assert item.day == 2
    assert item.start_time is not None


def test_fit_merges_duplicate_site_cards():
    a = _visit("v1", "颐和园", day=1, start=time(9, 0), dur=120)
    b = _visit("v2", "颐和园", day=2, start=time(15, 0), dur=120)
    plan = ItineraryPlan(
        itinerary_id="it-fit5",
        cities=["北京"],
        days=[
            DayPlan(day=1, base_city="北京", items=[a]),
            DayPlan(day=2, base_city="北京", items=[b]),
        ],
        start_date="2026-11-16",
    )
    notes = _enforce_site_day_fit(plan)
    names = [i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    assert names == ["颐和园"]
    assert any("重复卡" in str(n) for n in notes)

def test_fit_keeps_rain_outdoor_when_no_dry_day():
    """雨日换不到干日：保留原时刻只披露，绝不下成未排。"""
    item = _visit("v1", "天安门广场", start=time(9, 0), rain_ok="no")
    plan = ItineraryPlan(
        itinerary_id="it-fit6",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[item])],
        start_date="2026-11-16",
    )
    notes = _enforce_site_day_fit(plan, rain_days={"北京": {1}})
    assert item.start_time == time(9, 0)
    assert any("雨" in str(n) for n in notes)
