# -*- coding: utf-8 -*-
"""R12 流式行程（2026-11-19 用户拍板）：天安门后应该在去下一个景点的路上，
而不是空着等到午餐卡。

用户可见不变量：
1. 绑定真餐馆（烤鸭店）不再被 11:30 餐窗钳死——上午锚收尾后按营业时间
   +走行缝流式直排（c09 bound_any 分流）；
2. >=45 分钟的同日空档出现可见交通桥卡（assembly/bridges）——「路上」
   不再是死空气；
3. 桥卡是渲染件不是填充活动——hotfix 的远郊清场 pass 不撤它。
"""

from __future__ import annotations

from datetime import time

from app.services.itinerary.hotfix_1117 import evict_pre_remote_fillers
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.trip_solver.assembly.bridges import (
    BRIDGE_GAP_MIN,
    attach_gap_bridges,
)
from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.snapshot import snapshot_from_dict


def _cand(
    cid: str,
    *,
    name: str | None = None,
    rid: str | None = None,
    category: str = "attraction",
    hours: str = "08:00-20:00",
    duration: int = 60,
    **extra,
):
    return {
        "cid": cid,
        "name": name or cid,
        "poi_id": f"p-{cid}",
        "kind": "requested" if rid else "fill",
        "rid": rid,
        "category": category,
        "opening_hours": hours,
        "suggested_duration_min": duration,
        **extra,
    }


def _snap(candidates, *, days: int = 1, musts=(), pins=()):
    req = [
        {
            "rid": r if isinstance(r, str) else r["rid"],
            "name": r if isinstance(r, str) else r.get("name", r["rid"]),
            "poi_id": f"p-{r}" if isinstance(r, str) else r.get("poi_id"),
            "kind": "must",
            "importance": 3,
        }
        for r in musts
    ]
    raw = {
        "schema_version": 2,
        "request": {
            "days": days,
            "cities": ("北京",),
            "start_date": None,
            "musts": req,
            "pins": pins,
        },
        "candidates": candidates,
        "access_profiles": [],
        "travel": [],
        "weather": [],
        "source": "synthetic-r12",
    }
    return snapshot_from_dict(raw)


