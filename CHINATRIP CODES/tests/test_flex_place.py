"""时长收缩 / 30 分钟容忍（2026-11-16 用户拍板）。

口径：
- 非强约束景点（非演出/宴会/交通/餐宿、非用户钉住）60<d<90 可缩 1-15 分钟、
  d≥90 可缩 15-30 分钟；
- 与硬锚差 ≤30 分钟可接受，从强约束时间点倒排贴放（只吃下一站车程缓冲）。
"""

from __future__ import annotations

import datetime as dt

from app.services.agent import plan as plan_mod
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem

BUND = GeoPoint(lon=121.4903, lat=31.2398)
MUSEUM = GeoPoint(lon=121.4756, lat=31.2283)
ZHUJIAJIAO = GeoPoint(lon=121.04651, lat=31.10365)
YUYUAN = GeoPoint(lon=121.49131, lat=31.22713)


def _item(
    item_id: str,
    name: str,
    start: str | None,
    end: str | None,
    *,
    dur: int = 60,
    category: str = "sight",
    pinned: bool = False,
    location: GeoPoint | None = None,
    opening_hours: str | None = None,
) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=name,
        category=category,
        city="上海",
        day=1,
        duration_minutes=dur,
        start_time=dt.time.fromisoformat(start) if start else None,
        end_time=dt.time.fromisoformat(end) if end else None,
        pinned=pinned,
        location=location,
        opening_hours=opening_hours,
    )


def _plan(*items: VisitItem) -> tuple[ItineraryPlan, DayPlan]:
    day = DayPlan(day=1, base_city="上海", items=list(items))
    plan = ItineraryPlan(itinerary_id="it-flex", cities=["上海"], days=[day])
    return plan, day


def test_shrink_band_matches_user_rule() -> None:
    def band(dur: int, **kw) -> tuple[int, int]:
        return plan_mod._shrink_band(_item("v1", "点", None, None, dur=dur, **kw))

    assert band(75) == (1, 15)
    assert band(89) == (1, 15)
    assert band(90) == (15, 30)
    # 2026-11-17 用户拍板「d>=120 -> above 30」：两小时以上上限放到 60
    assert band(120) == (15, 60)
    assert band(210) == (15, 60)
    assert band(60) == (0, 0)
    assert band(45) == (0, 0)
    # 强约束面不缩：用户钉住 / 演出 / 餐 / 宿
    assert band(120, pinned=True) == (0, 0)
    assert band(120, category="show") == (0, 0)
    assert band(120, category="food") == (0, 0)
    assert band(120, category="hotel") == (0, 0)


def test_place_with_flex_shrinks_to_anchor() -> None:
    """豫园 90 分钟、16:30 闭园：15:15-16:30 按 75 分钟收口。"""
    plan, day = _plan(
        _item(
            "v47",
            "上海博物馆",
            "09:00",
            "12:00",
            dur=180,
            category="museum",
            pinned=True,
            location=MUSEUM,
        ),
        _item(
            "food-lunch-ph-d1",
            "午饭（自由安排）",
            "12:00",
            "13:00",
            dur=60,
            category="food",
        ),
        _item(
            "v49",
            "朱家角镇",
            "13:03",
            "14:03",
            dur=60,
            pinned=True,
            location=ZHUJIAJIAO,
        ),
        _item(
            "v46",
            "外滩",
            "17:00",
            "19:00",
            dur=120,
            category="nature",
            pinned=True,
            location=BUND,
        ),
    )
    visit = _item(
        "v1",
        "豫园",
        None,
        None,
        dur=90,
        category="park",
        location=YUYUAN,
        opening_hours="周二至周日 09:00-16:30(16:00停止入馆)",
    )
    placed = plan_mod._place_with_flex(plan, day, visit)
    assert placed is not None
    start, dur, note = placed
    assert (start // 60, start % 60) == (15, 15)
    assert dur == 75
    assert "90→75" in note


def test_place_with_flex_tolerates_within_30_minutes() -> None:
    """差 25 分钟（≤30）：不缩时长，贴着下一站前沿顺排。"""
    plan, day = _plan(
        _item("v0", "晨点", "08:30", "12:00", dur=210, pinned=True),
        _item("v1", "前站", "13:30", "15:00", dur=90, pinned=True),
        _item("v2", "后站", "16:55", "21:00", dur=245, pinned=True),
    )
    visit = _item("v9", "豫园", None, None, dur=80, category="park", location=YUYUAN)
    placed = plan_mod._place_with_flex(plan, day, visit)
    assert placed is not None
    start, dur, note = placed
    assert (start // 60, start % 60) == (15, 30)
    assert dur == 80
    assert "容忍" in note


def test_place_with_flex_refuses_hard_item() -> None:
    """用户钉住的卡不缩不容忍：放不下就返回 None（原计划不动）。"""
    plan, day = _plan(
        _item("v0", "晨点", "08:30", "12:00", dur=210, pinned=True),
        _item("v1", "前站", "13:30", "15:00", dur=90, pinned=True),
        _item("v2", "后站", "16:55", "21:00", dur=245, pinned=True),
    )
    visit = _item(
        "v9", "豫园", None, None, dur=80, category="park", location=YUYUAN, pinned=True
    )
    assert plan_mod._place_with_flex(plan, day, visit) is None
