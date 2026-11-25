# -*- coding: utf-8 -*-
"""R29 餐厅候选「评分 × 地理」（2026-11-24 用户令
「WHY RESTAURANTS ARE NOT PROPOSED BY RATING AND GEO INFORMATION」+
「WE HV RESTRANTS IN BOTH POIS AND RESTRANT TABLES」+「ALWAYS USE CP-SAT」）。

覆盖：
1. select_geo_rated：评分闸/半径闸/每簇配额/同名去重/总数上限（R41 簇轮转）；
2. cuisine_key 读两表声明菜系（cuisine/cuisine_group），槽位时段闸不再漏行；
3. 引擎候选池：restaurants 表行按评分×地理进池（meal_slot=any、quality=评分分）；
4. 地理半边（R41 硬闸）：餐馆只能落在「附近有景点在场」的天——远店全程不可选；
5. 槽位时段闸：无菜系键的餐卡同样「午槽<15:00 / 晚槽≥15:00」（倒挂不可行）。
"""

from __future__ import annotations

from types import SimpleNamespace

from ortools.sat.python import cp_model
from test_brief_text_input import SitesStore

from app.services.meal_geo import select_geo_rated
from app.services.trip_solver.inputs.cuisine import cuisine_key
from app.services.trip_solver.live import snapshot_from_request
from app.services.trip_solver.model.c09_c16 import (
    MEAL_NEAR_SIGHT_KM,
    _meal_near_gate,
    _r12d_hard_gates,
)


def _row(name, lon, lat, rating, count=None):
    return {
        "name": name,
        "category": "food",
        "location": (lon, lat),
        "rating": rating,
        "rating_count": count,
        "source_poi_id": name,
    }


class _GeoStore(SitesStore):
    """底库桩 + restaurants 表行（真库查询由只读探针覆盖，单测不打库）。"""

    def __init__(self, geo_rows=None, **kw):
        super().__init__(**kw)
        self._geo_rows = list(geo_rows or [])

    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        return []

    def restaurant_rows_in_city(self, city):
        return list(self._geo_rows)


# ------------------------------------------------------------------ 选择器


def test_select_geo_rated_keeps_best_rated_within_radius():
    rows = [
        _row("近低分", 116.4000, 39.9100, 4.1),
        _row("近高分", 116.4010, 39.9110, 4.9, 800),
        _row("远高分", 116.7000, 39.9100, 5.0, 3000),  # ~25km 外，出 2km 闸
        _row("无评分", 116.4020, 39.9120, None),
        _row("近高分", 116.4010, 39.9110, 4.6, 10),  # 同名低配重复行
    ]
    picked = select_geo_rated(
        rows,
        [(116.4000, 39.9100)],
        radius_km=2.0,
        per_cluster=2,
        limit=4,
        min_rating=4.0,
    )
    assert [r["name"] for r in picked] == ["近高分", "近低分"]


def test_select_geo_rated_per_cluster_cap_and_limit():
    rows = [
        _row("A1", 116.4000, 39.9100, 4.9, 10),
        _row("A2", 116.4005, 39.9105, 4.8, 10),
        _row("B1", 116.5000, 39.9500, 5.0, 10),
        _row("B2", 116.5005, 39.9505, 4.7, 10),
    ]
    anchors = [(116.4000, 39.9100), (116.5000, 39.9500)]
    # 每簇 1 家 + 上限 2：两簇各取头名（余量补足见 R41 欠填充测试）
    assert [
        r["name"] for r in select_geo_rated(rows, anchors, per_cluster=1, limit=2)
    ] == [
        "A1",
        "B1",
    ]
    assert len(select_geo_rated(rows, anchors, per_cluster=2, limit=3)) == 3


def test_select_geo_rated_no_anchor_keeps_old_pool():
    rows = [_row("甲", 116.4, 39.91, 4.9)]
    assert select_geo_rated(rows, []) == []


# ------------------------------------------------------------------ 菜系键


def test_cuisine_key_reads_declared_cuisine_fields():
    # 店名不含菜系词、但库里声明了 cuisine_group（restaurants 表北京 550/550）
    assert (
        cuisine_key(
            {
                "category": "food",
                "name": "北京新青海喜来登酒店·青海餐厅",
                "cuisine_group": "西北菜",
            }
        )
        == "西北菜"
    )
    assert (
        cuisine_key({"category": "food", "name": "翠华", "cuisine": "粤菜"}) == "粤菜"
    )
    assert cuisine_key({"category": "food", "name": "没有菜系的行"}) is None


# --------------------------------------------------------------- 引擎候选池


