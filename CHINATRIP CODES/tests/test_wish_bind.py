"""心愿→真实 POI 绑定（2026-10-30 用户拍板：看熊猫要匹配到熊猫基地并进排期）。

覆盖：核心词定城（看熊猫→成都，库内含「熊猫」行同城唯一）、候选池覆盖
绑定（不再落无城市「看熊猫」占位卡）、LLM 语义兜底（接地到候选序号、
单次尝试、负例缓存防每轮重烧）、必去合并按绑定钉真实 POI 且不与算法已
选重复、算法模式确定性命中零 LLM 调用。
"""

from __future__ import annotations

import asyncio

from app.services.agent.plan import PlanningAgent
from app.services.itinerary import VisitItem
from app.services.llm.base import ChatResult
from app.services.poi_details import PoiDetailStore
from app.services.trip_items import TripItemService

_PANDA = {
    "source_poi_id": "PANDA01",
    "name": "成都大熊猫繁育研究基地",
    "city": "成都",
    "category": "attraction",
    "address": "熊猫大道1375号",
    "opening_hours": "07:30-18:00",
    "source": "amap",
    "rating": 4.8,
    "rating_count": 210000,
    "tags": ["5a"],
    "best_visit_time": "morning",
    "suggested_duration_min": 180,
    "location": (104.1448, 30.7345),
}
_KUANZHAI = {
    "source_poi_id": "KZ01",
    "name": "宽窄巷子",
    "city": "成都",
    "category": "attraction",
    "rating": 4.5,
    "rating_count": 90000,
    "tags": [],
    "suggested_duration_min": 90,
    "location": (104.0532, 30.6650),
}


class PandaStore(PoiDetailStore):
    """熊猫场景桩：定城查询只认核心词「熊猫」；成都在库两行。"""

    def __init__(self):
        super().__init__(None)
        self.keyword_calls: list[tuple] = []

    def search_keyword(self, city, tokens, *, limit=5):
        self.keyword_calls.append((city, tuple(tokens or [])))
        rows = [dict(_PANDA) for t in tokens or [] if t == "熊猫"]
        return rows[:limit]

    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        if (city or "").removesuffix("市") != "成都":
            return []
        return [dict(_PANDA), dict(_KUANZHAI)][:limit]


class CountingLLM:
    def __init__(self, content: str = '{"i": null}'):
        self.content = content
        self.calls = 0

    async def chat(self, messages, *, temperature=0.3, max_tokens=None, **kwargs):
        self.calls += 1
        return ChatResult(content=self.content, model="fake")


def _visits(session):
    return [i for d in session.plan.days for i in d.items if isinstance(i, VisitItem)]


def _start(agent, *, wish: str):
    svc = agent._trip_items
    svc.create(wish, source="chat", city=None)
    return asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )


def test_wish_kanxiongmao_binds_panda_base(monkeypatch):
    """看熊猫：核心词命中库内熊猫基地——行程显示基地本体，零 LLM 调用。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = PandaStore()
    svc = TripItemService()
    llm = CountingLLM()
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = _start(agent, wish="看熊猫")
    names = [v.name for v in _visits(session)]
    assert "成都大熊猫繁育研究基地" in names
    assert "看熊猫" not in names
    panda = next(v for v in _visits(session) if v.name == "成都大熊猫繁育研究基地")
    assert (panda.city or "").removesuffix("市") == "成都"
    assert panda.poi_id == "PANDA01"
    assert llm.calls == 0
    rows_all = svc.list_groups()
    row = next(
        (
            r
            for g in ("wishlist", "scheduled")
            for r in rows_all.get(g, [])
            if r["name"] == "看熊猫"
        ),
        None,
    )
    assert row is not None
    assert (row.get("city") or "").removesuffix("市") == "成都"


def test_resolve_wish_city_core_keyword_layer():
    """定城核心词层：看熊猫 → 库名含「熊猫」行同城唯一 → 成都。"""
    store = PandaStore()
    agent = PlanningAgent(CountingLLM(), poi_details=store)
    assert asyncio.run(agent._resolve_wish_city("看熊猫")) == "成都"
    assert (None, ("熊猫",)) in store.keyword_calls


def test_wish_llm_semantic_bind_grounded(monkeypatch):
    """看国宝：确定性落空 → LLM 从候选池接地挑选（回显序号），单次调用。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = PandaStore()
    svc = TripItemService()
    llm = CountingLLM('{"i": 0}')
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = _start(agent, wish="看国宝")
    names = [v.name for v in _visits(session)]
    assert "成都大熊猫繁育研究基地" in names
    assert "看国宝" not in names
    assert sum(1 for n in names if n == "成都大熊猫繁育研究基地") == 1
    assert llm.calls == 1


