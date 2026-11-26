# -*- coding: utf-8 -*-
"""R20 regression tests: evening/sunset POIs land in the evening band.

库内夜游类（pois.best_visit_time=evening/sunset，如「大唐不夜城步行街」
evening-manual、珠江夜游、长安十二时辰主题街区）此前在引擎里零晚排力——
偏好层唯一的强晚排只认 show。修复=偏好层晚排带 EVENING_LATE_BANDS +
夜属性卡豁免必去大点晚开罚带（否则 −120/+240 同层精确对消）+ 晚餐 COVER
放行夜属性大时长卡。

钉住的回归面：
1. evening 必去街落到 ≥17:00（修复前探针实锤 09:30/10:00/12:01）；
2. 大时长白天对手在场时 evening 必去仍落晚上；
3. sunset 同享晚排带；
4. 夜街盖住晚餐核的日型可解（COVER 扩展不产生不可行）；
5. 无夜属性的控制组不被动（白天必去大点照旧早排 ≤12:30）。
"""

from app.services.trip_solver.entry import ENGINE_CPSAT, solve_trip
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    TripRequest,
)

STREET_LON, STREET_LAT = 108.9554, 34.2116


def _cand(cid, name, dur, lon, lat, hours, bvt=None):
    return CandidateItem(
        cid=cid,
        name=name,
        poi_id="poi_" + cid,
        kind="fill",
        category="sight",
        tier=4,
        lon=lon,
        lat=lat,
        opening_hours=hours,
        best_visit_time=bvt,
        suggested_duration_min=dur,
        city="西安",
    )


def _snapshot(days, street_dur, street_bvt, rivals):
    req = RequestedItem(
        rid="r1",
        name="大唐不夜城步行街",
        poi_id="poi_c1",
        kind="must",
    )
    street = CandidateItem(
        cid="c1",
        name="大唐不夜城步行街",
        poi_id="poi_c1",
        kind="requested",
        rid="r1",
        category="sight",
        tier=4,
        lon=STREET_LON,
        lat=STREET_LAT,
        opening_hours="全天开放",
        best_visit_time=street_bvt,
        suggested_duration_min=street_dur,
        city="西安",
    )
    request = TripRequest(
        days=days,
        cities=("西安",),
        start_date="2026-12-01",
        musts=(req,),
        wishes=(),
    )
    snap = FactSnapshot(
        schema_version=2,
        request=request,
        candidates=(street,) + tuple(rivals),
        source="r20-test",
    )
    out = solve_trip(snap, flag=ENGINE_CPSAT, budget_s=20.0, fail_loud=True)
    return out.solution, street.cid


def _street_start(sol, cid):
    items = [i for i in sol.items if i.cid == cid]
    assert items, "street must be placed; unplaced=%r" % (sol.unplaced,)
    return items[0].start_min


def _light_rivals():
    return (
        _cand("c2", "西安钟楼", 60, 108.9428, 34.2610, "08:30-18:00"),
        _cand("c3", "小雁塔", 75, 108.9375, 34.2360, "09:00-17:00"),
        _cand("c4", "大兴善寺", 60, 108.9635, 34.2250, "09:00-17:00"),
    )


def _big_rivals():
    return (
        _cand("c2", "秦始皇帝陵博物院", 180, 109.2785, 34.3852, "08:30-17:00"),
        _cand("c3", "陕西历史博物馆", 120, 108.9530, 34.2225, "09:00-17:30"),
        _cand("c4", "西安城墙", 120, 108.9390, 34.2520, "08:00-20:00"),
    )


def test_evening_must_street_lands_in_evening():
    sol, cid = _snapshot(2, 90, "evening", _light_rivals())
    assert sol.status == "OPTIMAL"
    assert _street_start(sol, cid) >= 17 * 60


def test_evening_must_with_big_rivals_lands_in_evening():
    sol, cid = _snapshot(2, 180, "evening", _big_rivals())
    assert sol.status == "OPTIMAL"
    assert _street_start(sol, cid) >= 17 * 60


def test_sunset_wish_lands_in_dusk_window():
    # R23 重祝福：sunset 从晚排带移交 C-01 黄昏窗 [16:00,19:00]（legacy
    # _BEST_VISIT_WINDOWS 镜像）——end 须落在窗内，不再被晚排带拉进夜里。
    sol, cid = _snapshot(2, 90, "sunset", _light_rivals())
    assert sol.status == "OPTIMAL"
    s = _street_start(sol, cid)
    assert 16 * 60 <= s
    assert s + 90 <= 19 * 60


def test_evening_street_covering_dinner_core_solves():
    # 18:00 开场的夜街盖住 18-19 晚餐核：COVER 扩展后占位晚餐槽取消，
    # 日型必须可解且夜街仍落晚上（修复前会被 21:00 日窗/餐窗挤压回白天）。
    sol, cid = _snapshot(1, 180, "evening", _light_rivals())
    assert sol.status == "OPTIMAL"
    assert _street_start(sol, cid) >= 17 * 60


def test_non_evening_big_must_keeps_daytime_band():
    # 控制组：无夜属性的必去大点不吃晚排带，照旧被必去晚开罚带压在 ≤12:30。
    sol, cid = _snapshot(2, 180, None, _big_rivals())
    assert sol.status == "OPTIMAL"
    assert _street_start(sol, cid) <= 12 * 60 + 30