def _card(item_id, name, cat, start, end, **extra):
    return VisitItem(
        item_id=item_id,
        name=name,
        category=cat,
        city="北京",
        day=1,
        start_time=time(start // 60, start % 60),
        end_time=time(end // 60, end % 60),
        duration_minutes=end - start,
        **extra,
    )


def _plan(*items):
    return ItineraryPlan(
        itinerary_id="it-r12",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
    )


def _bridges(plan):
    return [
        i for i in plan.days[0].items if str(i.item_id or "").startswith("leg-bridge-")
    ]


# ---------- 1) 绑定真餐馆流式直排（不再 11:30 餐窗钳制） ----------


def test_bound_restaurant_flows_after_anchor_not_meal_window():
    """用户把烤鸭钉在 10:30（锚 08:30-10:00 直后排）：R12 前餐窗硬钳
    [11:30,12:30] 会把绑定午餐判成 INFEASIBLE；R12 后必须可解、照常
    绑定顶卡（时刻=钉=流式解），晚餐占位卡照旧守窗。"""
    site = _cand(
        "site", rid="r-site", category="historic", hours="08:30-12:00", duration=90
    )
    duck = _cand(
        "duck",
        rid="r-duck",
        name="烤鸭店",
        category="food",
        hours="10:00-22:30",
        duration=60,
        meal_slot="lunch",
    )
    snap = _snap(
        [site, duck],
        musts=("r-site", "r-duck"),
        pins=(
            {"rid": "r-site", "day": 1, "start_min": 510},
            {"rid": "r-duck", "day": 1, "start_min": 630},  # 10:30 吃烤鸭
        ),
    )
    sol = solve_snapshot(enrich(snap))
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    placed = {i.cid: i for i in sol.items}
    d = placed["duck"]
    assert d.start_min == 630 and d.end_min == 690  # 钉住=流式解（旧钳下不可解）
    lunch = next(m for m in sol.meal_anchors if m["slot"] == "lunch")
    assert lunch["bound_cid"] == "duck"
    assert lunch["start_min"] == 630
    assert lunch["end_min"] == 690
    dinner = next(m for m in sol.meal_anchors if m["slot"] == "dinner")
    assert dinner["bound_cid"] is None  # 未绑的另一槽照常占位守窗
    assert 17 * 60 <= dinner["start_min"] <= 19 * 60 + 30


def test_placeholder_meal_keeps_window_when_no_restaurant_bound():
    """无真餐馆时系统占位餐卡照旧守窗（R12 只解绑定的钳）。"""
    site = _cand("site", rid="r-site", category="historic", duration=480)
    snap = _snap([site], musts=("r-site",))
    sol = solve_snapshot(enrich(snap))
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    lunch = next(m for m in sol.meal_anchors if m["slot"] == "lunch")
    assert 11 * 60 + 30 <= lunch["start_min"] <= 12 * 60 + 30
    assert lunch["bound_cid"] is None


# ---------- 2) 空档交通桥卡 ----------


def test_big_gap_gets_visible_transit_bridge():
    """天安门 10:00 收尾 -> 烤鸭店 11:02（62 分钟路上）：空档必须有一张
    可见「前往」交通卡，时间线不留死空气。"""
    # 腿字段挂在「前卡」上（annotate 的口径：a -> b 的腿写在 a 上）
    a = _card(
        "v1",
        "天安门广场",
        "attraction",
        8 * 60 + 30,
        10 * 60,
        poi_id="p-1",
        next_leg_mode="walk",
        next_leg_minutes=62,
    )
    duck = _card(
        "meal-lunch-1",
        "烤鸭店（故宫店）",
        "food",
        11 * 60 + 2,
        11 * 60 + 57,
        poi_id="p-2",
    )
    plan = attach_gap_bridges(_plan(a, duck))
    got = _bridges(plan)
    assert len(got) == 1
    b = got[0]
    assert b.category == "transfer" and b.synthetic
    assert b.start_time == time(10, 0)
    assert b.end_time == time(11, 2)
    assert "前往下一站" in b.name and "62" in b.name
    assert "烤鸭店" not in b.name  # 不内嵌目的地名（防名字检索误认）
    ids = [i.item_id for i in plan.days[0].items]
    assert ids == ["v1", "leg-bridge-d1-1", "meal-lunch-1"]


def test_bridge_fallback_name_without_leg_metadata():
    a = _card("v1", "钟鼓楼", "historic", 9 * 60, 10 * 60, poi_id="p-1")
    b = _card("v2", "南锣鼓巷", "street", 11 * 60 + 30, 12 * 60 + 30, poi_id="p-2")
    plan = attach_gap_bridges(_plan(a, b))
    got = _bridges(plan)
    assert len(got) == 1
    assert "前往下一站" in got[0].name and "自由安排" in got[0].name


def test_small_gap_and_system_cards_not_bridged():
    a = _card("v1", "天安门广场", "attraction", 8 * 60 + 30, 10 * 60, poi_id="p-1")
    near = _card(
        "v2", "故宫博物院", "museum", 10 * 60 + 30, 12 * 60 + 30, poi_id="p-3"
    )  # 30 分钟缝：leg 元数据足够，不出桥
    assert _bridges(attach_gap_bridges(_plan(a, near))) == []

    # 占位午餐做目的地：不桥（名字判占位——poi 缺失不误杀命名卡）
    ph = _card("meal-lunch-1", "午餐", "food", 11 * 60 + 30, 12 * 60 + 30)
    assert _bridges(attach_gap_bridges(_plan(a, ph))) == []
    # 命名餐卡（真餐厅顶卡）：常无 poi_id 但带坐标——必须可桥
    from app.services.itinerary.models import GeoPoint

    duck_nopoi = _card(
        "meal-lunch-1",
        "烤鸭店（故宫店）",
        "food",
        11 * 60 + 30,
        12 * 60 + 30,
        location=GeoPoint(lon=116.41, lat=39.92),
    )
    got_duck = _bridges(attach_gap_bridges(_plan(a, duck_nopoi)))
    assert len(got_duck) == 1 and got_duck[0].end_time == time(11, 30)

    # 换程/回城卡做起点：不桥
    ret = _card("access-return-v1", "回城", "transfer", 15 * 60 + 30, 17 * 60)
    din = _card("meal-dinner-1", "晚饭（烤鸭）", "food", 19 * 60, 20 * 60, poi_id="p-4")
    assert _bridges(attach_gap_bridges(_plan(ret, din))) == []


def test_nested_host_span_and_multi_gap():
    """嵌套餐卡并入宿主区间（不产生假空档）；一天两个真空档出两张桥。"""
    before = _card("v0", "天安门广场", "attraction", 8 * 60 + 30, 10 * 60, poi_id="p-0")
    host = _card("v1", "故宫博物院", "museum", 12 * 60 + 30, 14 * 60 + 30, poi_id="p-1")
    nested = _card("meal-lunch-1", "午餐", "food", 12 * 60 + 30, 13 * 60 + 30)
    nxt = _card("v2", "天坛", "temple", 15 * 60 + 15, 17 * 60 + 45, poi_id="p-2")
    plan = attach_gap_bridges(_plan(before, host, nested, nxt))
    got = _bridges(plan)
    assert len(got) == 2
    assert got[0].start_time == time(10, 0) and got[0].end_time == time(12, 30)
    assert got[1].start_time == time(14, 30) and got[1].end_time == time(15, 15)


# ---------- 3) 桥卡不是填充活动（hotfix 不撤） ----------


def test_bridge_card_survives_pre_remote_eviction():
    remote = _card(
        "v9", "慕田峪长城", "historic", 12 * 60 + 8, 15 * 60 + 8, poi_id="p-9"
    )
    anchor = _card(
        "v1",
        "天安门广场",
        "attraction",
        7 * 60 + 10,
        8 * 60 + 40,
        poi_id="p-1",
        pinned=True,
    )
    bridge = _card(
        "leg-bridge-d1-1",
        "🚕 乘车前往「慕田峪长城」",
        "transfer",
        9 * 60 + 30,
        11 * 60 + 8,
    )
    plan = _plan(anchor, bridge, remote)
    evict_pre_remote_fillers(plan)
    ids = [i.item_id for i in plan.days[0].items]
    assert "leg-bridge-d1-1" in ids  # 交通桥卡不是填充活动，不撤
    assert "v1" in ids and "v9" in ids


def test_attach_gap_bridges_is_idempotent():
    """读闸 heal 挪卡后重挂：先清后挂——两次调用不双卡；挪卡后的
    新空档照样补桥。"""
    a = _card(
        "v1",
        "天安门广场",
        "attraction",
        8 * 60 + 30,
        10 * 60,
        poi_id="p-1",
        next_leg_mode="walk",
    )
    duck = _card(
        "meal-lunch-1", "烤鸭店", "food", 11 * 60 + 2, 12 * 60 + 2, poi_id="p-2"
    )
    plan = attach_gap_bridges(_plan(a, duck))
    assert len(_bridges(plan)) == 1
    # heal 挪卡：烤鸭改到 12:30（新空档 10:00→12:30）后重挂——仍只有一桥
    duck.start_time = time(12, 30)
    duck.end_time = time(13, 30)
    duck.duration_minutes = 60
    plan = attach_gap_bridges(plan)
    got = _bridges(plan)
    assert len(got) == 1
    assert got[0].end_time == time(12, 30)  # 桥跟到新空档


def test_bridge_gap_min_constant():
    assert BRIDGE_GAP_MIN == 45
