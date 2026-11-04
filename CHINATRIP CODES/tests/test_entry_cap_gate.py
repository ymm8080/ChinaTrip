# -*- coding: utf-8 -*-
"""白天入场闸 16:30 + 营业窗兜底校验回归（2026-11-01 成都熊猫基地
18:00（闭馆 17:00）排期事故，会话 3e44c428）：

- 系统必去钉（pinned）落在未排上时间的条目上不再豁免入场闸——事故
  根因：solve 降级日必去件无时刻，pin 后再走兜底被甩到闸后；
- 兜底落位与挪日修复整段校验营业窗（此前只看闸不看闭馆时刻）；
- 「闭馆 ≥17:30 即豁免」废除 → 白天开到晚间的场馆同受 16:30 闸；
  仅晚间开放（全窗开 ≥17:00）的夜游类场馆豁免（白天无档，不豁免
  则永远排不进）；
- 2026-11-03 用户重申（第1天城墙 18:43 排期事故）：闸=最晚 16:30
  **开场**（start ≤ 16:30，转场/到达日同闸），11-02 的「最晚 16:30
  结束」（cap−dur）与转场日让位废除。
"""

from datetime import time as _t

from app.services.itinerary.models import DayPlan, ItineraryPlan, PoiHours, VisitItem
from app.services.itinerary.solver import generic_entry_cap

CAP = 16 * 60 + 30


def _visit(**kw):
    base = dict(
        item_id="v",
        name="点",
        city="成都",
        day=1,
        # 默认 60 分钟普通点（11-04 起默认 >80min 会落大点 15:30 闸档）
        duration_minutes=60,
        category="sight",
        best_visit_time="any",
    )
    base.update(kw)
    return VisitItem(**base)


# --- generic_entry_cap：闸值与豁免面 ------------------------------------


def test_entry_cap_is_1630_for_plain_sight():
    # 2026-11-03 用户重申「最晚 16:30 开场」：闸=16:30 起点值，不再
    # 减时长（11-02「最晚 16:30 结束」口径废除）。
    assert generic_entry_cap(_visit(), None) == CAP


def test_entry_cap_big_sight_tightened_to_1530():
    # 2026-11-04 拍板「大型的旅游景区不适合放下午16:00」：时长>80min
    # 的非街区大点最晚 15:30 开场（16:00 起排的大点天黑前走不完）。
    big = _visit(duration_minutes=120)
    assert generic_entry_cap(big, None) == 15 * 60 + 30
    # 街区轻游（tier8=CityWalk）不算大点——正是大点后面配的近游，
    # 维持 16:30 闸（回民街式街区可开进傍晚）。
    street = _visit(duration_minutes=120, tier=8)
    assert generic_entry_cap(street, None) == CAP
    # 夜属性大点（夜景公园 best_visit_time=evening）走夜游豁免不设闸。
    night_big = _visit(duration_minutes=120, best_visit_time="evening")
    assert generic_entry_cap(night_big, None) is None
    # 用户自钉且有时刻（铁律 19）照旧豁免。
    pinned = _visit(duration_minutes=120, pinned=True, start_time=_t(16, 0))
    assert generic_entry_cap(pinned, None) is None
    # 演出/餐/酒店类照旧豁免（80 分钟演出不是「旅游景区」）。
    show = _visit(duration_minutes=120, category="entertainment")
    assert generic_entry_cap(show, None) is None
    # 大点晚开门营业窗自治按加严闸值判：15:45 才开 > 15:30 闸 → 视为
    # 夜游类交营业窗收口。
    late_open = PoiHours(poi_id="p7", opens=_t(15, 45), closes=_t(19, 0))
    assert generic_entry_cap(big, late_open) is None
    # 15:00 开门 ≤ 15:30 闸 → 照常受闸。
    ok_open = PoiHours(poi_id="p8", opens=_t(15, 0), closes=_t(18, 0))
    assert generic_entry_cap(big, ok_open) == 15 * 60 + 30


