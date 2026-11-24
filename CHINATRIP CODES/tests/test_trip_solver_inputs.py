"""P1-B input-adapter tests: duration tiers (Q1), entry caps (equivalence
with solver.generic_entry_cap on non-open-form cases), travel matrix
coverage, access interval math (E-1 shape), weather conditioning, readiness
report, and G-01 enrichment integration.
"""

from __future__ import annotations

from datetime import time

from app.services.itinerary.models import PoiHours, VisitItem
from app.services.itinerary.solver import generic_entry_cap
from app.services.trip_solver.inputs.access import (
    choose_departure,
    min_to_hhmm,
    outbound_interval,
    return_interval,
)
from app.services.trip_solver.inputs.duration import duration_tier
from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.inputs.hours_caps import (
    entry_cap_minutes,
    is_open_form,
    parse_first_window,
)
from app.services.trip_solver.inputs.weather import weather_conditions
from app.services.trip_solver.snapshot import default_golden_path, load_golden

G01 = default_golden_path()


# ---------- F-15 duration tiers (Q1) ----------


def test_duration_tier_clamps_park_over_240():
    low, typ, high, clamped = duration_tier(300, "park")  # 颐和园 case
    assert (low, typ, high, clamped) == (120, 240, 300, True)


def test_duration_tier_leaves_normal_values():
    assert duration_tier(180, "historic") == (90, 180, 180, False)
    assert duration_tier(60, "tea_experience") == (30, 60, 60, False)
    assert duration_tier(None, None) == (45, 90, 90, False)


# ---------- F-12 hours windows + entry caps ----------


def test_parse_first_window_patterns():
    assert parse_first_window("今天07:30-18:30开放（17:30停止售票）") == (450, 1110)
    assert parse_first_window("周一至周日 00:00-24:00") == (0, 1440)
    assert parse_first_window("03:30-20:30") == (210, 1230)
    assert parse_first_window(None) is None
    assert parse_first_window("无固定开放时间") is None


def test_parse_first_window_allday_statement_r36():
    """R36（南锣鼓巷 vs 前门大街分类分裂）：显式全天声明=数据真值，
    解析为 (0,1440) 开放形态；无信息行（无固定/纯文本）仍 None。"""
    assert parse_first_window("全年全天开放") == (0, 1440)
    assert parse_first_window("全天开放") == (0, 1440)
    assert parse_first_window("周一至周日全天营业") == (0, 1440)
    assert parse_first_window("24小时营业") == (0, 1440)
    assert parse_first_window("24H") == (0, 1440)
    assert parse_first_window("无固定开放时间") is None
    assert parse_first_window("淡季营业") is None


def test_entry_cap_nanluoguxiang_vs_qianmen_r36():
    """R36：同构行（attraction / 全年全天开放 / 90min）必须同口径——
    南锣鼓巷不再是 big-site 960，与前门大街同为 open-form 豁免。
    另兜无 hours 数据的胡同行（street_like 补「巷/胡同」）。"""
    def cap(**kw):
        return entry_cap_minutes(**kw)

    for name in ("南锣鼓巷", "前门大街"):
        assert cap(
            name=name,
            category="attraction",
            best_visit_time="any",
            opening_hours_text="全年全天开放",
            duration_min=90,
            tier=8,
        ) == (None, "open-form")
    # 无 hours 数据的胡同行：街区语义兜住（既有「街」字路径的类内补齐）
    assert cap(
        name="五道营胡同",
        category="attraction",
        best_visit_time="any",
        opening_hours_text=None,
        duration_min=90,
        tier=8,
    ) == (None, "open-form")
    # 无信息行不越权：非街区语义照吃闸（2026-11-17 拍板不动）
    assert cap(
        name="老舍茶馆",
        category="tea_experience",
        best_visit_time="any",
        opening_hours_text=None,
        duration_min=60,
        tier=None,
    ) == (990, "generic")


