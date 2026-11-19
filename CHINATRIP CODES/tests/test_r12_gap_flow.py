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

from app.services.itinerary.hotfix_1117 import (
    evict_pre_remote_fillers,
    fold_restaurant_visit_cards,
)
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.trip_solver.assembly.bridges import (
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
    assert "前往下一站" in got[0].name and "自由活动" in got[0].name


def test_bridge_estimated_name_from_coordinates():
    """无腿元数据但有坐标：兜底按直线距离估步行/打车并写进卡名。"""
    from app.services.itinerary.models import GeoPoint

    a = _card(
        "v1",
        "天安门广场",
        "attraction",
        8 * 60 + 30,
        10 * 60,
        poi_id="p-1",
        location=GeoPoint(lon=116.397, lat=39.910),
    )
    b = _card(
        "v2",
        "景山公园",
        "attraction",
        10 * 60 + 30,
        12 * 60 + 30,
        poi_id="p-2",
        location=GeoPoint(lon=116.403, lat=39.917),
    )
    got = _bridges(attach_gap_bridges(_plan(a, b)))
    assert len(got) == 1
    assert "步行" in got[0].name and "分钟" in got[0].name


def test_every_hop_bridged_and_system_cards_not():
    """R12-C2（2026-11-19 拍板「所有景点后就是下一个景点，不需要
    45 分钟这个条件」）：每一段正时长转场都出桥——30 分钟缝也出；
    酒店/换程系统卡两端仍不桥；去程接驳段出「接驳前往下一站」。"""
    a = _card("v1", "天安门广场", "attraction", 8 * 60 + 30, 10 * 60, poi_id="p-1")
    near = _card("v2", "故宫博物院", "museum", 10 * 60 + 30, 12 * 60 + 30, poi_id="p-3")
    got = _bridges(attach_gap_bridges(_plan(a, near)))
    assert len(got) == 1  # 30 分钟缝也出桥
    assert got[0].start_time == time(10, 0) and got[0].end_time == time(10, 30)

    # 占位午餐做目的地：照常出桥（去吃饭也是在路上）
    ph = _card("meal-lunch-1", "午餐", "food", 11 * 60 + 30, 12 * 60 + 30)
    got_ph = _bridges(attach_gap_bridges(_plan(a, ph)))
    assert len(got_ph) == 1

    # access/换程段（去程接驳）出桥：🚌 接驳前往下一站（腿字段在 prev
    # 卡上——annotate 口径：锚→慕田峪的接驳腿写在锚卡上）
    anchor_acc = _card(
        "v0",
        "天安门广场",
        "attraction",
        8 * 60 + 51,
        8 * 60 + 51,
        poi_id="p-0",
        next_leg_mode="access",
        next_leg_minutes=98,
        next_leg_detail={"service_name": "前门旅游专线"},
    )
    shut = _card(
        "v3",
        "慕田峪长城",
        "historic",
        11 * 60 + 8,
        14 * 60 + 8,
        poi_id="p-5",
    )
    got_acc = _bridges(attach_gap_bridges(_plan(anchor_acc, shut)))
    assert len(got_acc) == 1
    assert "接驳" in got_acc[0].name and "98" in got_acc[0].name

    # 换程/回城卡做起点或目的地：仍不桥（系统卡自管）
    ret = _card("access-return-v1", "回城", "transfer", 15 * 60 + 30, 17 * 60)
    din = _card("meal-dinner-1", "晚饭（烤鸭）", "food", 19 * 60, 20 * 60, poi_id="p-4")
    assert _bridges(attach_gap_bridges(_plan(ret, din))) == []
    # 酒店夜卡做目的地：不桥
    hn = _card("hotel-night-d1", "回酒店·夜间休息", "hotel", 21 * 60, 22 * 60)
    assert _bridges(attach_gap_bridges(_plan(din, hn))) == []


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


def test_fold_restaurant_visit_cards_into_meal_card():
    """R12-C（2026-11-19 拍板「餐厅放午餐/晚餐卡上」）：存量计划的
    观光卡烤鸭折进当日占位餐卡——占位顶替成命名餐卡、观光卡撤除、
    幂等。"""
    from app.services.itinerary.models import GeoPoint

    anchor = _card("v3", "天安门广场", "attraction", 8 * 60 + 30, 10 * 60, poi_id="p-3")
    duck = _card(
        "v4",
        "四季民福烤鸭店（故宫店）",
        "food",
        11 * 60 + 2,
        11 * 60 + 57,
        location=GeoPoint(lon=116.410, lat=39.925),
        opening_hours="10:30-22:30",
    )
    lunch_ph = _card("meal-lunch-1", "午餐", "food", 12 * 60 + 30, 13 * 60 + 30)
    plan = _plan(anchor, duck, lunch_ph)
    notes = fold_restaurant_visit_cards(plan)
    assert notes and "四季民福" in notes[0]
    names = [(i.name, i.item_id) for i in plan.days[0].items]
    assert ("四季民福烤鸭店（故宫店）", "meal-lunch-1") in names
    assert all(
        n != "四季民福烤鸭店（故宫店）" or iid == "meal-lunch-1" for n, iid in names
    )
    meal = next(i for i in plan.days[0].items if i.item_id == "meal-lunch-1")
    assert meal.start_time == time(11, 2) and meal.end_time == time(11, 57)
    assert meal.location is not None
    # 幂等：二次运行无新动作
    assert fold_restaurant_visit_cards(plan) == []


def test_fold_evening_restaurant_into_dinner_placeholder():
    duck = _card(
        "v4",
        "四季民福烤鸭店（故宫店）",
        "food",
        19 * 60 + 58,
        21 * 60 + 28,
        poi_id="p-4",
    )
    dinner_ph = _card("meal-dinner-1", "晚饭", "food", 17 * 60 + 58, 19 * 60 + 28)
    sight = _card("v1", "天坛", "temple", 14 * 60, 15 * 60 + 30, poi_id="p-1")
    plan = _plan(sight, duck, dinner_ph)
    notes = fold_restaurant_visit_cards(plan)
    assert notes
    meal = next(i for i in plan.days[0].items if i.item_id == "meal-dinner-1")
    assert meal.name == "四季民福烤鸭店（故宫店）"
    assert meal.start_time == time(19, 58)


def test_fold_no_placeholder_leaves_orphan_untouched():
    duck = _card("v4", "蜀宴赋", "food", 16 * 60 + 48, 18 * 60 + 48, poi_id="p-4")
    sight = _card("v1", "武侯祠", "historic", 9 * 60, 11 * 60, poi_id="p-1")
    plan = _plan(sight, duck)
    assert fold_restaurant_visit_cards(plan) == []
    assert any(i.item_id == "v4" for i in plan.days[0].items)


def test_any_slot_restaurant_binds_time_matching_slot():
    """R12-C3：any-槽按时段对齐——上午流式的烤鸭落午餐卡（不是晚餐卡
    的 09:00 倒挂）。"""
    site = _cand(
        "site", rid="r-site", category="historic", hours="08:30-12:00", duration=90
    )
    duck = _cand(
        "duck",
        rid="r-duck",
        name="烤鸭店",
        category="food",
        hours="09:00-22:30",
        duration=60,
        meal_slot="any",
    )
    snap = _snap(
        [site, duck],
        musts=("r-site", "r-duck"),
        pins=({"rid": "r-site", "day": 1, "start_min": 510},),
    )
    sol = solve_snapshot(enrich(snap))
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    placed = {i.cid: i for i in sol.items}
    d = placed["duck"]
    assert d.start_min < 15 * 60  # 上午流式（营业地板+缝）
    lunch = next(m for m in sol.meal_anchors if m["slot"] == "lunch")
    dinner = next(m for m in sol.meal_anchors if m["slot"] == "dinner")
    assert lunch["bound_cid"] == "duck"  # 午段烤鸭=午餐卡
    assert dinner["bound_cid"] is None  # 晚餐槽照常占位
