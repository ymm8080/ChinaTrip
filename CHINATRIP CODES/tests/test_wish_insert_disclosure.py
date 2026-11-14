# -*- coding: utf-8 -*-
"""陕历博插入假成功案回归锚（2026-11-11）：聊天插入「陕西历史博物馆」，
回复报「已加到第3天」而行程里没有——双病根三修复：

1. 错针：专名含品类子串（→「博物馆」）被关键词路接管，底库 rank 的
   精确名首键全库落空，同行高 tier 记录（西安市钟鼓楼博物馆）顶包。
   修复 = _poi_library_lookup tokens 全名前置。
2. 假成功回复：_drop_untimed_visits 清算披露只写 plan.assumptions，
   从不进用户可见 notes——LLM 按插入前中间态报成功。修复 =
   _apply_structural 第四返回带出披露，_apply_with_repair 并入 notes；
   sync_wishes_to_trip_items 回钉重加的披露串同样并入返回 notes。
3. 必去保护漏认：_drop_untimed_from_day 的 protect 判据是
   item.name not in protect 精确等值——条目以 POI 正名（含括号尾缀/
   别名）落卡时必去心愿匹配不上被当杂卡删。修复 = _site_dup 核名。
"""

import asyncio

import app.services.agent.plan as plan_mod
from app.services.agent.plan import (
    PlanningAgent,
    _drop_untimed_visits,
    _reconcile_transfer_days,
)
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)


class _NoLLM:
    async def complete(self, *a, **k):
        return ""


def _visit(item_id, *, dur=180, day=1, city="西安", **kw) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city=city,
        day=day,
        duration_minutes=dur,
        **kw,
    )


def _plan(days):
    return ItineraryPlan(itinerary_id="it1", cities=["上海", "西安"], days=days)


def _session():
    from app.services.agent.plan import PlanSession

    return PlanSession(
        session_id="s1", device_id="dev-1", cities=["西安"], plan=_plan([])
    )


# ---------------- 病根 1：错针（全名前置 token 后精确行胜过高 tier） ----------------


class _RankedStore:
    """search_keyword 仿库内 rank（poi_details 口径）：首键名字==token
    精确命中，其后 label/坐标/品类，末键 -tier 高者胜。错针案布景：
    精确同名行 tier 远逊同行——tokens 无全名时同行凭末键顶包。"""

    def __init__(self, rows):
        self.rows = rows
        self.seen_tokens: list[list[str]] = []

    @staticmethod
    def _rank(row, tokens):
        name = (row.get("name") or "").strip()
        exact = any(name == t for t in tokens)
        label = bool(set(row.get("tags") or []) & set(tokens))
        loc = row.get("location") is not None
        cat = any(t in (row.get("category") or "") for t in tokens)
        return (exact, label, loc, cat, -(row.get("hit_tier") or 99))

    def search_keyword(self, city, tokens, limit=20):
        self.seen_tokens.append(list(tokens))
        ranked = sorted(self.rows, key=lambda r: self._rank(r, tokens), reverse=True)
        return ranked[:limit]

    def get(self, poi_id):
        return None

    def get_by_name(self, city, name):
        return None

    def upsert(self, *a, **k):
        return None

    def get_details(self, poi_id):
        return None


_ROWS = [
    {
        "name": "陕西历史博物馆",
        "category": "museum",
        "location": (108.953, 34.222),
        "hit_tier": 5,
        "tags": [],
    },
    {
        "name": "西安市钟鼓楼博物馆",
        "category": "museum",
        "location": (108.943, 34.265),
        "hit_tier": 1,
        "tags": [],
    },
]


def test_poi_library_lookup_full_name_token_beats_tier():
    """专名含品类子串（陕西历史博物馆→博物馆）：keywords 首 token 必须是
    全名，精确同名行才能顶住高 tier 同行（修复前顶包者胜=错针复发）。"""
    store = _RankedStore(_ROWS)
    agent = PlanningAgent(_NoLLM(), poi_details=store)
    hit = asyncio.run(
        agent._poi_library_lookup(_session(), "陕西历史博物馆", "博物馆", "西安")
    )
    assert hit is not None
    assert hit["name"] == "陕西历史博物馆"
    assert store.seen_tokens[0][0] == "陕西历史博物馆"


def test_poi_library_lookup_exact_name_path_unchanged():
    """无品类子串的专名（search_kw=None）走精确闸，行为不回退。"""
    store = _RankedStore(_ROWS)
    agent = PlanningAgent(_NoLLM(), poi_details=store)
    hit = asyncio.run(
        agent._poi_library_lookup(_session(), "西安市钟鼓楼博物馆", None, "西安")
    )
    assert hit is not None
    assert hit["name"] == "西安市钟鼓楼博物馆"


# ---------------- 病根 2：假成功回复（清算披露必须出到 notes） ----------------