def test_open_form_semantics():
    assert is_open_form(None) is True  # no hours = street/citywalk
    assert is_open_form((0, 1440)) is True  # 00:00-24:00
    assert is_open_form((210, 1230)) is False  # 03:30-20:30, close < 22:00
    assert is_open_form((390, 1320)) is False  # 06:30 open > 06:00
    assert is_open_form((360, 1320)) is True  # 06:00-22:00 boundary


def test_entry_cap_g01_values():
    def cap(**kw):
        return entry_cap_minutes(**kw)

    # R12-H11/H23：sunrise 卡走晨锁带（≤08:30 开场，锚=升旗真值）
    assert cap(
        name="天安门广场",
        category="attraction",
        best_visit_time="sunrise",
        opening_hours_text="03:30-20:30",
        duration_min=90,
        tier=1,
    ) == (510, "sunrise-band")
    assert cap(
        name="故宫博物院",
        category="museum",
        best_visit_time="any",
        opening_hours_text="…08:30-17:00(16:00停止检票)…",
        duration_min=120,
        tier=1,
    ) == (960, "big-site")  # R12-H23 入场闸 16:00
    assert cap(
        name="慕田峪长城",
        category="historic",
        best_visit_time="any",
        opening_hours_text="今天07:30-18:30开放",
        duration_min=180,
        tier=1,
    ) == (960, "big-site")  # R12-H23
    assert cap(
        name="颐和园",
        category="park",
        best_visit_time="any",
        opening_hours_text="今天06:30-19:00开放",
        duration_min=300,
        tier=1,
    ) == (960, "big-site")  # R12-H23
    assert cap(
        name="老舍茶馆",
        category="tea_experience",
        best_visit_time="any",
        opening_hours_text=None,
        duration_min=60,
        tier=None,
    ) == (
        990,
        "generic",
    )  # P2-B3: no-hours non-street rows take the 晚闸 (2026-11-17 拍板)
    assert cap(
        name="梵高星空艺术馆（王府井旗舰店）",
        category="entertainment",
        best_visit_time="any",
        opening_hours_text="10:00-22:00,21:00停止入场",
        duration_min=90,
        tier=6,
    ) == (None, "evening-cat")
    assert cap(
        name="武康路-安福路街区",
        category="historic",
        best_visit_time="any",
        opening_hours_text="周一至周日 00:00-24:00",
        duration_min=90,
        tier=8,
    ) == (None, "open-form")
    assert cap(
        name="某沉浸式主题街区",
        category="citywalk",
        best_visit_time="any",
        opening_hours_text="10:00-22:00",
        duration_min=240,
        tier=None,
    ) == (None, "theme-block")
    assert cap(
        name="某夜游馆",
        category="historic",
        best_visit_time="any",
        opening_hours_text="17:00-23:00",
        duration_min=120,
        tier=3,
    ) == (None, "evening-only")


def _visit(**kw):
    base = dict(
        name="x",
        poi_id="x",
        city="北京",
        category="attraction",
        day=1,
        best_visit_time="any",
        tier=1,
        duration_minutes=90,
        pinned=False,
        start_time=None,
        location=None,
        stops=None,
        opening_hours=None,
        item_id="v_x",
    )
    base.update(kw)
    return VisitItem(**base)


def test_entry_cap_equivalence_with_solver_on_non_open_form():
    """Model-level cap must match solver.generic_entry_cap whenever the
    window is NOT open-form (open-form exemption is model-only, v2 口径)."""
    cases = [
        dict(
            name="天安门广场",
            category="attraction",
            best_visit_time="sunrise",
            duration_minutes=90,
            tier=1,
        ),
        dict(name="故宫博物院", category="museum", duration_minutes=120, tier=1),
        dict(name="颐和园", category="park", duration_minutes=300, tier=1),
        dict(
            name="梵高星空艺术馆", category="entertainment", duration_minutes=90, tier=6
        ),
    ]
    for case in cases:
        item = _visit(**case)
        window = PoiHours(poi_id="x", opens=time(8, 30), closes=time(17, 0))
        expected = generic_entry_cap(item, window)
        ours, _ = entry_cap_minutes(
            name=case["name"],
            category=case["category"],
            best_visit_time=case.get("best_visit_time", "any"),
            opening_hours_text="08:30-17:00",
            duration_min=case["duration_minutes"],
            tier=case["tier"],
        )
        assert ours == expected, case


