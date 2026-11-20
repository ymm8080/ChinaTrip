# -*- coding: utf-8 -*-
"""R13h twin-channel regression tests (legacy-parity ground truth)."""

from __future__ import annotations

from app.services.trip_solver.inputs.twins import combo_same_day, twin_gate_km
from app.services.trip_solver.types import CandidateItem


def _cand(name, *, category="sight", poi_id=None, lon=None, lat=None):
    return CandidateItem(
        cid="c-%s" % name,
        name=name,
        poi_id=poi_id,
        kind="fill",
        category=category,
        lon=lon,
        lat=lat,
    )


def test_twin_gate_channels_match_legacy():
    """通道→闸分档与 legacy _same_visit 当日口径一致（probe 实测基准）。"""
    # 同内容配套（大足）：content 通道 → 30km
    assert twin_gate_km(_cand("大足石刻博物馆"), _cand("大足石刻")) == 30.0
    # 同票家族（兵马俑/华清）：heritage → 10km
    assert twin_gate_km(_cand("秦始皇帝陵博物院(兵马俑)"), _cand("秦始皇陵")) == 10.0
    assert twin_gate_km(_cand("华清宫"), _cand("临潼区华清池景区")) == 10.0
    # 同地名（朱家角）：town → 2km
    assert twin_gate_km(_cand("朱家角古镇"), _cand("朱家角镇")) == 2.0
    # 演出桶：show → 2km
    assert twin_gate_km(_cand("蜀风雅韵"), _cand("川剧变脸表演")) == 2.0
    # 大小兄弟：sibling → 30km
    assert twin_gate_km(_cand("大雁塔北广场"), _cand("小雁塔")) is not None
    # 不同站：无闸
    assert twin_gate_km(_cand("大雁塔"), _cand("大慈恩寺")) is None
    # poi_id 相等：无条件
    assert twin_gate_km(_cand("甲", poi_id="p1"), _cand("乙", poi_id="p1")) == 0.0


def test_museum_umbrella_combo_exempt_and_same_day():
    """11-07 终裁：博物馆×伞形挂牌不互斥（连排组合），双在场⇒同日。"""
    museum = _cand("成都武侯祠博物馆", category="museum")
    combo = _cand("武侯祠·锦里")
    assert twin_gate_km(museum, combo) is None  # 组合豁免不互斥
    assert combo_same_day(museum, combo) is True  # 但双在场必须同日
    # 真孪生（content 命中）不是组合对
    dazu = _cand("大足石刻博物馆", category="museum")
    assert combo_same_day(dazu, _cand("大足石刻")) is False


def test_hotel_and_street_guards():
    """酒店卡不参与；街区×宴/演劈叉不并（11-08 拍板）。"""
    hotel = _cand("某酒店", category="hotel")
    assert twin_gate_km(hotel, _cand("同名景区")) is None
    street = _cand("锦里古街", category="citywalk")
    feast = _cand("锦里宴", category="entertainment")
    assert twin_gate_km(street, feast) is None


def test_engine_twin_pair_single_presence(monkeypatch):
    """引擎级：同地名双行（朱家角类）一次行程至多一张卡。"""

    monkeypatch.setenv("TRIP_SOLVER", "cpsat")
    from app.services.trip_solver.inputs.enrich import enrich
    from app.services.trip_solver.model.solve import solve_snapshot
    from app.services.trip_solver.snapshot import (
        default_golden_path,
        load_golden,
    )
    from app.services.trip_solver.types import (
        FactSnapshot,
    )

    def _mk(name, cid):
        return CandidateItem(
            cid=cid,
            name=name,
            kind="fill",
            category="sight",
            lon=121.05,
            lat=31.11,
            suggested_duration_min=90,
        )

    snapshot, expect, prov = load_golden(default_golden_path())
    # 用 g01 快照的 request 形状换候选池（同地名双行同坐标）
    twin_a = _mk("朱家角古镇", "tz-a")
    twin_b = _mk("朱家角镇", "tz-b")
    req = snapshot.request
    new_snapshot = FactSnapshot(
        schema_version=snapshot.schema_version,
        request=req,
        candidates=[*snapshot.candidates, twin_a, twin_b],
    )
    sol = solve_snapshot(enrich(new_snapshot), budget_s=3.0)
    picked = {it.cid for it in sol.items}
    both = twin_a.cid in picked and twin_b.cid in picked
    assert not both, "同地名双行不得双在场（朱家角类防双卡）"