def test_wish_llm_miss_placeholder_and_negative_cache(monkeypatch):
    """LLM 也挑不出（i=null）：保持占位语义；负例缓存防下轮重烧。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = PandaStore()
    svc = TripItemService()
    llm = CountingLLM('{"i": null}')
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = _start(agent, wish="看外星人遗址")
    assert "看外星人遗址" in [v.name for v in _visits(session)]
    assert llm.calls == 1
    asyncio.run(agent._generate_v0(session))
    assert llm.calls == 1
    assert "看外星人遗址" in [v.name for v in _visits(session)]


def test_sync_heals_stale_binding_to_real_poi(monkeypatch):
    """绑定毒成次优（小熊猫）但行程里已是正主（基地）：绑定自愈+行翻已排期。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = PandaStore()
    svc = TripItemService()
    svc.create("看熊猫", source="chat", city="成都")
    llm = CountingLLM()
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )
    stale = {
        "name": "小熊猫森林公园",
        "city": "成都",
        "source_poi_id": "ct_成都_103",
        "location": (104.1, 30.7),
    }
    agent._wish_bindings["看熊猫"] = stale
    session.wish_bindings["看熊猫"] = stale
    agent._sync_wish_rows(session)
    assert session.wish_bindings["看熊猫"]["source_poi_id"] == "PANDA01"
    assert agent._wish_bindings["看熊猫"]["source_poi_id"] == "PANDA01"
    rows = svc.list_groups(session.plan.itinerary_id)
    row = next(r for r in rows["scheduled"] if r["name"] == "看熊猫")
    assert "成都大熊猫繁育研究基地" in (row.get("note") or "")


def test_sync_time_arrange_skips_when_name_match_exists(monkeypatch):
    """行程里已有名字对得上的正主：不再为次优绑定点加第二个点。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = PandaStore()
    svc = TripItemService()
    svc.create("看熊猫", source="chat", city="成都")
    llm = CountingLLM()
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )
    stale = {
        "name": "小熊猫森林公园",
        "city": "成都",
        "source_poi_id": "ct_成都_103",
        "location": (104.1, 30.7),
    }
    session.wish_bindings["看熊猫"] = stale
    agent._wish_bindings["看熊猫"] = stale
    calls: list[list[str]] = []

    async def fake_add(sess, names, **kwargs):
        calls.append(list(names))
        return sess, None, ""

    agent._add_must_visits = fake_add
    notes, unresolved = asyncio.run(
        agent.sync_wishes_to_trip_items(session, ["看熊猫"])
    )
    assert calls == []
    assert llm.calls == 0


def test_wish_binds_out_of_pool_library_row(monkeypatch):
    """正主被挤出候选 top 窗口（在库不在池）：库内绑定兜底+入池落排。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = WaterStore(named=True, in_pool=False)
    svc = TripItemService()
    svc.create("看成都附近的水利工程", source="chat", city="成都")
    llm = CountingLLM()
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )
    names = [v.name for v in _visits(session)]
    assert "都江堰水利工程" in names
    assert "看成都附近的水利工程" not in names
    assert llm.calls == 0
    itin = session.plan.itinerary_id
    row = next(
        (
            r
            for g in ("wishlist", "scheduled")
            for r in svc.list_groups(itin).get(g, [])
            if r["name"] == "看成都附近的水利工程"
        ),
        None,
    )
    assert row is not None and row["status"] == "scheduled"
    assert "都江堰水利工程" in (row.get("note") or "")


