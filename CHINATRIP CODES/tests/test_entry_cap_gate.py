# -*- coding: utf-8 -*-
"""白天入场结束闸 16:30 + 营业窗兜底校验回归（2026-11-01 成都熊猫基地
18:00（闭馆 17:00）排期事故，会话 3e44c428）：

- 系统必去钉（pinned）落在未排上时间的条目上不再豁免入场闸——事故
  根因：solve 降级日必去件无时刻，pin 后再走兜底被甩到闸后；
- 兜底落位与挪日修复整段校验营业窗（此前只看闸不看闭馆时刻）；
- 「闭馆 ≥17:30 即豁免」废除 → 白天开到晚间的场馆同受闸；
  仅晚间开放（全窗开 ≥17:00）的夜游类场馆豁免（白天无档，不豁免
  则永远排不进）；
- 2026-11-03 用户重申（第1天城墙 18:43 排期事故）：闸=最晚 16:30
  开场（start ≤ 16:30，转场/到达日同闸），11-02 的「最晚 16:30
  结束」（cap−dur）与转场日让位废除；
- **2026-11-05 终裁（第 4 次重述，成都武侯祠 15:23+90=16:53 判违规
  「下午 4:30 以后不放景点，除非是夜景或者 SHOW」）**：闸升级为
  **结束闸**——观光占用须 16:30 前收尾，最晚开场 = 16:30 − 时长
  （大点 15:30 开场带被时长>80min 自然含入）；「开门晚于闸值→豁免」
  分支废除（会放行 16:30 后占用），晚开门场馆当天物理无档 → 挪日。
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
        # 默认 60 分钟普通点（11-04 起默认 >80min 会落大点闸档）
        duration_minutes=60,
        category="sight",
        best_visit_time="any",
    )
    base.update(kw)
    return VisitItem(**base)


# --- generic_entry_cap：结束闸与豁免面 ------------------------------------


def test_entry_cap_end_based_plain_sight():
    # 2026-11-05 终裁：观光占用须 16:30 前收尾 → 最晚开场 = 16:30 −
    # 时长（武侯祠式 90 分钟点最晚 15:00 开场，15:23 开即违规形态）。
    assert generic_entry_cap(_visit(duration_minutes=30), None) == CAP - 30
    assert generic_entry_cap(_visit(), None) == CAP - 60
    assert generic_entry_cap(_visit(duration_minutes=90), None) == CAP - 90
    # 时长缺省按 DEFAULT_VISIT_MINUTES=60 回减。
    assert generic_entry_cap(_visit(duration_minutes=None), None) == CAP - 60


def test_entry_cap_big_sight_cap_and_exemptions():
    # 大点开场带（11-04）：>80min 时结束闸自然含入 15:30——120 分钟
    # 大点最晚 14:30 开场（结束 16:30）。
    big = _visit(duration_minutes=120)
    assert generic_entry_cap(big, None) == CAP - 120
    # 街区轻游（tier8=CityWalk）不算大点，但同受结束闸。
    street = _visit(duration_minutes=120, tier=8)
    assert generic_entry_cap(street, None) == CAP - 120
    # 夜属性大点（夜景公园 best_visit_time=evening）走夜游豁免不设闸。
    night_big = _visit(duration_minutes=120, best_visit_time="evening")
    assert generic_entry_cap(night_big, None) is None
    # 用户自钉且有时刻（铁律 19）照旧豁免。
    pinned = _visit(duration_minutes=120, pinned=True, start_time=_t(16, 0))
    assert generic_entry_cap(pinned, None) is None
    # 演出/餐/酒店类照旧豁免（80 分钟演出不是「旅游景区」）。
    show = _visit(duration_minutes=120, category="entertainment")
    assert generic_entry_cap(show, None) is None
    # 晚开门营业窗不再豁免（11-05 终裁废除 11-02 分支）：15:45 开+
    # 120min=17:45 收尾即违规形态，照常返回结束闸 → 当天物理无档挪日。
    late_open = PoiHours(poi_id="p7", opens=_t(15, 45), closes=_t(19, 0))
    assert generic_entry_cap(big, late_open) == CAP - 120
    # 15:00 开门 120min：15:00-17:00 收尾越结束闸 → 同样只给结束闸。
    ok_open = PoiHours(poi_id="p8", opens=_t(15, 0), closes=_t(18, 0))
    assert generic_entry_cap(big, ok_open) == CAP - 120


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
    assert generic_entry_cap(untimed, None) == CAP - 60


def test_open_late_no_longer_exempt_but_evening_only_exempt():
    # 白天开到晚间（07:30-18:00）：旧口径豁免 → 2026-11-01 用户裁定
    # 除夜游与演出外一律受闸，现按结束闸受闸。
    daytime = PoiHours(poi_id="p1", opens=_t(7, 30), closes=_t(18, 0))
    assert generic_entry_cap(_visit(), daytime) == CAP - 60
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
    assert generic_entry_cap(_visit(), mixed) == CAP - 60


def test_late_open_no_longer_exempt_under_end_gate():
    # 2026-11-05 终裁废除「开门晚于闸值→豁免」分支：16:00 开、60 分钟
    # 点 = 16:00-17:00 收尾越闸 → 不再豁免，返回结束闸（当天无档挪日）；
    # 16:45 开同理；15:30 开 60 分钟 = 15:30-16:30 恰好收尾在闸内。
    late = PoiHours(poi_id="p4", opens=_t(16, 0), closes=_t(18, 0))
    assert generic_entry_cap(_visit(duration_minutes=60), late) == CAP - 60
    later = PoiHours(poi_id="p6", opens=_t(16, 45), closes=_t(20, 0))
    assert generic_entry_cap(_visit(duration_minutes=60), later) == CAP - 60
    edge = PoiHours(poi_id="p5", opens=_t(15, 30), closes=_t(18, 0))
    assert generic_entry_cap(_visit(duration_minutes=60), edge) == CAP - 60


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
