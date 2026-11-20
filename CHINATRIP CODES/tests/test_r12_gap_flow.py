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
    dur = extra.pop("duration_minutes", None)
    if start is None:  # 无时刻卡（入场闸剥掉的必去等）
        st = en = None
    else:
        st = time(start // 60, start % 60)
        en = time(end // 60, end % 60)
        dur = end - start
    return VisitItem(
        item_id=item_id,
        name=name,
        category=cat,
        city="北京",
        day=1,
        start_time=st,
        end_time=en,
        duration_minutes=dur,
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
    # R12-H18：全天大点盖住午点核心 ⇒ 占位午餐被 COVER（园内解决）；
    # 未覆盖时占位照旧守窗。
    try:
        lunch = next(m for m in sol.meal_anchors if m["slot"] == "lunch")
    except StopIteration:
        site_item = next(i for i in sol.items if i.cid == "site")
        assert site_item.start_min <= 12 * 60
        assert site_item.end_min >= 13 * 60
        return
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


# ---------- R12-D: 同菜系不重样（2026-11-19 拍板「尽量不要同样的菜肴」） ----------


def test_cuisine_key_classifier():
    from app.services.trip_solver.inputs.cuisine import cuisine_key

    assert (
        cuisine_key(
            {
                "category": "food",
                "name": "四季民福烤鸭店（故宫店）",
                "intro": "故宫旁果木烤鸭名店：果木烤鸭/京味爆肚",
            }
        )
        == "烤鸭"
    )
    # 提督名字不含烤鸭——intro 是关键信号
    assert (
        cuisine_key(
            {
                "category": "food",
                "name": "提督·TIDU（前门创始店）",
                "intro": "北京坊新派烤鸭：提督烤鸭/糖油饼",
            }
        )
        == "烤鸭"
    )
    assert (
        cuisine_key(
            {
                "category": "food",
                "name": "御仙都·皇家菜博物馆",
                "intro": "宫廷礼仪乐舞伴宴",
            }
        )
        is None
    )
    assert cuisine_key({"category": "attraction", "name": "故宫博物院"}) is None


def test_same_cuisine_not_both_slots_same_day():
    """两家烤鸭不再同日分占午晚双槽：同菜系罚项让池内异菜系替代者顶上
    （quality 差 100 < 罚 150——罚项翻盘证明）。"""
    site = _cand(
        "site", rid="r-site", category="historic", hours="08:30-12:00", duration=90
    )
    duck1 = {
        "cid": "duck1",
        "name": "烤鸭店甲",
        "poi_id": "p-duck1",
        "kind": "fill",
        "category": "food",
        "opening_hours": "10:00-22:30",
        "suggested_duration_min": 60,
        "meal_slot": "any",
        "quality": 0.95,
        "cuisine": "烤鸭",
    }
    duck2 = dict(duck1, cid="duck2", name="烤鸭店乙", poi_id="p-duck2")
    alt = dict(
        duck1,
        cid="alt",
        name="川小馆",
        poi_id="p-alt",
        quality=0.85,
        cuisine="川菜",
    )
    snap = _snap(
        [site, duck1, duck2, alt],
        musts=("r-site",),
        pins=({"rid": "r-site", "day": 1, "start_min": 510},),
    )
    sol = solve_snapshot(enrich(snap))
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    placed = {i.cid for i in sol.items}
    bound_foods = {m["bound_cid"] for m in sol.meal_anchors if m.get("bound_cid")}
    # 两家烤鸭至多一家在场；替代异菜系餐馆顶上双槽
    ducks_in = {"duck1", "duck2"} & placed
    assert len(ducks_in) <= 1, f"同日两家烤鸭: {placed}"
    assert bound_foods and len(bound_foods) >= 2
    assert ("duck1" in bound_foods) != ("duck2" in bound_foods) or not ducks_in
    if ducks_in:
        assert "alt" in bound_foods


# ---------- R12-E: 入场闸营救（2026-11-19「指定的天坛漏了、没指定的景山
# 插进去了」——必去顶填充窗口） ----------


def test_rescue_entry_gated_must_takes_fill_window():
    from app.services.itinerary.hotfix_1117 import rescue_entry_gated_musts

    anchor = _card(
        "v1",
        "天安门广场",
        "attraction",
        7 * 60 + 9,
        7 * 60 + 54,
        poi_id="p-1",
        pinned=True,
    )
    fill = _card(
        "v2", "景山公园", "attraction", 8 * 60 + 30, 10 * 60 + 30, poi_id="p-2"
    )
    lunch = _card("meal-lunch-1", "午餐", "food", 12 * 60 + 2, 13 * 60 + 2)
    palace = _card(
        "v3",
        "故宫博物院",
        "museum",
        13 * 60 + 2,
        14 * 60 + 37,
        poi_id="p-3",
        pinned=True,
    )
    duck = _card(
        "meal-dinner-1",
        "四季民福烤鸭店（故宫店）",
        "food",
        19 * 60 + 16,
        20 * 60 + 46,
        poi_id="p-4",
    )
    tiantan = _card(
        "v4", "天坛", "temple", None, None, poi_id="p-5", duration_minutes=150
    )
    plan = _plan(anchor, fill, lunch, palace, duck, tiantan)
    notes = rescue_entry_gated_musts(plan, must_names=["天坛"])
    assert notes and "必去优先" in notes[0] and "天坛" in notes[0]
    ids = [i.item_id for i in plan.days[0].items]
    assert "v2" not in ids  # 未请求的景山让位
    seated = next(i for i in plan.days[0].items if i.item_id == "v4")
    assert seated.start_time is not None and seated.end_time is not None
    st = seated.start_time.hour * 60 + seated.start_time.minute
    en = seated.end_time.hour * 60 + seated.end_time.minute
    assert st == 8 * 60 + 30 and en == 11 * 60  # 顶进景山窗口
    # 幂等：再跑一次无动作
    assert rescue_entry_gated_musts(plan, must_names=["天坛"]) == []


def test_rescue_no_fill_keeps_must_untimed():
    from app.services.itinerary.hotfix_1117 import rescue_entry_gated_musts

    palace = _card(
        "v3",
        "故宫博物院",
        "museum",
        13 * 60,
        14 * 60 + 37,
        poi_id="p-3",
        pinned=True,
    )
    tiantan = _card("v4", "天坛", "temple", None, None, poi_id="p-5")
    plan = _plan(palace, tiantan)
    assert rescue_entry_gated_musts(plan, must_names=["天坛"]) == []
    assert tiantan.start_time is None


def test_evict_trigger_counts_untimed_must_named_engine_cards():
    from app.services.itinerary.hotfix_1117 import evict_fillers_when_must_unseated

    fill = _card(
        "v2", "景山公园", "attraction", 8 * 60 + 30, 10 * 60 + 30, poi_id="p-2"
    )
    tiantan = _card("v4", "天坛", "temple", None, None, poi_id="p-5")
    plan = _plan(fill, tiantan)
    notes = evict_fillers_when_must_unseated(plan, must_names=["天坛"])
    assert notes  # 引擎卡无 must 标记但名字命中名册 → 填充让位
    assert all(i.item_id != "v2" for i in plan.days[0].items)


# ---------- R12-F: 引擎必去标 + 必去大点提早（2026-11-19 审计拍板） ----------


def test_materialize_marks_requested_cards_as_must():
    """引擎必去卡打 must 标（legacy 判定面全链对齐）——live 实锤天坛/景山
    案的类根修。"""
    from app.services.trip_solver.assembly.materialize import materialize_plan

    site = _cand(
        "site", rid="r-site", category="historic", hours="08:30-18:00", duration=90
    )
    fill = _cand(
        "fill", category="park", hours="08:30-18:00", duration=90, lon=116.40, lat=39.91
    )
    snap = _snap([site, fill], musts=("r-site",))
    sol = solve_snapshot(enrich(snap))
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    plan = materialize_plan(sol, snap)
    cards = {c.name: c for d in plan.days for c in d.items}
    assert cards["site"].must is True
    assert cards["fill"].must is False


def test_pre_remote_eviction_spares_marked_must():
    """远郊日清场（B-03a）不撤打标必去——此前引擎必去（无 must 标）会被
    当 filler 误撤。"""
    from app.services.itinerary.hotfix_1117 import evict_pre_remote_fillers

    anchor = _card(
        "v1",
        "天安门广场",
        "attraction",
        7 * 60 + 10,
        8 * 60 + 40,
        poi_id="p-1",
        must=True,
    )
    remote = _card(
        "v9", "慕田峪长城", "historic", 12 * 60 + 8, 15 * 60 + 8, poi_id="p-9"
    )
    plan = _plan(anchor, remote)
    evict_pre_remote_fillers(plan)
    ids = [i.item_id for i in plan.days[0].items]
    assert "v1" in ids and "v9" in ids


def test_big_musts_go_early_fills_take_leftover():
    """R12-F2：必去大点晚开分段罚——锚后必去大点先排（故宫/天坛进上午
    早段），填充大点（景山）让出到下午剩余时段。"""
    site = _cand(
        "anchor", rid="r-a", category="attraction", hours="07:00-20:00", duration=60
    )
    palace = _cand(
        "palace",
        rid="r-p",
        name="故宫博物院",
        category="museum",
        hours="08:30-17:00",
        duration=120,
    )
    tiantan = _cand(
        "tiantan",
        rid="r-t",
        name="天坛",
        category="temple",
        hours="06:30-22:00",
        duration=150,
    )
    fill = _cand(
        "jingshan",
        name="景山公园",
        category="park",
        hours="06:30-20:00",
        duration=120,
    )
    snap = _snap(
        [site, palace, tiantan, fill],
        musts=("r-a", "r-p", "r-t"),
        pins=({"rid": "r-a", "day": 1, "start_min": 450},),
    )
    sol = solve_snapshot(enrich(snap))
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    placed = {i.cid: i for i in sol.items}
    # 填充可选：只进真余量（F4b 预算放不下就挪天/不进均合法）
    # 必去大点不进晚开带：故宫/天坛都在 12:30 前（或至少早于填充）
    assert placed["palace"].start_min < 12 * 60 + 30
    assert placed["tiantan"].start_min < 14 * 60
    # 填充大点吃剩余：进场时晚于其同日最早必去大点（不进=预算不许可）
    if "jingshan" in placed:
        same_day = [
            placed[c].start_min
            for c in ("palace", "tiantan")
            if placed[c].day == placed["jingshan"].day
        ]
        if same_day:
            assert placed["jingshan"].start_min > min(same_day)


def test_fill_budget_blocks_shrink_causing_fill():
    """R12-F4b（用户纠正「引起收缩的填充不应插入」——不是连坐）：必去
    满档+骨架已近日容，再塞 120 分钟填充必靠必去压缩腾位 → 预算（按
    满档 mid 计）直接不允许该填充进场；填充去有余量的天。"""
    anchor = _cand(
        "anchor", rid="r-a", category="attraction", hours="07:00-20:00", duration=90
    )
    palace = _cand(
        "palace",
        rid="r-p",
        name="故宫博物院",
        category="museum",
        hours="08:30-17:00",
        duration=150,
    )
    tiantan = _cand(
        "tiantan",
        rid="r-t",
        name="天坛",
        category="temple",
        hours="06:30-22:00",
        duration=150,
    )
    fill = _cand(
        "jingshan",
        name="景山公园",
        category="park",
        hours="06:30-20:00",
        duration=120,
    )
    snap = _snap(
        [anchor, palace, tiantan, fill],
        musts=("r-a", "r-p", "r-t"),
        pins=({"rid": "r-a", "day": 1, "start_min": 510},),
        days=2,
    )
    sol = solve_snapshot(enrich(snap))
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    placed = {i.cid: i for i in sol.items}
    # 锚+故宫+天坛满档（390+缝 90+骨架 240=720≈750 日容）：景山
    # （120+30）不可能靠压缩必去进第 1 天——只去第 2 天余量或不进
    jing = placed.get("jingshan")
    day1_musts = [c for c in ("palace", "tiantan") if placed[c].day == 1]
    if jing is not None and len(day1_musts) == 2:
        assert jing.day != 1
    # 必去全排上
    assert {"anchor", "palace", "tiantan"} <= set(placed)


def test_innocent_fill_survives_window_caused_shrink():
    """R12-F4b 反向（无辜填充不连坐）：必去被自己的窄窗逼缩（与填充
    无关），且满档预算仍放得下填充 → 填充照常进场。"""
    palace = _cand(
        "palace",
        rid="r-p",
        name="故宫博物院",
        category="museum",
        hours="10:00-11:45",  # 105 分钟窗：120 档必须缩
        duration=120,
    )
    fill = _cand(
        "jingshan",
        name="景山公园",
        category="park",
        hours="06:30-20:00",
        duration=120,
    )
    snap = _snap([palace, fill], musts=("r-p",))
    sol = solve_snapshot(enrich(snap))
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    placed = {i.cid: i for i in sol.items}
    p = placed["palace"]
    assert p.end_min - p.start_min < 120  # 窄窗自缩
    # 无辜景山照常在场（同日）——压缩是窗造成的，不是它
    assert "jingshan" in placed and placed["jingshan"].day == p.day


# ---------- R12-G: 升旗锚重叠推平（2026-11-20 polish） ----------


def test_flag_anchor_pushes_overlapping_successors():
    """live 实锤形态：天安门锚 07:09-08:39（升旗重定位）、天坛 08:30
    ——9 分钟重叠。推平后：天坛 ≥08:49（+10 分钟地板），级联再推下一张。"""
    from app.services.agent.plan import _push_flag_successors

    anchor = _card(
        "v1",
        "天安门广场",
        "attraction",
        7 * 60 + 9,
        8 * 60 + 39,
        poi_id="p-1",
        pinned=True,
    )
    tiantan = _card("v2", "天坛", "temple", 8 * 60 + 30, 10 * 60 + 53, poi_id="p-2")
    # 13:00 起的后继（不与推平后的天坛 08:49-11:12 重叠）——应保持不动
    next_card = _card("v3", "故宫博物院", "museum", 13 * 60, 15 * 60, poi_id="p-3")
    plan = _plan(anchor, tiantan, next_card)
    _push_flag_successors(plan.days[0], anchor)
    st = tiantan.start_time.hour * 60 + tiantan.start_time.minute
    assert st == 8 * 60 + 49  # 08:39 + 10 地板
    # 无重叠的后继不动
    nst = next_card.start_time.hour * 60 + next_card.start_time.minute
    assert nst == 13 * 60


def test_flag_anchor_push_cascade_and_pin_respected():
    """级联：天坛被推到 08:49-11:12 后压住 10:30 的下一卡 → 连锁右推；
    用户钉住卡（铁律 19）绝不动。"""
    from app.services.agent.plan import _push_flag_successors

    anchor = _card(
        "v1",
        "天安门广场",
        "attraction",
        7 * 60 + 9,
        8 * 60 + 39,
        poi_id="p-1",
        pinned=True,
    )
    tiantan = _card("v2", "天坛", "temple", 8 * 60 + 30, 10 * 60 + 53, poi_id="p-2")
    chained = _card("v3", "钟鼓楼", "historic", 10 * 60 + 30, 12 * 60, poi_id="p-3")
    pinned = _card(
        "v4", "用户钉住点", "museum", 9 * 60, 10 * 60, poi_id="p-4", pinned=True
    )
    plan = _plan(anchor, tiantan, chained, pinned)
    _push_flag_successors(plan.days[0], anchor)
    t_end = tiantan.end_time.hour * 60 + tiantan.end_time.minute
    assert t_end == 8 * 60 + 49 + 143  # 11:12
    cst = chained.start_time.hour * 60 + chained.start_time.minute
    assert cst == 11 * 60 + 22  # 11:12 + 10 地板
    # 钉住卡原时刻不动
    pst = pinned.start_time.hour * 60 + pinned.start_time.minute
    assert pst == 9 * 60


def test_flag_anchor_push_no_overlap_noop():
    from app.services.agent.plan import _push_flag_successors

    anchor = _card(
        "v1",
        "天安门广场",
        "attraction",
        7 * 60 + 9,
        8 * 60 + 39,
        poi_id="p-1",
        pinned=True,
    )
    far = _card("v2", "天坛", "temple", 9 * 60, 11 * 60, poi_id="p-2")
    plan = _plan(anchor, far)
    _push_flag_successors(plan.days[0], anchor)
    assert far.start_time.hour * 60 + far.start_time.minute == 9 * 60
