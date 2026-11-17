# -*- coding: utf-8 -*-
"""雨日调换闸锚（2026-11-11 拍板「打开行程自动更新天气，同时根据雨天
走调换逻辑」）：天气真值每日漂移，建划时的雨日判读过期后，读路径须按
新雨情把不耐雨组合与干日的耐雨组合对调。

闸口径（类级）：
① 只动「族」——当天观光卡按 ≤1km 原子连边聚族，族整体对调；
② 严进严出——雨日族不耐雨度（硬露天员数, 未标注弱件数）严格大于
   干日族才调；相等/倒挂不动（宁缺勿滥）；
③ 族内有钉/软钉/必去/手建/精选/演出卡 → 整族不调（用户权威与
   场次日期不可自动挪）；
④ 交通日（含城际腿）不参与；
⑤ 对调后两天 4/日帽与 480min 账不得破，重排时刻后 validate 无
   error 才落盘，否则放弃本次对调；
⑥ 餐/酒店卡随日不走。
"""

from __future__ import annotations

from datetime import time

from app.services.agent.plan import _rain_rebalance_days
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)

# 族甲布点（≤1km 原子连边）：(104.060..070, 30.66)
_A0 = GeoPoint(lat=30.66, lon=104.060)
_A1 = GeoPoint(lat=30.66, lon=104.065)
_A2 = GeoPoint(lat=30.66, lon=104.070)
# 族乙布点：两族相距 ~40km 互不连边
_B0 = GeoPoint(lat=30.66, lon=104.500)
_B1 = GeoPoint(lat=30.66, lon=104.505)
_B2 = GeoPoint(lat=30.66, lon=104.510)


def _v(
    item_id: str,
    name: str,
    day: int,
    *,
    loc: GeoPoint | None = None,
    cat: str = "attraction",
    rain_ok: str | None = None,
    tier: int | None = None,
    dur: int = 90,
    st: time | None = None,
    en: time | None = None,
    bvt: str | None = None,
    pinned: bool = False,
) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=name,
        city="西安",
        day=day,
        category=cat,
        location=loc,
        rain_ok=rain_ok,
        tier=tier,
        duration_minutes=dur,
        start_time=st,
        end_time=en,
        best_visit_time=bvt,
        pinned=pinned,
    )


def _xfer(
    item_id: str, day: int, frm: str, to: str, st: time, en: time
) -> TransferItem:
    return TransferItem(
        item_id=item_id,
        day=day,
        seq=1,
        from_city=frm,
        to_city=to,
        mode="flight",
        start_time=st,
        end_time=en,
        duration_minutes=180,
    )


def _full_day_stays(day: int) -> list[VisitItem]:
    """整日固定锚：午餐软钉 + 晚间回酒店（对调后必须原日保留）。"""
    return [
        _v(
            f"d{day}lunch",
            "午饭（自由安排）",
            day,
            cat="food",
            dur=90,
            st=time(12, 0),
            en=time(13, 30),
        ),
        _v(
            f"d{day}hotel",
            "🏨 回酒店·夜间休息",
            day,
            cat="hotel",
            dur=60,
            st=time(20, 0),
            en=time(21, 0),
        ),
    ]


def _family_a(day: int) -> list[VisitItem]:
    """不耐雨族：硬露天王牌（rain_ok=no）+ 两耐雨员 → intol=(1,0)。"""
    return [
        _v(
            f"a1d{day}",
            "甲露天",
            day,
            loc=_A0,
            rain_ok="no",
            tier=2,
            st=time(9, 0),
            en=time(10, 30),
        ),
        _v(
            f"a2d{day}",
            "甲员二",
            day,
            loc=_A1,
            rain_ok="yes",
            st=time(10, 45),
            en=time(12, 15),
        ),
        _v(
            f"a3d{day}",
            "甲员三",
            day,
            loc=_A2,
            rain_ok="yes",
            st=time(14, 0),
            en=time(15, 30),
        ),
    ]


def _family_b(day: int) -> list[VisitItem]:
    """耐雨族：王牌+两员全 rain_ok=yes → intol=(0,0)。"""
    return [
        _v(
            f"b1d{day}",
            "乙王牌",
            day,
            loc=_B0,
            rain_ok="yes",
            tier=1,
            st=time(9, 0),
            en=time(10, 30),
        ),
        _v(
            f"b2d{day}",
            "乙员二",
            day,
            loc=_B1,
            rain_ok="yes",
            st=time(10, 45),
            en=time(12, 15),
        ),
        _v(
            f"b3d{day}",
            "乙员三",
            day,
            loc=_B2,
            rain_ok="yes",
            st=time(14, 0),
            en=time(15, 30),
        ),
    ]