def test_scoring_big_entry_cap_aligned_with_solver():
    from app.services.itinerary import scoring, solver

    assert (
        scoring.ENTRY_CAP_BIG_MINUTES
        == solver.BIG_SITE_ENTRY_CAP_MINUTES
        == 15 * 60 + 30
    )
    assert scoring.AFTERNOON_START_MINUTES == solver.AFTERNOON_START_MINUTES
    assert scoring.BIG_SITE_MIN_MINUTES == solver.BIG_SITE_MIN_MINUTES == 80


def test_pinned_with_time_exempt_but_pinned_untimed_capped():
    # 铁律 19 豁免要求「pinned 且有时刻」：系统必去钉可能落在排不上
    # 时间的条目上（降级日）——无时刻即无用户确认时刻可豁免。
    timed = _visit(pinned=True, start_time=_t(18, 0))
    assert generic_entry_cap(timed, None) is None
    untimed = _visit(pinned=True)  # 事故形态：必去钉+未排时
    assert generic_entry_cap(untimed, None) == CAP


def test_open_late_no_longer_exempt_but_evening_only_exempt():
    # 白天开到晚间（07:30-18:00）：旧口径豁免 → 2026-11-01 用户裁定
    # 除夜游与演出外一律最晚 16:30 开场，现受闸。
    daytime = PoiHours(poi_id="p1", opens=_t(7, 30), closes=_t(18, 0))
    assert generic_entry_cap(_visit(), daytime) == CAP
    # 仅晚间开放（18:00-21:30）= 夜游类：白天无档，豁免。
    night = PoiHours(poi_id="p2", opens=_t(18, 0), closes=_t(21, 30))
    assert generic_entry_cap(_visit(), night) is None
    # 混合分段（白天段+晚间段）：有白天档可走，仍受闸。
    mixed = PoiHours(
        poi_id="p3",
        opens=_t(9, 0),
        closes=_t(21, 0),
        windows=[(_t(9, 0), _t(12, 0)), (_t(18, 0), _t(21, 0))],
    )
    assert generic_entry_cap(_visit(), mixed) == CAP


def test_late_open_hours_governed_by_window_not_cap():
    # 晚开门场馆营业窗自治（2026-11-02 backlog #2，11-03 随开场闸收窄）：
    # 16:00 开、18:00 关的场馆闸前（16:00-16:30）物理有档 → 照常受闸；
    # 开门晚于闸值（16:45 才开）才豁免，交 _fits_hours_window 收口。
    late = PoiHours(poi_id="p4", opens=_t(16, 0), closes=_t(18, 0))
    assert generic_entry_cap(_visit(duration_minutes=60), late) == CAP
    later = PoiHours(poi_id="p6", opens=_t(16, 45), closes=_t(20, 0))
    assert generic_entry_cap(_visit(duration_minutes=60), later) is None
    # 开门恰在闸值上（15:30 开、60 分钟点）仍受闸：15:30-16:30 装得下。
    edge = PoiHours(poi_id="p5", opens=_t(15, 30), closes=_t(18, 0))
    assert generic_entry_cap(_visit(duration_minutes=60), edge) == CAP


def test_scoring_entry_cap_aligned_with_solver():
    from app.services.itinerary.scoring import ENTRY_CAP_MINUTES
    from app.services.itinerary.solver import _GENERIC_ENTRY_CAP_MINUTES

    assert ENTRY_CAP_MINUTES == _GENERIC_ENTRY_CAP_MINUTES == CAP


# --- _fits_hours_window：兜底/挪日营业窗整段校验 ------------------------


