"""P1-C2 model-core tests: E-1 shape with Tiananmen pin, C-05 endpoint caps,
C-06 remote-day exclusivity with the morning-anchor exception, C-07 city
coherence, C-08 access intervals (card ≡ leg), determinism.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.snapshot import default_golden_path, load_golden
from app.services.trip_solver.types import (
    CandidateItem,
    FactSnapshot,
    FixedPin,
    RequestedItem,
    TripRequest,
)

G01 = default_golden_path()


def _with_pin(snapshot, pin: FixedPin):
    request = replace(snapshot.request, pins=(pin,))
    return replace(snapshot, request=request)


def test_e1_shape_tiananmen_then_direct_mutianyu_departure():
    snapshot, _, _ = load_golden(G01)
    # 天安门 07:10 升旗钉 → 08:40 散场 + taxi → 09:30 班 → 11:08 到慕田峪
    snapshot = _with_pin(snapshot, FixedPin(rid="r1", day=1, start_min=7 * 60 + 10))
    enriched = enrich(snapshot)
    sol = solve_snapshot(enriched)
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status

    by_cid = {c.cid: c for c in snapshot.candidates}
    tian = next(i for i in sol.items if by_cid[i.cid].name == "天安门广场")
    mty = next(i for i in sol.items if by_cid[i.cid].name == "慕田峪长城")
    assert (tian.day, tian.start_min) == (1, 430)  # pin 07:10 immovable
    assert 475 <= tian.end_min <= 520  # 档位 [45,90]：允许缩时（F-20）
    # 卡≡腿：start == dep + ride + last_mile（dep 属班次表值域）
    legs = sol.access_legs
    assert len(legs) == 1
    leg = legs[0]
    assert leg["depart_min"] in {450, 510, 570, 630}  # 只取班次表值
    assert mty.start_min == leg["depart_min"] + 90 + 8
    # 晨锚先于出班：dep ≥ 天安门.end + taxi
    assert leg["depart_min"] >= tian.end_min + 15
    # 早班偏好属 P1-D 目标④（makespan/travel），C2 阶段任一合法班次均可
    assert leg["return_depart_min"] >= mty.end_min + 8
    assert leg["arrive_city_min"] == leg["return_depart_min"] + 90 + 8
    # 远郊日：除晨锚外不得有其它必去/补点
    remote_day_items = [i for i in sol.items if i.day == mty.day]
    names_remote_day = {by_cid[i.cid].name for i in remote_day_items}
    assert names_remote_day == {"天安门广场", "慕田峪长城"}
    assert not any(by_cid[i.cid].name == "老舍茶馆" for i in remote_day_items)
    # 其它必去落在另外一天
    others = {by_cid[i.cid].name for i in sol.items if i.day != mty.day}
    assert {"故宫博物院", "天坛", "颐和园"} <= others

    # 早班偏好属 P1-D 目标④（makespan/travel），C2 阶段任一合法班次均可
    # （确定性由幂等测试锁定）；这里只锁 C-08 结构不变量。
    legs = sol.access_legs
    assert len(legs) == 1
    leg = legs[0]
    assert leg["arrive_poi_min"] == leg["depart_min"] + 90 + 8  # 卡≡腿
    assert leg["return_depart_min"] >= mty.end_min + 8  # 散场 +8 → 回程班
    assert leg["arrive_city_min"] == leg["return_depart_min"] + 90 + 8


def test_e1_idempotent_and_deterministic():
    snapshot, _, _ = load_golden(G01)
    snapshot = _with_pin(snapshot, FixedPin(rid="r1", day=1, start_min=430))
    enriched = enrich(snapshot)
    a = solve_snapshot(enriched)
    b = solve_snapshot(enriched)
    assert [(i.cid, i.day, i.start_min, i.end_min) for i in a.items] == [
        (i.cid, i.day, i.start_min, i.end_min) for i in b.items
    ]
    assert a.access_legs == b.access_legs


def test_remote_day_has_no_unrequested_fill():
    snapshot, _, _ = load_golden(G01)
    enriched = enrich(snapshot)
    sol = solve_snapshot(enriched)
    by_cid = {c.cid: c for c in snapshot.candidates}
    mty = next(i for i in sol.items if by_cid[i.cid].name == "慕田峪长城")
    same_day = [i for i in sol.items if i.day == mty.day]
    # 老舍茶馆是未请求补点（fill），不得出现在远郊日
    assert not any(by_cid[i.cid].name == "老舍茶馆" for i in same_day)
    # 至多一个晨锚（本例无 pin，天安门在远郊日 ≤10:30）
    anchors = [
        i for i in same_day if by_cid[i.cid].rid and by_cid[i.cid].name != "慕田峪长城"
    ]
    assert len(anchors) <= 1
    for a in anchors:
        assert a.start_min <= 630


def test_departure_day_cap():
    snapshot, _, _ = load_golden(G01)
    request = replace(snapshot.request, departure_time="18:00")
    snapshot = replace(snapshot, request=request)
    sol = solve_snapshot(enrich(snapshot))
    assert sol.status in ("OPTIMAL", "FEASIBLE")
    for it in sol.items:
        if it.day == snapshot.request.days:
            assert it.end_min <= 18 * 60 - 90  # dep 18:00 − 90 缓冲 = 16:30


def test_arrival_day_floor():
    snapshot, _, _ = load_golden(G01)
    request = replace(snapshot.request, arrival_time="09:00")
    snapshot = replace(snapshot, request=request)
    sol = solve_snapshot(enrich(snapshot))
    for it in sol.items:
        if it.day == 1:
            assert it.start_min >= 9 * 60 + 150  # 落地 +2.5h = 11:30


def test_multi_city_never_same_day():
    a = CandidateItem(
        cid="ca",
        name="甲",
        poi_id="pa",
        kind="requested",
        rid="r1",
        category="attraction",
        opening_hours="09:00-17:00",
        suggested_duration_min=60,
        lon=116.40,
        lat=39.90,
        city="北京",
    )
    b = CandidateItem(
        cid="cb",
        name="乙",
        poi_id="pb",
        kind="requested",
        rid="r2",
        category="attraction",
        opening_hours="09:00-17:00",
        suggested_duration_min=60,
        lon=121.47,
        lat=31.23,
        city="上海",
    )
    snapshot = FactSnapshot(
        schema_version=1,
        request=TripRequest(
            days=1,
            cities=("北京", "上海"),
            musts=(
                RequestedItem(rid="r1", name="甲", poi_id="pa"),
                RequestedItem(rid="r2", name="乙", poi_id="pb"),
            ),
        ),
        candidates=(a, b),
        source="synthetic",
    )
    sol = solve_snapshot(enrich(snapshot))
    # 同城互斥：一天内不能两城同排 → 一个落 unplaced
    assert len(sol.items) == 1
    assert len(sol.unplaced) == 1