def _plan(*, day2: list[VisitItem], day3: list[VisitItem]) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-rain-test",
        cities=["西安"],
        start_date="2026-11-12",
        days=[
            DayPlan(
                day=1,
                base_city="西安",
                items=[
                    _xfer("t1", 1, "上海", "西安", time(9, 0), time(12, 0)),
                    _v(
                        "d1hotel",
                        "🏨 酒店入住（放行李·休整）",
                        1,
                        cat="hotel",
                        dur=60,
                        st=time(13, 30),
                        en=time(14, 30),
                    ),
                ],
            ),
            DayPlan(day=2, base_city="西安", items=[*day2, *_full_day_stays(2)]),
            DayPlan(day=3, base_city="西安", items=[*day3, *_full_day_stays(3)]),
            DayPlan(
                day=4,
                base_city="西安",
                items=[
                    _xfer("t4", 4, "西安", "上海", time(17, 0), time(20, 0)),
                ],
            ),
        ],
    )


def _names(day: DayPlan) -> set[str]:
    return {i.name for i in day.items if isinstance(i, VisitItem)}


def test_rainy_day_family_swaps_with_dry_day_tolerant_family():
    """天气漂移后打开行程：雨日(day2)的不耐雨族甲必须与干日(day3)的
    耐雨族乙对调——甲族落 day3，乙族落 day2；餐/酒店卡原地不动。"""
    plan = _plan(day2=_family_a(2), day3=_family_b(3))
    notes = _rain_rebalance_days(plan, {"西安": {2}}, "2026-11-12")
    assert notes, "应对调并留披露"
    d2 = next(d for d in plan.days if d.day == 2)
    d3 = next(d for d in plan.days if d.day == 3)
    assert {"乙王牌", "乙员二", "乙员三"} <= _names(d2)
    assert {"甲露天", "甲员二", "甲员三"} <= _names(d3)
    assert "午饭（自由安排）" in _names(d2)
    assert "午饭（自由安排）" in _names(d3)
    assert "🏨 回酒店·夜间休息" in _names(d2)
    assert "🏨 回酒店·夜间休息" in _names(d3)
    # 换天后时刻重排：观光卡不得裸奔（无时刻）
    for d in (d2, d3):
        for it in d.items:
            if isinstance(it, VisitItem) and it.category not in ("food", "hotel"):
                assert it.start_time is not None and it.end_time is not None
    # 披露含两族代表名
    blob = " ".join(notes)
    assert "甲露天" in blob and "乙王牌" in blob


def test_pinned_member_blocks_family_swap():
    """族内有用户钉 → 整族不自动挪（铁律 19），宁可雨日硬扛也不动钉。"""
    fam = _family_a(2)
    fam[0] = fam[0].model_copy(update={"pinned": True})
    plan = _plan(day2=fam, day3=_family_b(3))
    notes = _rain_rebalance_days(plan, {"西安": {2}}, "2026-11-12")
    assert notes == []
    d2 = next(d for d in plan.days if d.day == 2)
    assert "甲露天" in _names(d2)


def test_show_member_blocks_family_swap():
    """族内挂演出（场次绑死日期）→ 整族不调。"""
    fam = _family_a(2)
    fam[2] = fam[2].model_copy(update={"category": "entertainment"})
    plan = _plan(day2=fam, day3=_family_b(3))
    notes = _rain_rebalance_days(plan, {"西安": {2}}, "2026-11-12")
    assert notes == []
    d2 = next(d for d in plan.days if d.day == 2)
    assert "甲露天" in _names(d2)


def test_equal_intolerance_no_swap():
    """干日族同样不耐雨（intol 相等）→ 对调无收益，不动（宁缺勿滥）。"""
    fam_b = _family_b(3)
    fam_b[0] = fam_b[0].model_copy(update={"rain_ok": "no", "tier": 2})
    plan = _plan(day2=_family_a(2), day3=fam_b)
    notes = _rain_rebalance_days(plan, {"西安": {2}}, "2026-11-12")
    assert notes == []
    d2 = next(d for d in plan.days if d.day == 2)
    assert "甲露天" in _names(d2)


def test_no_rain_noop():
    plan = _plan(day2=_family_a(2), day3=_family_b(3))
    notes = _rain_rebalance_days(plan, {}, "2026-11-12")
    assert notes == []
    d2 = next(d for d in plan.days if d.day == 2)
    assert "甲露天" in _names(d2)


def test_transfer_day_never_swapped():
    """交通日（含城际腿）即使进雨集也不参与对调。"""
    plan = _plan(
        day2=_family_a(2),
        day3=[*_family_b(3), _xfer("t3", 3, "西安", "咸阳", time(18, 0), time(19, 0))],
    )
    notes = _rain_rebalance_days(plan, {"西安": {2, 3}}, "2026-11-12")
    assert notes == []