def test_fits_hours_window_panda_string_shape():
    from app.services.agent.plan import _fits_hours_window

    # 熊猫基地串解析形态：07:30-12:00 + 12:00-17:00（零间隔 → 合并
    # 07:30-17:00 一段）。
    h = PoiHours(
        poi_id="ct_成都_0",
        opens=_t(7, 30),
        closes=_t(17, 0),
        windows=[(_t(7, 30), _t(12, 0)), (_t(12, 0), _t(17, 0))],
    )
    assert _fits_hours_window(h, 14 * 60, 180) is True  # 14:00-17:00 整段在窗
    assert _fits_hours_window(h, 15 * 60, 180) is False  # 15:00-18:00 越闭馆
    assert _fits_hours_window(h, 18 * 60, 180) is False  # 18:00 起完全在窗外
    assert _fits_hours_window(None, 18 * 60, 180) is True  # 无营业数据不硬卡
    # 午休分段（G3）：09:00-12:00 + 13:30-17:00——整段跨午休不可。
    g3 = PoiHours(
        poi_id="p4",
        opens=_t(9, 0),
        closes=_t(17, 0),
        windows=[(_t(9, 0), _t(12, 0)), (_t(13, 30), _t(17, 0))],
    )
    assert _fits_hours_window(g3, 10 * 60 + 30, 180) is False
    assert _fits_hours_window(g3, 13 * 60 + 30, 180) is True


# --- 兜底：pinned+未排不再被甩到闸后/闭馆后 ------------------------------


def _panda_item():
    return VisitItem(
        item_id="v10",
        name="成都大熊猫繁育研究基地",
        city="成都",
        day=1,
        category="zoo",
        duration_minutes=180,
        pinned=True,
        poi_id="ct_成都_0",
        opening_hours=(
            "今天07:30-12:00开放（17:00停止售票，17:00停止入园）;12:00-17:00开放"
        ),
    )


def test_fallback_pinned_untimed_not_dumped_after_gate():
    """事故复现（会话 3e44c428 day1）：上午被固定件占满、下午固定到
    17:30——pinned 必去「熊猫基地」被兜底甩到 18:00-21:00。修复后：
    合法落位（闸 16:30 + 营业窗 17:00 收口内）或留空交校验披露。"""
    from app.services.agent.plan import _fallback_sequence_times

    morning = VisitItem(
        item_id="v0",
        name="固定上午件",
        city="成都",
        day=1,
        duration_minutes=180,
        start_time=_t(9, 0),
        end_time=_t(12, 0),
    )
    afternoon = VisitItem(
        item_id="v1",
        name="青城山—都江堰",
        city="成都",
        day=1,
        duration_minutes=180,
        start_time=_t(14, 30),
        end_time=_t(17, 30),
    )
    panda = _panda_item()
    plan = ItineraryPlan(
        itinerary_id="it-x",
        cities=["成都"],
        days=[DayPlan(day=1, base_city="成都", items=[morning, afternoon, panda])],
        assumptions=[],
    )
    _fallback_sequence_times(plan)
    assert panda.start_time is None  # 12:30-18:00 无合法整段 → 留空披露


def test_fallback_pinned_untimed_places_inside_hours_when_slot_exists():
    from app.services.agent.plan import _fallback_sequence_times

    morning = VisitItem(
        item_id="v0",
        name="固定上午件",
        city="成都",
        day=1,
        duration_minutes=210,
        start_time=_t(9, 0),
        end_time=_t(12, 30),
    )
    panda = _panda_item()
    plan = ItineraryPlan(
        itinerary_id="it-x",
        cities=["成都"],
        days=[DayPlan(day=1, base_city="成都", items=[morning, panda])],
        assumptions=[],
    )
    _fallback_sequence_times(plan)
    assert panda.start_time == _t(13, 0)  # 固定件缓冲后 13:00-16:00 整段在窗
    assert panda.end_time == _t(16, 0)


def test_solver_day_with_pinned_untimed_degrades_not_places():
    """solver 主路对 pinned+未排件本来就按日降级（_visit_spec None）——
    锁行为：不得因闸口径变化而改成硬排。"""
    from app.services.itinerary.solver import insertion_schedule_day, solve_day

    panda = _panda_item()
    day = DayPlan(day=1, base_city="成都", items=[panda])
    hours = [
        PoiHours(
            poi_id="ct_成都_0",
            opens=_t(7, 30),
            closes=_t(17, 0),
            windows=[(_t(7, 30), _t(12, 0)), (_t(12, 0), _t(17, 0))],
        )
    ]
    assert insertion_schedule_day(day, poi_hours=hours) is None
    assert solve_day(day, poi_hours=hours) is None