def test_apply_structural_returns_drop_notes(monkeypatch):
    """_apply_structural 第四返回 = _drop_untimed_visits 披露；调用方并入
    notes 才进用户可见回复（修复前返回值被丢弃，回复按中间态报成功）。"""
    monkeypatch.setattr(plan_mod, "_reconcile_transfer_days", lambda p, protect: [])
    monkeypatch.setattr(plan_mod, "_has_untimed_visits", lambda p: True)
    monkeypatch.setattr(plan_mod, "_fallback_sequence_times", lambda p: None)
    monkeypatch.setattr(plan_mod, "_transfer_day_sweep", lambda p, protect: [])
    monkeypatch.setattr(
        plan_mod, "_drop_untimed_visits", lambda p, protect: ["DISCLOSED-REMOVAL"]
    )
    agent = PlanningAgent(_NoLLM(), solver=lambda *a, **k: None)
    day1 = DayPlan(day=1, base_city="西安", items=[_visit("stray")])
    plan = _plan([day1])
    candidate, _report, _summary, drop_notes = agent._apply_structural(plan, [])
    assert drop_notes == ["DISCLOSED-REMOVAL"]
    assert "DISCLOSED-REMOVAL" in candidate.assumptions


def test_apply_with_repair_surfaces_drop_notes(monkeypatch):
    """端到端口径：_apply_with_repair 返回的 notes 必须含清算披露——
    用户看到的回复不再只说「已加到第N天」。"""
    monkeypatch.setattr(plan_mod, "_reconcile_transfer_days", lambda p, protect: [])
    monkeypatch.setattr(plan_mod, "_has_untimed_visits", lambda p: True)
    monkeypatch.setattr(plan_mod, "_fallback_sequence_times", lambda p: None)
    monkeypatch.setattr(plan_mod, "_transfer_day_sweep", lambda p, protect: [])
    monkeypatch.setattr(
        plan_mod, "_drop_untimed_visits", lambda p, protect: ["DISCLOSED-REMOVAL"]
    )
    agent = PlanningAgent(_NoLLM(), solver=lambda *a, **k: None, auto_restaurants=False)
    session = _session()
    day1 = DayPlan(day=1, base_city="西安", items=[_visit("stray")])
    session.plan = _plan([day1])
    from app.services.itinerary.models import DiffOp

    add = DiffOp(op="add", new_day=1, item=_visit("added", start_time=None))
    _plan_out, _summary, notes = asyncio.run(
        agent._apply_with_repair(session, [add], "插入陕西历史博物馆")
    )
    assert "DISCLOSED-REMOVAL" in notes


# ---------------- 病根 3：必去保护认 POI 正名核名（含尾缀/别名变体） ----------------


def test_drop_untimed_protects_core_name_variants():
    """protect 名录「陕西历史博物馆」vs 卡名「陕西历史博物馆（基本陈列）」：
    精确等值判据下必去心愿被当杂卡删（2026-11-11 陕历博案）——_site_dup
    核名后整卡豁免（同精确名旧口径，protect 命中不留痕），同日起杂卡
    照旧清算留痕。"""
    day1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            VisitItem(
                item_id="shxlm",
                name="陕西历史博物馆（基本陈列）",
                city="西安",
                day=1,
                duration_minutes=180,
            ),
            _visit("gone"),
        ],
    )
    plan = _plan([day1])
    notes = _drop_untimed_visits(plan, {"陕西历史博物馆"})
    kept = [i for i in day1.items if i.item_id == "shxlm"]
    assert len(kept) == 1
    # protect 命中即整卡豁免（同精确名旧口径），不得出现它的移除留痕；
    # 同日起杂卡照旧清算留痕。
    assert not any("陕西历史博物馆" in str(n) for n in notes)
    assert any("移除" in str(n) or "removed" in str(n) for n in notes)
    assert all(i.item_id != "gone" for i in day1.items)


# ------------- 2026-11-12 复发案（用户报「插入陕西历史博物馆没安排」） -------------
# 病根链四拍：①品类子串劫持——sync 首循环「博物馆」子串把专名心愿整轮
# 跳过（不绑定/不回钉/不进 must）；②兜底网 _ensure_wishlist_coverage 虽
# 接住重加，但名不回钉 must_visits → 本回合清算无保护；③solver 不收敛
# （240min 多日探测均 placed=None）→ 无保护清算删除「已移除」，回复只报
# 成功；④到达日/离城日清扫 protect 精确等值漏认 POI 正名变体卡。
# 修复 = 专名优先闸(_known_proper_noun) + 重加回钉 must + 无时刻件不钉
# + 未排必去 keep 披露 + protect 统一 _site_dup 核名（三处精确等值全改）。


def test_known_proper_noun_exact_library_hit_overrides_category_substring():
    """专名优先闸：「陕西历史博物馆」含品类子串「博物馆」，但整串精确命中
    POI 底库（带坐标）→ 专名路由（修复前 sync 首循环 continue，绑定/回钉/
    must_visits 整链被跳过=插入假成功复发）。"""
    store = _RankedStore(_ROWS)
    agent = PlanningAgent(_NoLLM(), poi_details=store)
    assert asyncio.run(agent._known_proper_noun("陕西历史博物馆")) is True