def test_snapshot_pool_takes_rated_rows_by_geo():
    store = _GeoStore(
        [
            _row("近高分店", 116.4000, 39.9100, 4.8, 500),
            _row("近低分店", 116.4005, 39.9105, 4.2, 10),
            _row("远高分店", 116.9000, 40.2000, 5.0, 999),
        ],
        known={
            ("北京", "故宫博物院"): {
                "name": "故宫博物院",
                "city": "北京",
                "category": "museum",
                "location": (116.3970, 39.9160),
            }
        },
    )
    snap = snapshot_from_request(
        cities=["北京"],
        days=2,
        start_date="2026-12-01",
        musts=["故宫博物院"],
        store=store,
    )
    foods = [c for c in snap.candidates if c.category == "food"]
    names = {c.name for c in foods}
    # R41：每簇午/晚双配额（MEAL_GEO_PER_CLUSTER=2）——同簇前两名都进池，
    # 第二名是被避/被点时的备选；25km 外的远店仍不进池。
    assert "近高分店" in names
    assert "近低分店" in names
    assert "远高分店" not in names  # 25km 外，不进 geo 池
    assert all(c.meal_slot == "any" for c in foods)  # 顶餐卡的 any 槽
    high = next(c for c in foods if c.name == "近高分店")
    low = next(c for c in foods if c.name == "近低分店")
    # R41：质量分吃可信度评分（4.8×500 → 47.7 量级 → 48），仍 >40；
    # 高评论数店的质量分必须高过小样本店（评分数进模型）。
    assert high.quality and high.quality > 40
    assert high.quality > low.quality


# ----------------------------------------------------------- 地理半边（软罚）


def _presence_grid(model, cids, days):
    return {
        (cid, day): model.NewBoolVar("p_%s_%d" % (cid, day))
        for cid in cids
        for day in days
    }


def test_meal_near_gate_picks_near_day_and_drops_far_shop():
    """R41：软罚 400 → 餐馆侧就近硬闸；同样的结局（近店落近天、远店不进解）。"""
    model = cp_model.CpModel()
    sight = SimpleNamespace(
        cid="s1", category="museum", meal_slot=None, lon=116.400, lat=39.910, rid=None
    )
    near = SimpleNamespace(
        cid="f1", category="food", meal_slot="any", lon=116.401, lat=39.911, rid=None
    )
    far = SimpleNamespace(
        cid="f2", category="food", meal_slot="any", lon=117.200, lat=40.300, rid=None
    )
    days = [1, 2]
    presence = _presence_grid(model, ["s1", "f1", "f2"], days)
    bundle = SimpleNamespace(model=model, presence=presence, days=days)
    enriched = SimpleNamespace(snapshot=SimpleNamespace(candidates=[sight, near, far]))
    _meal_near_gate(bundle, enriched)

    # 景点只在第 1 天在场；餐卡奖励 190（≈FILL_REWARD+quality 量级）。
    # 没有罚项——「不就近」直接不可行，不靠目标值压。
    model.Add(presence[("s1", 1)] == 1)
    model.Add(presence[("s1", 2)] == 0)
    reward = 190 * sum(presence[(cid, day)] for cid in ("f1", "f2") for day in days)
    model.Maximize(reward)
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    # 近店落在有景点的第 1 天（第 2 天无景点在场：硬闸不可行）
    assert solver.Value(presence[("f1", 1)]) == 1
    assert solver.Value(presence[("f1", 2)]) == 0
    # 远店 2.5km 内无池内景点：全程不可选（旧版是逐日罚 400 的软压）
    assert solver.Value(presence[("f2", 1)]) == 0
    assert solver.Value(presence[("f2", 2)]) == 0
    assert MEAL_NEAR_SIGHT_KM > 0


# --------------------------------------------------- 槽位时段闸（无菜系键也盖）


def _band_model(start_min: int) -> str:
    model = cp_model.CpModel()
    cand = SimpleNamespace(
        cid="f1", category="food", meal_slot="any", cuisine=None, rid=None
    )
    presence = {("f1", 1): model.NewBoolVar("p_f1_1")}
    start = {("f1", 1): model.NewIntVar(0, 1440, "s_f1_1")}
    meal_bound = {
        ("f1", 1, "lunch"): model.NewBoolVar("bl"),
        ("f1", 1, "dinner"): model.NewBoolVar("bd"),
    }
    bundle = SimpleNamespace(
        model=model, presence=presence, start=start, meal_bound=meal_bound, days=[1]
    )
    enriched = SimpleNamespace(snapshot=SimpleNamespace(candidates=[cand]))
    _r12d_hard_gates(bundle, enriched)
    model.Add(presence[("f1", 1)] == 1)
    model.Add(meal_bound[("f1", 1, "lunch")] == 1)
    model.Add(meal_bound[("f1", 1, "dinner")] == 0)
    model.Add(start[("f1", 1)] == start_min)
    status = cp_model.CpSolver().Solve(model)
    return "INFEASIBLE" if status == cp_model.INFEASIBLE else "FEASIBLE"


def test_slot_band_gate_covers_cuisineless_food_cards():
    # 17:00 的「午餐」= 倒挂（旧闸只盖有菜系键的行，新候选整条漏过）
    assert _band_model(17 * 60) == "INFEASIBLE"
    assert _band_model(12 * 60) == "FEASIBLE"