# ---------- F-11 travel matrix ----------


def test_travel_matrix_full_coverage_on_g01():
    snapshot, _, _ = load_golden(G01)
    from app.services.trip_solver.inputs.enrich import enrich

    enriched = enrich(snapshot)
    assert enriched.matrix_coverage["coverage_pct"] == 100.0
    assert enriched.matrix_coverage["uncovered"] == []
    measured = [
        (t.from_key, t.to_key)
        for t in snapshot.travel
        if t.source != "haversine" and t.source != "access-profile"
    ]
    for pair in measured:
        assert pair in enriched.matrix


# ---------- F-13 weather ----------


def test_weather_penalizes_rainy_outdoor_only():
    snapshot, _, _ = load_golden(G01)

    class W:
        pass

    cond = ("ct_北京_8", "2026-11-25", "moderate rain")
    out = weather_conditions((cond,), snapshot.candidates)
    key = ("c3", "2026-11-25")  # 慕田峪长城 outdoor
    assert out[key]["penalty"] == 240
    assert out[key]["forbid"] is False
    heavy = weather_conditions(
        (("ct_北京_8", "2026-11-25", "heavy rain"),), snapshot.candidates
    )
    assert heavy[key]["forbid"] is True
    # indoor candidate (故宫) gets no penalty
    assert not any(k[0] == "c4" for k in out)


# ---------- F-14 access intervals (E-1 shape) ----------


def test_access_outbound_matches_e1_timeline():
    snapshot, _, _ = load_golden(G01)
    profile = snapshot.access_profiles[0]
    dep = choose_departure(profile, 9 * 60)  # after 天安门 08:40 + margin
    assert dep == "09:30"
    out = outbound_interval(profile, dep)
    assert out["arrive_poi"] == 11 * 60 + 8  # ≈11:08
    ret = return_interval(profile, 15 * 60 + 8)  # visit ends 15:08
    assert ret["return_depart"] == 15 * 60 + 30
    assert ret["arrive_city"] == 17 * 60 + 8
    assert min_to_hhmm(out["arrive_poi"]) == "11:08"


# ---------- M14 readiness report ----------


def test_readiness_report_computes_gates_honestly():
    snapshot, _, _ = load_golden(G01)
    enriched = enrich(snapshot)
    gates = enriched.readiness["gates"]
    assert gates["hours_parse"]["pass"] is False  # 老舍茶馆 has no hours: 6/7
    assert gates["hours_parse"]["value"] == round(6 / 7, 3)
    assert gates["remote_access_coverage"]["pass"] is True
    assert gates["duration_tier"]["pass"] is True
    assert gates["matrix_coverage"]["pass"] is True
    # G-01 fixture is known-sparse on indoor/rain_ok — the gate must FAIL
    # honestly rather than silently pass (audit M14 note).
    assert gates["indoor_rain_ok"]["pass"] is False
    assert enriched.readiness["all_pass"] is False


def test_enrich_g01_caps_and_tiers():
    snapshot, _, _ = load_golden(G01)
    enriched = enrich(snapshot)
    by_name = {c.name: c.cid for c in snapshot.candidates}
    # R12-H11：语料天安门 bvt=sunrise → 晨锁带
    assert enriched.caps[by_name["天安门广场"]] == (510, "sunrise-band")
    assert enriched.caps[by_name["老舍茶馆"]] == (
        990,
        "generic",
    )  # P2-B3: hours-gap rows keep the cap unless street-like
    assert enriched.caps[by_name["梵高星空艺术馆（王府井旗舰店）"]] == (
        None,
        "evening-cat",
    )
    assert enriched.tiers[by_name["颐和园"]][1:3] == (240, 300)  # clamped typ