def test_known_proper_noun_pure_category_wish_stays_category():
    """品类语义不回退：「我想去博物馆」整串无精确 POI 行 → 仍按品类愿望走
    全城口碑与就近落实（闸只放行整串精确命中，不误伤品类）。"""
    store = _RankedStore(_ROWS)
    agent = PlanningAgent(_NoLLM(), poi_details=store)
    assert asyncio.run(agent._known_proper_noun("我想去博物馆")) is False


def test_sync_routes_proper_noun_past_category_gate(monkeypatch):
    """sync 首循环端到端：含品类子串的专名心愿不被 continue——绑定、回钉
    must_visits、走 _add_must_visits 重加；同轮纯品类愿望照旧跳过（不绑定
    不重加）。修复前专名心愿整轮静默跳过=只建行不排期。"""
    from app.services.trip_items import TripItemService

    store = _RankedStore(_ROWS)
    agent = PlanningAgent(_NoLLM(), poi_details=store, trip_items=TripItemService())
    add_calls: list[list[str]] = []

    async def _fake_bind(wish, city, *, allowed_cities):
        return {
            "name": wish,
            "city": "西安",
            "source_poi_id": "poi-shxlm",
            "location": (108.953, 34.222),
        }

    async def _fake_add(session, names, **kw):
        add_calls.append(list(names))
        return session, None, ""

    monkeypatch.setattr(agent, "_bind_wish_poi", _fake_bind)
    monkeypatch.setattr(agent, "_add_must_visits", _fake_add)
    session = _session()
    session.plan = _plan([DayPlan(day=1, base_city="西安", items=[])])
    asyncio.run(
        agent.sync_wishes_to_trip_items(session, ["陕西历史博物馆", "我想去博物馆"])
    )
    assert session.must_visits == ["陕西历史博物馆"]
    assert add_calls == [["陕西历史博物馆"]]


def test_add_must_visits_repins_and_keeps_untimed_with_disclosure():
    """兜底网重加件三拍收口（solver 不收敛=本拍无解实景）：
    ①名回钉 session.must_visits（修复前无必去身份，终局清算按杂卡删）；
    ②件幸存 plan——protect+pinned 双豁免 _drop_untimed（钉住无时刻件是
    引擎既有口径：下游 sweep 靠钉位落位，不钉的无时刻件反被挪日引发
    校验修复环，2026-11-12 灵隐寺案实测回退）；
    ③返回 note 有用户可见 keep 披露（修复前被「已移除」清算，回复只报
    成功）。"""
    store = _RankedStore(_ROWS)
    agent = PlanningAgent(
        _NoLLM(),
        poi_details=store,
        solver=lambda *a, **k: None,
        auto_restaurants=False,
    )
    session = _session()
    filler = _visit("秦始皇帝陵博物院", dur=720)
    session.plan = _plan([DayPlan(day=1, base_city="西安", items=[filler])])
    session, _summary, note = asyncio.run(
        agent._add_must_visits(session, ["陕西历史博物馆"], repin=True)
    )
    assert "陕西历史博物馆" in session.must_visits
    kept = [
        i
        for d in session.plan.days
        for i in d.items
        if "陕西历史博物馆" in str(getattr(i, "name", ""))
    ]
    assert len(kept) == 1
    assert kept[0].start_time is None
    assert kept[0].pinned is True
    assert "保留" in str(note)


def test_reconcile_transfer_days_protects_name_variant():
    """protect 名录心愿名「陕西历史博物馆」vs 卡名 POI 正名变体「陕西历史
    博物馆（基本陈列）」：离城日搁浅保护必须 _site_dup 核名认人（修复前
    精确等值漏认，必去卡被「已从第N天移除」静默删除）。同杂卡无保护照旧
    移除留痕。"""
    day1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            TransferItem(item_id="t1", day=1, seq=1, from_city="西安", to_city="上海"),
            VisitItem(
                item_id="shxlm",
                name="陕西历史博物馆（基本陈列）",
                city="西安",
                day=1,
                duration_minutes=180,
            ),
            _visit("杂卡", dur=180),
        ],
    )
    day2 = DayPlan(day=2, base_city="上海", items=[])
    plan = _plan([day1, day2])
    notes = _reconcile_transfer_days(plan, frozenset({"陕西历史博物馆"}))
    assert any(i.item_id == "shxlm" for i in day1.items)
    # 必去卡：不得出现它的移除留痕；杂卡照旧移除留痕。
    assert not any(
        "陕西历史博物馆" in str(n) and ("移除" in str(n) or "removed" in str(n))
        for n in notes
    )
    assert any("移除" in str(n) or "removed" in str(n) for n in notes)
    assert all(i.item_id != "杂卡" for i in day1.items)