def test_absorb_reopens_scheduled_row_for_new_trip(monkeypatch):
    """已排期（挂在旧行程）的心愿行：新行程重新吸收+换绑+刷新便签。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = WaterStore(named=True)
    svc = TripItemService()
    svc.create("看成都附近的水利工程", source="chat", city="成都")
    row = next(
        r for r in svc.list_groups()["wishlist"] if r["name"] == "看成都附近的水利工程"
    )
    # 旧行程已安排过：行翻 scheduled、挂旧行程、note 带旧「已安排」
    svc.update(
        row["id"],
        status="scheduled",
        day=3,
        note="来自聊天｜已安排：旧行程（第3天 09:00）",
    )
    svc.link_itinerary(row["id"], "it-old-trip")
    llm = CountingLLM()
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )
    assert "看成都附近的水利工程" in session.must_visits
    names = [v.name for v in _visits(session)]
    assert "都江堰水利工程" in names
    itin = session.plan.itinerary_id
    row2 = next(
        r
        for r in svc.list_groups(itin)["scheduled"]
        if r["name"] == "看成都附近的水利工程"
    )
    assert row2["itinerary_id"] == itin
    assert "旧行程" not in (row2["note"] or "")
    assert "都江堰水利工程" in (row2["note"] or "")
    assert row2["day"] in (1, 2)


def test_merge_must_visits_binding_appends_real_poi():
    """merge 绑定支：算法没选中的绑定 POI 以真实候选规格强制进排期。"""
    picked = [
        {
            "name": "宽窄巷子",
            "city": "成都",
            "category": "sight",
            "day": 1,
            "duration_minutes": 60,
        }
    ]
    out = PlanningAgent._merge_must_visits(
        picked,
        ["看熊猫"],
        ["成都"],
        2,
        {"成都": (1, 2)},
        bindings={"看熊猫": dict(_PANDA)},
    )
    panda = next(s for s in out if s["name"] == "成都大熊猫繁育研究基地")
    assert panda["must"] is True
    assert panda["day"] in (1, 2)
    assert panda["source_poi_id"] == "PANDA01"
    assert panda["category"] != "food"


def test_merge_must_visits_binding_marks_picked_no_dup():
    """绑定 POI 已被算法选中：标 must 不重复追加。"""
    picked = [
        {
            "name": "成都大熊猫繁育研究基地",
            "city": "成都",
            "category": "sight",
            "day": 1,
            "duration_minutes": 60,
        }
    ]
    out = PlanningAgent._merge_must_visits(
        picked,
        ["看熊猫"],
        ["成都"],
        2,
        {"成都": (1, 2)},
        bindings={"看熊猫": dict(_PANDA)},
    )
    assert sum(1 for s in out if s["name"] == "成都大熊猫繁育研究基地") == 1
    assert out[0]["must"] is True


# --- 水利工程事故（2026-10-30 深夜）：精确→模糊→LLM + 行程中心留痕 ---


_DUJIANGYAN_REAL = {
    # 正主：名字不含「水利工程」——确定性包含匹配够不到，只有 LLM 够得到
    "source_poi_id": "5a_255",
    "name": "青城山都江堰旅游景区",
    "city": "成都",
    "category": "attraction",
    "rating": 4.6,
    "rating_count": 180000,
    "tags": ["5a"],
    "suggested_duration_min": 180,
    "location": (103.619, 31.006),
}
_DUJIANGYAN_NAMED = {
    # 名字含「水利工程」——确定性纯核心词包含可绑
    "source_poi_id": "SL001",
    "name": "都江堰水利工程",
    "city": "成都",
    "category": "attraction",
    "rating": 4.7,
    "suggested_duration_min": 150,
    "location": (103.61, 31.0),
}


class WaterStore(PoiDetailStore):
    """水利工程场景桩：named=False 库内无「水利工程」命名行（逼 LLM）。
    in_pool=False 时命名行不进城 top 窗口（候选池窗外正主场景）。"""

    def __init__(self, named: bool = False, in_pool: bool = True):
        super().__init__(None)
        self.named = named
        self.in_pool = in_pool

    def search_keyword(self, city, tokens, *, limit=5):
        rows = [
            dict(_DUJIANGYAN_NAMED)
            for t in tokens or []
            if self.named and t == "水利工程"
        ]
        return rows[:limit]

    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        if (city or "").removesuffix("市") != "成都":
            return []
        if self.named:
            head = [dict(_DUJIANGYAN_NAMED)] if self.in_pool else []
        else:
            head = [dict(_DUJIANGYAN_REAL)]
        return (head + [dict(_KUANZHAI)])[:limit]


def test_wish_pure_core_strips_city_and_vicinity():
    from app.services.agent.plan import _wish_pure_core

    assert _wish_pure_core("看成都附近的水利工程") == "水利工程"
    assert _wish_pure_core("成都的水利工程") == "水利工程"
    assert _wish_pure_core("附近的水利工程") == "水利工程"
    assert _wish_pure_core("看熊猫") == "熊猫"
    assert _wish_pure_core("西湖") == "西湖"


def test_wish_water_llm_bind_full_flow(monkeypatch):
    """看成都附近的水利工程：库内无同名→LLM 接地选都江堰；行翻已排期
    +note 写映射+挂行程（行程中心按行程过滤可见）。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = WaterStore(named=False)
    svc = TripItemService()
    svc.create("看成都附近的水利工程", source="chat", city=None)
    llm = CountingLLM('{"i": 0}')
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )
    names = [v.name for v in _visits(session)]
    assert "青城山都江堰旅游景区" in names
    assert "看成都附近的水利工程" not in names
    assert llm.calls == 1
    itin = session.plan.itinerary_id
    row = next(
        r
        for r in svc.list_groups(itin).get("scheduled", [])
        if r["name"] == "看成都附近的水利工程"
    )
    assert row["day"] in (1, 2)
    assert "已安排" in (row.get("note") or "")
    assert "青城山都江堰旅游景区" in (row.get("note") or "")


def test_wish_water_deterministic_named_row(monkeypatch):
    """库名含「水利工程」（都江堰水利工程）：确定性纯核心词绑定，零 LLM。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = WaterStore(named=True)
    svc = TripItemService()
    svc.create("看成都附近的水利工程", source="chat", city=None)
    llm = CountingLLM()
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )
    names = [v.name for v in _visits(session)]
    assert "都江堰水利工程" in names
    assert "看成都附近的水利工程" not in names
    assert llm.calls == 0


def test_add_must_visits_binds_water_wish_incremental(monkeypatch):
    """消息回合增量路径（_add_must_visits）：语义绑定+行收口同样生效。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "algorithm")
    store = WaterStore(named=False)
    svc = TripItemService()
    llm = CountingLLM('{"i": 0}')
    agent = PlanningAgent(
        llm, trip_items=svc, poi_details=store, auto_restaurants=False
    )
    session = asyncio.run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="随便")
    )
    svc.create("看成都附近的水利工程", source="chat", city="成都")
    session, _, _ = asyncio.run(
        agent._add_must_visits(session, ["看成都附近的水利工程"])
    )
    names = [v.name for v in _visits(session)]
    assert "青城山都江堰旅游景区" in names
    assert "看成都附近的水利工程" not in names
    itin = session.plan.itinerary_id
    row = next(
        (
            r
            for g in ("wishlist", "scheduled")
            for r in svc.list_groups(itin).get(g, [])
            if r["name"] == "看成都附近的水利工程"
        ),
        None,
    )
    assert row is not None and row["status"] == "scheduled"
    assert row["itinerary_id"] == itin


def test_wish_bind_prefers_classic_5a_over_shorter_rival():
    """2026-10-31 用户拍板「景点先去最经典的」：同类候选（都江堰熊猫谷
    vs 5A 成都大熊猫繁育研究基地）同池时，经典档权重压过更高评分与更短
    名称——基地胜出，熊猫谷留给 reply「可替换」注释语义。"""
    agent = PlanningAgent(CountingLLM())
    valley = {
        "source_poi_id": "PANDAVALLEY",
        "name": "都江堰熊猫谷",
        "city": "成都",
        "category": "attraction",
        "rating": 4.9,
        "tags": [],
        "location": (103.60, 31.01),
    }
    base = dict(_PANDA)  # source_poi_id=PANDA01, tags=["5a"], rating 4.8
    picked = agent._wish_bind_candidate("看熊猫", [valley, base])
    assert picked is not None and picked["source_poi_id"] == "PANDA01"
    # 反向次序同样稳定（max 不受输入顺序影响）
    picked = agent._wish_bind_candidate("看熊猫", [base, valley])
    assert picked is not None and picked["source_poi_id"] == "PANDA01"
