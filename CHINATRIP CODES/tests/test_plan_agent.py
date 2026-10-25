"""Planning agent tests (design §6.1-§6.4, §6.9): stub LLM/amap/solver.

All offline (test_gate.py style: asyncio.run, no pytest-asyncio). Stubs are
injected through PlanningAgent's constructor; nothing here touches the
network or the real amap/zhipu backends.
"""

import asyncio
import json
from datetime import time

import pytest

from app.services.agent.plan import (
    MAX_REPAIR_ROUNDS,
    POI_KEYWORD,
    PlanningAgent,
    _category_search_keyword,
    _dedupe_visit_keepers,
    _site_dup,
    clarify_questions,
    current_violations,
)
from app.services.itinerary import GeoPoint, RuleSeverity, TransferItem, VisitItem
from app.services.llm.base import ChatResult
from app.services.llm.zhipu import LLMError
from app.services.poi_details import PoiDetailStore
from app.services.trip_items import TripItemService


class ScriptedLLM:
    """Returns canned replies in order; counts chat() calls."""

    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def chat(
        self, messages, *, temperature: float = 0.3, max_tokens=None
    ) -> ChatResult:
        self.calls += 1
        assert self.replies, "scripted replies exhausted"
        return ChatResult(content=self.replies.pop(0), model="scripted")


class ExplodingLLM:
    """Any call is a bug sentinel (clarify path must not burn the LLM)."""

    name = "explode"

    async def chat(
        self, messages, *, temperature: float = 0.3, max_tokens=None
    ) -> ChatResult:
        raise LLMError("backend down")


class FlakyLLM:
    """First ``failures`` calls raise (backend stall), then one canned reply."""

    name = "flaky"

    def __init__(self, failures: int, then: str) -> None:
        self.failures = failures
        self.then = then
        self.calls = 0

    async def chat(
        self, messages, *, temperature: float = 0.3, max_tokens=None
    ) -> ChatResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise LLMError("zhipu request timeout: ReadTimeout")
        return ChatResult(content=self.then, model="flaky")


class StubAmap:
    def __init__(self, pois=None, exc: Exception | None = None) -> None:
        self.pois = pois or []
        self.exc = exc
        self.calls: list[tuple[str, str | None]] = []

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append((keywords, city))
        if self.exc is not None:
            raise self.exc
        return self.pois


class DistanceAmap(StubAmap):
    """StubAmap + amap-style leg measurement (v2.4.3 enrich path)."""

    def __init__(self, pois=None, meters=1100, seconds=900, exc=None):
        super().__init__(pois, exc=exc)
        self.meters = meters
        self.seconds = seconds
        self.route_calls = []
        self.hours_calls = []
        self.search_calls = []

    async def walking_route(
        self, origin, destination, *, origin_id=None, destination_id=None
    ):
        self.route_calls.append((origin, destination, origin_id, destination_id))
        if self.exc is not None:
            raise self.exc
        return {
            "distance_m": self.meters,
            "duration_s": self.seconds,
            "steps": [],
            "polyline": [],
        }

    async def place_hours(self, poi_id):
        self.hours_calls.append(poi_id)
        if self.exc is not None:
            raise self.exc
        return {"opening_hours": "09:00-17:00", "rating": "4.8"}

    async def search_hours(self, keyword, city=None):
        self.search_calls.append((keyword, city))
        if self.exc is not None:
            raise self.exc
        return {
            "opening_hours": "09:00-21:00",
            "rating": None,
            "matched": keyword,
            "poi_id": "B00TEST01",
        }


def run(coro):
    return asyncio.run(coro)


def v0_reply(items, assumptions=None) -> str:
    return json.dumps(
        {"items": items, "assumptions": assumptions or []}, ensure_ascii=False
    )


def edit_reply(reply: str, diffs, need=None, wishes=None) -> str:
    payload = {"reply": reply, "diffs": diffs, "need_clarification": need or []}
    if wishes is not None:
        payload["wishes"] = wishes
    return json.dumps(payload, ensure_ascii=False)


def repair_reply(diffs) -> str:
    return json.dumps({"diffs": diffs}, ensure_ascii=False)


SH_HZ_ITEMS = [
    {
        "name": "外滩",
        "city": "上海",
        "category": "sight",
        "day": 1,
        "duration_minutes": 90,
    },
    {
        "name": "豫园",
        "city": "上海",
        "category": "sight",
        "day": 1,
        "duration_minutes": 60,
    },
    {
        "name": "西湖",
        "city": "杭州",
        "category": "sight",
        "day": 2,
        "duration_minutes": 120,
    },
]

AMAP_POIS = [
    {
        "name": "外滩",
        "city": "上海",
        "category": "风景名胜",
        "source_poi_id": "B000A7BD6C",
        "location": {"lon": 121.49, "lat": 31.24},
        "address": "中山东一路",
        "opening_hours": "全年 全天开放",
    },
    {
        "name": "豫园",
        "city": "上海",
        "category": "风景名胜",
        "source_poi_id": "B000A7U3C8",
        "location": {"lon": 121.49, "lat": 31.23},
        "address": "文昌路",
        "opening_hours": "09:00-17:00",
    },
    {
        "name": "东方明珠",
        "city": "上海",
        "category": "风景名胜",
        "source_poi_id": "B000A8UIN8",
        "location": {"lon": 121.50, "lat": 31.24},
    },
]


def all_visits(session):
    return [i for d in session.plan.days for i in d.items if isinstance(i, VisitItem)]


def all_transfers(session):
    return [
        i for d in session.plan.days for i in d.items if isinstance(i, TransferItem)
    ]


def hard_errors(session):
    return [v for v in current_violations(session) if v.severity == RuleSeverity.error]


# --- clarify flow (§6.1: <=2 questions, no LLM burned) ---------------------


def test_start_incomplete_request_clarifies_without_llm():
    agent = PlanningAgent(ExplodingLLM())  # any LLM call would raise
    session = run(agent.start(device_id="d1", cities=[], days=0))
    assert session.state == "clarify"
    assert session.clarify_count == 1
    assert session.plan is None
    questions = clarify_questions(session)
    assert any("天" in q for q in questions)
    assert any("城市" in q for q in questions)


def test_clarify_asks_origin_and_destination_first():
    agent = PlanningAgent(ExplodingLLM())
    session = run(agent.start(device_id="d1", cities=[], days=0))
    questions = clarify_questions(session)
    # 城市问题排第一，且明确问出发地/目的地（用户令 1018）
    assert "出发" in questions[0] and "目的地" in questions[0]


def test_clarify_answer_completes_then_generates_v0():
    agent = PlanningAgent(ScriptedLLM([v0_reply(SH_HZ_ITEMS)]))
    session = run(agent.start(device_id="d1", cities=[], days=0))
    assert session.state == "clarify"
    session, reply, change = run(agent.message(session, "想去上海和杭州，玩 2 天"))
    assert session.state == "ready"
    assert session.cities == ["上海", "杭州"]
    assert session.days == 2
    assert session.plan is not None and session.plan.days
    assert change is None
    assert "初版行程" in reply


def test_clarify_exhausted_forces_v0_on_default_assumptions():
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm)
    session = run(agent.start(device_id="d1", cities=[], days=0))
    session, reply1, _ = run(agent.message(session, "还没想好"))
    assert session.state == "clarify"
    assert session.clarify_count == 2
    session, reply2, _ = run(agent.message(session, "你看着办"))
    assert session.state == "ready"
    assert llm.calls == 1  # only the forced v0 generation
    assert any("默认" in a for a in session.assumptions)
    assert reply2


# --- sightseeing preference round (one ask before v0) -----------------------


def test_start_complete_without_preferences_asks_preference():
    agent = PlanningAgent(ExplodingLLM())  # the round must not burn the LLM
    session = run(agent.start(device_id="d1", cities=["上海"], days=3))
    assert session.state == "clarify"
    assert session.clarify_count == 1
    assert session.pref_asked is True
    questions = clarify_questions(session)
    assert any(("偏好" in q or "观光" in q) and "无特别要求" in q for q in questions)
    assert any("博物馆人文" in q and "慢慢逛" in q for q in questions)


def test_preference_answer_is_stored_and_generates_v0():
    agent = PlanningAgent(ScriptedLLM([v0_reply(SH_HZ_ITEMS)]))
    session = run(agent.start(device_id="d1", cities=["上海", "杭州"], days=2))
    assert session.state == "clarify"
    session, reply, change = run(agent.message(session, "喜欢博物馆和美食"))
    assert session.state == "ready"
    assert session.preferences == "喜欢博物馆和美食"
    assert session.pref_asked is False
    assert session.plan is not None and session.plan.days
    assert "初版行程" in reply
    assert change is None


def test_preference_skip_word_keeps_preferences_empty_and_generates_v0():
    agent = PlanningAgent(ScriptedLLM([v0_reply(SH_HZ_ITEMS)]))
    session = run(agent.start(device_id="d1", cities=["上海"], days=2))
    session, reply, _ = run(agent.message(session, "无特别要求"))
    assert session.state == "ready"
    assert session.preferences == ""
    assert session.pref_asked is False
    assert session.plan is not None and session.plan.days
    assert session.assumptions
    assert "初版行程" in reply


def test_start_with_preferences_generates_v0_without_preference_round():
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm)
    session = run(
        agent.start(device_id="d1", cities=["上海"], days=2, preferences="亲子")
    )
    assert session.state == "ready"
    assert session.pref_asked is False
    assert session.clarify_count == 0
    assistant_texts = [m.content for m in session.history if m.role == "assistant"]
    assert not any("无特别要求" in t for t in assistant_texts)
    assert llm.calls == 1  # straight to v0, no preference detour


# --- v0 generation ---------------------------------------------------------


def test_v0_amap_transfer_and_solved_schedule():
    items = [
        # 出发城市的景点按产品规则 2026-10-19 被丢弃并写假设
        {
            "name": "外滩",
            "city": "上海",
            "category": "sight",
            "day": 1,
            "duration_minutes": 90,
        },
        {
            "name": "豫园",
            "city": "杭州",
            "category": "sight",
            "day": 1,
            "duration_minutes": 60,
        },
        {
            "name": "拙政园",
            "city": "苏州",
            "category": "sight",
            "day": 2,
            "duration_minutes": 90,
        },
        # 返程占位 17:00，最后一天仍装得下活动
        {
            "name": "留园",
            "city": "苏州",
            "category": "sight",
            "day": 3,
            "duration_minutes": 60,
        },
    ]
    llm = ScriptedLLM([v0_reply(items)])
    amap = StubAmap(AMAP_POIS)
    agent = PlanningAgent(llm, amap_client=amap)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州", "苏州"],
            days=3,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    plan = session.plan
    assert len(plan.days) == 3
    visits = all_visits(session)
    transfers = all_transfers(session)
    assert len(visits) == 3  # 外滩位于出发城市，未列入行程
    assert "外滩" not in {v.name for v in visits}
    assert any(
        "出发城市 上海" in a and "出发日只安排交通" in a for a in session.assumptions
    )
    # 交通段 = 目的地数 + 1（出发段、城际段、返程段）
    assert len(transfers) == 3
    dep, hop, ret = transfers
    assert (dep.from_city, dep.to_city, dep.day) == ("上海", "杭州", 1)
    assert dep.mode == "train"
    assert dep.train_no == "G7351"
    assert (hop.from_city, hop.to_city, hop.day) == ("杭州", "苏州", 2)
    assert (ret.from_city, ret.to_city, ret.day) == ("苏州", "上海", 3)
    assert ret.start_time == time(17, 0)  # 返程占位 17:00，白天留给活动
    # 出发城市不再抓 POI 候选（产品规则 2026-10-19）
    assert [city for _, city in amap.calls] == ["杭州", "苏州"]
    # solver placed every visit (§6.9 pipeline backend)
    assert all(v.start_time is not None for v in visits)
    # 最后一天仍有活动（返程段晚出发的收益）
    assert any(v.name == "留园" and v.day == 3 for v in visits)
    # amap enrichment: matched candidate name carries the source poi_id
    by_name = {v.name: v for v in visits}
    assert by_name["豫园"].poi_id == "B000A7U3C8"
    # every recommendation carries its concrete address + opening hours
    assert by_name["豫园"].address == "文昌路"
    assert by_name["豫园"].opening_hours == "09:00-17:00"
    assert "假设中等节奏、不早起" in session.assumptions


def _two_stop_items():
    return [
        {
            "name": "豫园",
            "city": "上海",
            "category": "sight",
            "day": 2,
            "duration_minutes": 60,
        },
        {
            "name": "外滩",
            "city": "上海",
            "category": "sight",
            "day": 2,
            "duration_minutes": 90,
        },
    ]


def _day2_visits(session):
    by_day = {}
    for v in all_visits(session):
        by_day.setdefault(v.day, []).append(v)
    return by_day.get(2, [])


def test_v0_adjacent_stops_enriched_by_amap_distance():
    """v2.4.3: measured walking legs replace the straight-line estimate."""
    llm = ScriptedLLM([v0_reply(_two_stop_items())])
    amap = DistanceAmap(AMAP_POIS)
    agent = PlanningAgent(llm, amap_client=amap, auto_restaurants=False)
    session = run(
        agent.start(
            device_id="d1",
            cities=["杭州", "上海"],
            days=2,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    day2 = _day2_visits(session)
    assert {v.name for v in day2} == {"豫园", "外滩"}
    first = day2[0]
    # measured, not estimated: leg_source flips and the stub's numbers win
    assert first.leg_source == "amap"
    assert first.distance_to_next_km == pytest.approx(1.1, abs=0.01)
    assert first.next_walk_minutes == 15
    assert amap.route_calls, "legs must be measured via walking_route"
    assert amap.route_calls[0][2] and amap.route_calls[0][3], (
        "POI ids should ride along for route snapping"
    )


class CtripStub:
    """ctrip_hours reader stub (agent-injected, no network)."""

    def __init__(self):
        self.calls = []

    async def hours_for(self, city, name):
        self.calls.append((city, name))
        return "全年全天开放"


class NullCtrip:
    async def hours_for(self, city, name):
        return None


def test_v0_store_hit_fills_without_live_calls():
    """v2.4.4: a store hit fills the card with zero live calls."""
    store = PoiDetailStore()  # memory mode
    store.upsert(
        "B000A7U3C8",
        city="上海",
        name="豫园",
        address="文昌路",
        opening_hours="09:00-17:00",
        hours_source="amap_v5_detail",
    )
    amap = DistanceAmap(AMAP_POIS)
    ctrip = CtripStub()
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(_two_stop_items())]),
        amap_client=amap,
        poi_details=store,
        ctrip_hours=ctrip,
        auto_restaurants=False,
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["杭州", "上海"],
            days=2,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    visits = {v.name: v for v in all_visits(session)}
    assert visits["豫园"].opening_hours == "09:00-17:00"
    assert visits["豫园"].address == "文昌路"
    assert ctrip.calls == []  # 库命中 → 不触网
    assert amap.hours_calls == []


def test_v0_store_miss_runs_ctrip_first_then_appends():
    """v2.4.4 修订: 库未命中当场走链，携程先命中即 APPEND 入库。"""
    pois = [
        {
            "name": "豫园",
            "city": "上海",
            "category": "风景名胜",
            "source_poi_id": "B000A7U3C8",
            "location": {"lon": 121.49, "lat": 31.23},
            "address": "文昌路",
            "opening_hours": None,
        },
        {
            "name": "外滩",
            "city": "上海",
            "category": "风景名胜",
            "source_poi_id": "B000A7BD6C",
            "location": {"lon": 121.49, "lat": 31.24},
            "address": "中山东一路",
            "opening_hours": None,
        },
    ]
    store = PoiDetailStore()
    amap = DistanceAmap(pois)
    ctrip = CtripStub()
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(_two_stop_items())]),
        amap_client=amap,
        poi_details=store,
        ctrip_hours=ctrip,
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["杭州", "上海"],
            days=2,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    assert ctrip.calls, "携程应先于高德被问询"
    assert amap.hours_calls == [], "携程命中后高德不应再被问询"
    got = store.get("B000A7U3C8")
    assert got["opening_hours"] == "全年全天开放"
    assert got["hours_source"] == "ctrip"


def test_v0_store_miss_no_poi_id_search_appends():
    """v2.4.4 修订: 无 poi_id 条目走 携程(miss)→关键词搜索 并按 amap id 入库。"""
    pois = [
        {
            "name": "豫园",
            "city": "上海",
            "category": "风景名胜",
            "location": {"lon": 121.49, "lat": 31.23},
            "address": "文昌路",
            "opening_hours": None,
        },
        {
            "name": "外滩",
            "city": "上海",
            "category": "风景名胜",
            "location": {"lon": 121.49, "lat": 31.24},
            "address": "中山东一路",
            "opening_hours": None,
        },
    ]
    store = PoiDetailStore()
    amap = DistanceAmap(pois)
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(_two_stop_items())]),
        amap_client=amap,
        poi_details=store,
        ctrip_hours=NullCtrip(),
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["杭州", "上海"],
            days=2,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    assert amap.search_calls, "关键词搜索是高德侧兜底"
    filled = [v for v in all_visits(session) if v.opening_hours == "09:00-21:00"]
    assert filled, "无 poi_id 条目应被关键词搜索回填"
    assert store.get("B00TEST01") is not None, "命中应 APPEND 入库"


def test_v0_poi_details_read_from_store():
    """v2.4.4: planning reads address/hours from the poi detail store."""
    store = PoiDetailStore()  # memory mode (no session factory)
    store.upsert(
        "B000A7U3C8",
        city="上海",
        name="豫园",
        address="文昌路",
        opening_hours="09:00-17:00",
        hours_source="amap_v5_detail",
    )
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(_two_stop_items())]),
        amap_client=StubAmap(AMAP_POIS),
        poi_details=store,
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["杭州", "上海"],
            days=2,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    visits = {v.name: v for v in all_visits(session)}
    assert visits["豫园"].opening_hours == "09:00-17:00"
    assert visits["豫园"].address == "文昌路"
    # 外滩 carries v3 payload hours → written through as a job seed
    assert store.get("B000A7BD6C") is not None


def test_v0_leg_enrich_degrades_to_estimate():
    """No measurement capability -> the straight-line estimate stays."""
    llm = ScriptedLLM([v0_reply(_two_stop_items())])
    agent = PlanningAgent(llm, amap_client=StubAmap(AMAP_POIS), auto_restaurants=False)
    session = run(
        agent.start(
            device_id="d1",
            cities=["杭州", "上海"],
            days=2,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    first = _day2_visits(session)[0]
    assert first.leg_source == "estimate"
    assert first.distance_to_next_km == pytest.approx(1.11, abs=0.05)


def test_v0_amap_failure_falls_back_to_placeholder_candidates():
    llm = ScriptedLLM(
        [
            v0_reply(
                [
                    {
                        "name": "北京博物馆",
                        "city": "北京",
                        "category": "sight",
                        "day": 1,
                        "duration_minutes": 60,
                    },
                    {
                        "name": "北京老街",
                        "city": "北京",
                        "category": "sight",
                        "day": 1,
                        "duration_minutes": 60,
                    },
                ]
            )
        ]
    )
    agent = PlanningAgent(llm, amap_client=StubAmap(exc=RuntimeError("amap down")))
    session = run(
        agent.start(
            device_id="d1",
            cities=["北京"],
            days=1,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    assert any("占位" in a for a in session.assumptions)
    assert len(session.plan.days[0].items) == 2


class PerCityAmap:
    """Different canned POIs per city (real-ish coordinates)."""

    def __init__(self, pois_by_city: dict[str, list[dict]]) -> None:
        self.pois_by_city = pois_by_city
        self.calls: list[str | None] = []

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append(city)
        return self.pois_by_city.get(city, [])


def _poi(name: str, lon: float, lat: float) -> dict:
    return {"name": name, "location": {"lon": lon, "lat": lat}}


def test_v0_uncovered_pair_without_coords_degrades_to_flight():
    llm = ScriptedLLM(
        [
            v0_reply(
                [
                    {
                        "name": "莫高窟",
                        "city": "敦煌",
                        "category": "sight",
                        "day": 1,
                        "duration_minutes": 120,
                    },
                    {
                        "name": "中山桥",
                        "city": "兰州",
                        "category": "sight",
                        "day": 2,
                        "duration_minutes": 60,
                    },
                ]
            )
        ]
    )
    agent = PlanningAgent(llm)  # no amap → no anchors → distance unknown
    session = run(
        agent.start(
            device_id="d1",
            cities=["敦煌", "兰州"],
            days=2,
            preferences="博物馆",
        )
    )
    transfers = all_transfers(session)
    # 敦煌→兰州 is ~1000km: a 90-minute drive is nonsense, placeholder as flight
    assert transfers[0].mode == "flight"
    assert transfers[0].duration_minutes == 180
    assert any("无班次" in a for a in session.assumptions)
    # the fixed 09:00 flight window still lets the solver place everything
    assert all(v.start_time is not None for v in all_visits(session))


def test_v0_far_pair_with_coords_is_flight_placeholder():
    llm = ScriptedLLM(
        [
            v0_reply(
                [
                    {
                        "name": "天涯海角",
                        "city": "三亚",
                        "category": "sight",
                        "day": 1,
                        "duration_minutes": 120,
                    },
                    {
                        "name": "中央大街",
                        "city": "哈尔滨",
                        "category": "sight",
                        "day": 2,
                        "duration_minutes": 90,
                    },
                ]
            )
        ]
    )
    amap = PerCityAmap(
        {
            "三亚": [_poi("天涯海角", 109.22, 18.24)],
            "哈尔滨": [_poi("中央大街", 126.62, 45.76)],
        }
    )
    agent = PlanningAgent(llm, amap_client=amap)
    session = run(
        agent.start(
            device_id="d1",
            cities=["北京", "三亚", "哈尔滨"],
            days=4,
            preferences="海岛与冰雪",
        )
    )
    transfers = all_transfers(session)
    assert len(transfers) == 3  # 出发段 + 城际段 + 返程段
    # 三亚→哈尔滨 两端都有坐标锚点（均为目的地，出发城市不抓候选），
    # 直线约 3400 公里：90 分钟车程不合理，占位为航班
    hop = transfers[1]
    assert (hop.from_city, hop.to_city, hop.day) == ("三亚", "哈尔滨", 2)
    assert hop.mode == "flight"
    assert hop.duration_minutes == 180
    assert [c for c in amap.calls] == ["三亚", "哈尔滨"]  # origin 无 amap 调用
    assert any("航班" in a and "公里" in a for a in session.assumptions)


def test_v0_near_pair_with_coords_is_car_placeholder():
    llm = ScriptedLLM(
        [
            v0_reply(
                [
                    {
                        "name": "外滩",
                        "city": "上海",
                        "category": "sight",
                        "day": 1,
                        "duration_minutes": 90,
                    },
                    {
                        "name": "拙政园",
                        "city": "苏州",
                        "category": "sight",
                        "day": 2,
                        "duration_minutes": 90,
                    },
                ]
            )
        ]
    )
    amap = PerCityAmap(
        {
            "上海": [_poi("外滩", 121.49, 31.24)],
            "苏州": [_poi("拙政园", 120.62, 31.33)],  # ~85km from 上海
        }
    )
    agent = PlanningAgent(llm, amap_client=amap)
    session = run(
        agent.start(
            device_id="d1",
            cities=["南京", "上海", "苏州"],
            days=3,
            preferences="园林",
        )
    )
    transfers = all_transfers(session)
    assert len(transfers) == 3
    # 上海→苏州 两端都有坐标锚点（同为目的地），~85km 同域腿按驾车占位
    hop = transfers[1]
    assert (hop.from_city, hop.to_city, hop.day) == ("上海", "苏州", 2)
    assert hop.mode == "car"
    assert 60 <= hop.duration_minutes <= 180
    assert [c for c in amap.calls] == ["上海", "苏州"]  # origin 无 amap 调用
    assert any("驾车" in a for a in session.assumptions)


def test_v0_poi_day_outside_city_window_is_clamped():
    llm = ScriptedLLM(
        [
            v0_reply(
                [
                    {
                        "name": "西湖",
                        "city": "杭州",
                        "category": "sight",
                        "day": 3,  # wrong: 杭州 window is day 1 only
                        "duration_minutes": 120,
                    },
                    {
                        "name": "拙政园",
                        "city": "苏州",
                        "category": "sight",
                        "day": 2,
                        "duration_minutes": 90,
                    },
                ]
            )
        ]
    )
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["北京", "杭州", "苏州"],
            days=3,
            preferences="经典",
        )
    )
    hangzhou = [v for v in all_visits(session) if v.city == "杭州"]
    assert hangzhou and all(v.day == 1 for v in hangzhou)
    assert any("城市日程" in a for a in session.assumptions)


def test_v0_placeholder_selection_respects_city_windows():
    agent = PlanningAgent(
        ExplodingLLM(), amap_client=StubAmap(exc=RuntimeError("amap down"))
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州", "苏州"],
            days=4,
            preferences="无",
        )
    )
    visits = all_visits(session)
    hangzhou = [v for v in visits if v.city == "杭州"]
    suzhou = [v for v in visits if v.city == "苏州"]
    assert hangzhou and all(v.day == 1 for v in hangzhou)
    assert suzhou and all(2 <= v.day <= 4 for v in suzhou)
    # 出发城市不再产生任何占位候选（产品规则 2026-10-19）
    assert not [v for v in visits if v.city == "上海"]


def test_v0_solver_failure_delivers_sequenced_with_assumption():
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, solver=lambda plan, **kw: None)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州"],
            days=2,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    assert any("求解器未收敛" in a for a in session.assumptions)
    # Degraded solver still ships timed items (fallback sequencing) —
    # 未排 items are invisible to validation and broke transfer-day checks.
    assert all(v.start_time is not None for v in all_visits(session))


# --- LLM degradation (parse retry -> placeholder plan) ---------------------


def test_v0_llm_down_degrades_to_placeholder_plan():
    agent = PlanningAgent(ExplodingLLM())
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海"],
            days=2,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    assert any("LLM 不可用" in a for a in session.assumptions)
    visits = all_visits(session)
    assert len(visits) == 4  # four built-in placeholder candidates
    names = {v.name for v in visits}
    assert "上海博物馆" in names
    assert "上海地标" in names


def test_v0_bad_json_retries_once_then_degrades():
    llm = ScriptedLLM(["完全不是 JSON", "也不是什么合法 {JSON"])
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海"],
            days=1,
            preferences="博物馆",
        )
    )
    assert llm.calls == 2  # one attempt + one retry
    assert any("LLM 不可用" in a for a in session.assumptions)
    assert session.plan.days[0].items


# --- conversational iteration (diffs through the pipeline) -----------------


def test_message_move_diff_changes_plan_and_reports_change():
    items = [
        {
            "name": "外滩",
            "city": "上海",
            "category": "sight",
            "day": 1,
            "duration_minutes": 90,
        },  # 出发城市：装配时丢弃
        {
            "name": "故宫",
            "city": "北京",
            "category": "sight",
            "day": 2,
            "duration_minutes": 90,
        },
        {
            "name": "天坛",
            "city": "北京",
            "category": "sight",
            "day": 3,
            "duration_minutes": 60,
        },  # v2
    ]
    llm = ScriptedLLM(
        [
            v0_reply(items),
            edit_reply(
                "已把天坛挪到最后一天", [{"op": "move", "item_id": "v2", "new_day": 4}]
            ),
        ]
    )
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州", "北京"],
            days=4,
            preferences="博物馆",
        )
    )
    session, reply, change = run(agent.message(session, "把天坛挪到最后一天"))
    assert "天坛" in reply
    assert change is not None
    assert change.affected_items_count == 1
    assert change.change_summary
    moved = next(i for d in session.plan.days for i in d.items if i.item_id == "v2")
    # Day 4 carries the 北京→上海 return leg in the evening (no in-window
    # train → 17:00 placeholder), so the moved POI keeps the morning slot:
    # 末日 = 活动 + 返程.
    assert moved.day == 4
    assert not hard_errors(session)


def test_selfrepair_recovers_from_hard_violation():
    # Day 1 carries the 上海→杭州 train (07:15-08:16 + 90min buffer ⇒ 西湖
    # can only start ≥09:46); the first diff retimes 西湖 to 09:00 -> rule-4
    # buffer violation -> repair round fixes it.
    items = [
        {
            "name": "西湖",
            "city": "杭州",
            "category": "sight",
            "day": 1,
            "duration_minutes": 120,
        },
        {
            "name": "拙政园",
            "city": "苏州",
            "category": "sight",
            "day": 2,
            "duration_minutes": 90,
        },
    ]
    llm = ScriptedLLM(
        [
            v0_reply(items),
            edit_reply(
                "好的", [{"op": "retime", "item_id": "v1", "new_start_time": "09:00"}]
            ),
            repair_reply(
                [{"op": "retime", "item_id": "v1", "new_start_time": "10:00"}]
            ),
        ]
    )
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州", "苏州"],
            days=3,
            preferences="博物馆",
        )
    )
    session, reply, change = run(agent.message(session, "西湖改到九点开始"))
    assert llm.calls == 3  # v0 + edit + one repair round
    item = next(i for d in session.plan.days for i in d.items if i.item_id == "v1")
    assert item.start_time == time(10, 0)
    assert change is not None
    assert not hard_errors(session)


def test_selfrepair_exhausted_delivers_half_product():
    items = [
        {
            "name": "西湖",
            "city": "杭州",
            "category": "sight",
            "day": 1,
            "duration_minutes": 120,
        },
        {
            "name": "拙政园",
            "city": "苏州",
            "category": "sight",
            "day": 2,
            "duration_minutes": 90,
        },
    ]
    bad_edit = edit_reply(
        "试试", [{"op": "retime", "item_id": "v1", "new_start_time": "09:00"}]
    )
    bad_repairs = [
        repair_reply([{"op": "retime", "item_id": "v1", "new_start_time": "09:00"}])
        for _ in range(MAX_REPAIR_ROUNDS)
    ]
    llm = ScriptedLLM([v0_reply(items), bad_edit] + bad_repairs)
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州", "苏州"],
            days=3,
            preferences="博物馆",
        )
    )
    session, reply, change = run(agent.message(session, "西湖改到九点开始"))
    assert llm.calls == 2 + MAX_REPAIR_ROUNDS  # v0 + edit + 3 repairs
    assert "半成品" in reply
    assert change is not None  # the applied-but-invalid diffs still reported
    assert hard_errors(session)  # rule-4 buffer violation shipped, annotated


def test_message_unknown_item_keeps_plan_unchanged():
    # PipelineError on every round (no valid item id) -> change does not land.
    llm = ScriptedLLM(
        [
            v0_reply(SH_HZ_ITEMS),
            edit_reply("挪一下", [{"op": "move", "item_id": "v999", "new_day": 2}]),
        ]
        + [
            repair_reply([{"op": "move", "item_id": "v999", "new_day": 2}])
            for _ in range(MAX_REPAIR_ROUNDS)
        ]
    )
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州"],
            days=2,
            preferences="博物馆",
        )
    )
    before = session.plan.model_copy(deep=True)
    session, reply, change = run(agent.message(session, "随便挪一个"))
    assert "未能生效" in reply
    assert session.plan == before
    assert change is None  # nothing was applied


def test_message_edit_llm_timeout_keeps_conversation_alive():
    # v0 burns attempts 1-2 (placeholder plan), the edit turn burns 3-4:
    # every chat() raises ReadTimeout -> friendly in-band reply, no 502.
    llm = FlakyLLM(failures=4, then="never reached")
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海"],
            days=1,
            preferences="博物馆",
        )
    )
    before = session.plan.model_copy(deep=True)
    session, reply, change = run(agent.message(session, "把豫园挪到第二天"))
    assert llm.calls == 4  # v0 two attempts + edit two attempts
    assert "模型暂时无响应" in reply
    assert session.plan == before
    assert change is None
    assert session.history[-1].role == "assistant"


def test_message_edit_parse_failure_retried_then_success():
    # Edit draw 1 is unparseable prose -> resampled (v0 loop shape), draw 2
    # delivers a valid diff and it lands. No "请再发一次" punt.
    items = [
        {
            "name": "外滩",
            "city": "上海",
            "category": "sight",
            "day": 1,
            "duration_minutes": 90,
        },
        {
            "name": "豫园",
            "city": "上海",
            "category": "sight",
            "day": 1,
            "duration_minutes": 60,
        },
    ]
    llm = ScriptedLLM(
        [
            v0_reply(items),
            "抱歉我走神了这不是 JSON",
            edit_reply("已删除", [{"op": "remove", "item_id": "v1"}]),
        ]
    )
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海"],
            days=1,
            preferences="博物馆",
        )
    )
    session, reply, change = run(agent.message(session, "删掉外滩"))
    assert llm.calls == 3  # v0 one + edit two (first unparseable)
    assert "已删除" in reply
    assert change is not None


def test_message_edit_parse_failure_exhausted_keeps_conversation_alive():
    # Both edit draws unparseable -> friendly in-band reply, plan untouched.
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS), "走神第一次", "走神第二次"])
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州"],
            days=2,
            preferences="博物馆",
        )
    )
    before = session.plan.model_copy(deep=True)
    session, reply, change = run(agent.message(session, "随便改改"))
    assert llm.calls == 3
    assert "没能解析" in reply
    assert session.plan == before
    assert change is None
    assert session.history[-1].role == "assistant"


def test_message_edit_llm_retry_then_success():
    # v0 burns attempts 1-2 (placeholder plan), attempt 3 still stalls,
    # attempt 4 delivers a valid edit -> the diff lands normally.
    llm = FlakyLLM(
        failures=3,
        then=edit_reply("已删除", [{"op": "remove", "item_id": "v1"}]),
    )
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海"],
            days=1,
            preferences="博物馆",
        )
    )
    session, reply, change = run(agent.message(session, "删掉第一个景点"))
    assert llm.calls == 4
    assert "已删除" in reply
    assert change is not None
    assert all(i.item_id != "v1" for d in session.plan.days for i in d.items)


def test_message_raw_exception_leaves_stored_session_intact():
    # 1018h incident: an unclassified exception mid-message used to poison
    # the caller's session (state="planning", plan=None) -> every later
    # message hit the plan-not-None assert with a 500.
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州"],
            days=2,
            preferences="博物馆",
        )
    )
    hist_len = len(session.history)

    class RawBoomLLM:
        name = "raw-boom"

        async def chat(self, messages, *, temperature=0.3, max_tokens=None):
            raise RuntimeError("unclassified backend crash")

    with pytest.raises(RuntimeError):
        run(PlanningAgent(RawBoomLLM()).message(session, "改一下"))

    assert len(session.history) == hist_len  # stored session untouched
    assert session.state == "ready"
    assert session.plan is not None


def test_v0_hours_chain_fills_every_item_across_chunks():
    """2026-10-20 latency fix: more than HOURS_CHUNK missing items run
    in concurrent chunks — every item must still be filled and
    appended to the store."""
    pois = [
        {
            "name": f"景点{idx}",
            "city": "上海",
            "category": "风景名胜",
            "source_poi_id": f"B0000{idx:02d}",
            "location": {"lon": 121.49 + idx * 0.01, "lat": 31.23},
            "address": f"路{idx}",
            "opening_hours": None,
        }
        for idx in range(8)
    ]
    items = [
        {
            "name": f"景点{idx}",
            "city": "上海",
            "day": idx // 2 + 1,
            "duration_minutes": 60,
        }
        for idx in range(8)
    ]
    store = PoiDetailStore()
    amap = DistanceAmap(pois)
    ctrip = CtripStub()
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]),
        amap_client=amap,
        poi_details=store,
        ctrip_hours=ctrip,
        auto_restaurants=False,  # 8.2.4：腿/小时链断言条目数，不插餐厅
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["杭州", "上海"],
            days=4,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    visits = all_visits(session)
    assert len(visits) == 8
    assert all(v.opening_hours == "全年全天开放" for v in visits)
    assert len(ctrip.calls) == 8
    assert amap.hours_calls == []  # ctrip hit → v5 never asked
    assert all(store.get(f"B0000{idx:02d}") for idx in range(8))


# --- rule 19 carve-out: named edits release pins; deletes hit trip center ---


class UnwantRecorder:
    """trip-item service stub capturing mark_unwanted calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str | None]] = []

    def list_groups(self, itinerary_id: str | None = None) -> dict:
        return {"wishlist": [], "scheduled": [], "booked": [], "unwanted": []}

    def mark_unwanted(self, name, *, itinerary_id=None, city=None):
        self.calls.append((name, itinerary_id, city))
        return {"name": name, "status": "unwanted"}


def _ready_hz_session(agent):
    """上海→杭州 2 days: departure day is travel-only, so the plan's
    surviving visit is 西湖 (day 2)."""
    session = run(agent.start(device_id="d1", cities=["上海", "杭州"], days=2))
    assert session.state == "clarify"
    session, _, _ = run(agent.message(session, "喜欢博物馆"))
    assert session.state == "ready"
    return session


def test_named_retime_on_pinned_item_applies_and_stays_pinned():
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm)
    session = _ready_hz_session(agent)
    westlake = next(v for v in all_visits(session) if v.name == "西湖")
    westlake.pinned = True
    llm.replies.append(
        edit_reply(
            "已调整",
            [
                {
                    "op": "retime",
                    "item_id": westlake.item_id,
                    "new_start_time": "10:00",
                }
            ],
        )
    )
    session, reply, _ = run(agent.message(session, "把西湖改到 10:00 开始"))
    assert session.state == "ready"
    westlake = next(v for v in all_visits(session) if v.name == "西湖")
    assert westlake.start_time == time(10, 0)
    assert westlake.pinned is True  # re-pin follows the item to its new slot
    assert not hard_errors(session)
    assert "未能生效" not in reply


def test_unnamed_retime_on_pinned_item_rejected_by_rule_19():
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm)
    session = _ready_hz_session(agent)
    westlake = next(v for v in all_visits(session) if v.name == "西湖")
    westlake.pinned = True
    llm.replies.append(
        edit_reply(
            "已调整",
            [
                {
                    "op": "retime",
                    "item_id": westlake.item_id,
                    "new_start_time": "10:00",
                }
            ],
        )
    )
    llm.replies.append(repair_reply([]))  # repair gives up -> half-product
    session, reply, _ = run(agent.message(session, "把那里改到 10:00 开始"))
    westlake = next(v for v in all_visits(session) if v.name == "西湖")
    # Rule 19 fired: the diff was rejected in-pipeline and the violation
    # rides the half-product annotation (exhaustion ships warnings, not
    # silence); the pin itself survives the failed carve-out.
    assert "已被用户确认" in reply
    assert westlake.pinned is True


def test_conversational_remove_syncs_trip_items_only_on_success():
    recorder = UnwantRecorder()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=recorder)
    session = _ready_hz_session(agent)
    westlake = next(v for v in all_visits(session) if v.name == "西湖")
    westlake.pinned = True  # user names it in the message -> pin release applies
    iid = session.plan.itinerary_id
    llm.replies.append(
        edit_reply("已删除", [{"op": "remove", "item_id": westlake.item_id}])
    )
    session, _, _ = run(agent.message(session, "删掉西湖"))
    assert "西湖" not in {v.name for v in all_visits(session)}
    assert recorder.calls == [("西湖", iid, "杭州")]


def test_failed_removal_never_syncs_trip_items():
    recorder = UnwantRecorder()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=recorder)
    session = _ready_hz_session(agent)
    llm.replies.append(edit_reply("已删除", [{"op": "remove", "item_id": "v_none"}]))
    llm.replies.append(repair_reply([]))  # no usable repair -> diff never applied
    session, reply, _ = run(agent.message(session, "删掉西湖"))
    assert "未能生效" in reply
    assert "西湖" in {v.name for v in all_visits(session)}
    assert recorder.calls == []


# --- chat wishes land in the trip-center wishlist verbatim (2026-10-24) -----


_ADD_FACE_SHOW = {
    "op": "add",
    "item": {
        "name": "川剧变脸表演（蜀风雅韵）",
        "city": "杭州",
        "category": "sight",
        "day": 2,
        "duration_minutes": 90,
    },
}


def test_conversational_wish_stored_verbatim_not_model_name():
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=svc)
    session = _ready_hz_session(agent)
    iid = session.plan.itinerary_id
    llm.replies.append(edit_reply("已加入", [_ADD_FACE_SHOW], wishes=["看变脸表演"]))
    session, _, _ = run(agent.message(session, "我想看变脸表演"))
    # Plan holds the model-resolved venue…
    assert "川剧变脸表演（蜀风雅韵）" in {v.name for v in all_visits(session)}
    # …but the wishlist keeps the user's own words (rule 2026-10-24).
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["source"], i["note"]) for i in wish] == [
        ("看变脸表演", "chat", "来自聊天")
    ]


def test_conversational_wish_syncs_for_english_input():
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=svc)
    session = _ready_hz_session(agent)
    iid = session.plan.itinerary_id
    english = "watch the face-changing show"
    llm.replies.append(edit_reply("Added.", [], wishes=[english]))
    msg = "I want to watch the face-changing show"
    session, _, _ = run(agent.message(session, msg))
    # Wishlist keeps the English verbatim…
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["source"]) for i in wish] == [(english, "chat")]
    # …and coverage rides it into the itinerary (pinned), same as Chinese.
    added = next(v for v in all_visits(session) if v.name == english)
    assert added.pinned is True


def test_wish_captured_without_plan_diff():
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=svc)
    session = _ready_hz_session(agent)
    iid = session.plan.itinerary_id
    # 大熊猫 message-1 scenario: reply says it's covered, no diff emitted,
    # the wish alone must still reach the wishlist.
    llm.replies.append(edit_reply("已包含大熊猫", [], wishes=["看大熊猫"]))
    session, _, _ = run(agent.message(session, "我想看大熊猫"))
    assert session.state == "ready"
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["source"]) for i in wish] == [("看大熊猫", "chat")]


def test_user_named_venue_stored_verbatim():
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=svc)
    session = _ready_hz_session(agent)
    iid = session.plan.itinerary_id
    llm.replies.append(edit_reply("已加入", [_ADD_FACE_SHOW], wishes=["蜀风雅韵"]))
    run(agent.message(session, "我要去蜀风雅韵"))
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["source"]) for i in wish] == [("蜀风雅韵", "chat")]


def test_repeated_wish_reuses_row_and_restores_unwanted():
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=svc)
    session = _ready_hz_session(agent)
    iid = session.plan.itinerary_id
    svc.create("灵隐寺", source="manual", city="杭州", itinerary_id=iid)
    llm.replies.append(edit_reply("好的", [], wishes=["去灵隐寺"]))
    run(agent.message(session, "我想去灵隐寺"))
    wish = svc.list_groups(iid)["wishlist"]
    assert [i["name"] for i in wish].count("灵隐寺") == 1
    assert [(i["name"], i["source"]) for i in wish] == [("灵隐寺", "manual")]

    row = svc.list_groups(iid)["wishlist"][0]
    svc.update(row["id"], status="unwanted")
    llm.replies.append(edit_reply("好的", [], wishes=["灵隐寺"]))
    run(agent.message(session, "还是想去灵隐寺"))
    wish = svc.list_groups(iid)["wishlist"]
    assert [(i["name"], i["source"]) for i in wish] == [("灵隐寺", "manual")]
    assert svc.list_groups(iid)["unwanted"] == []


def test_wishlist_coverage_adds_missing_site_to_plan():
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=svc)
    session = _ready_hz_session(agent)
    iid = session.plan.itinerary_id
    svc.create("看变脸表演", source="chat", itinerary_id=iid, note="来自聊天")
    # A turn with no diffs and no fresh wishes still must close the gap.
    llm.replies.append(edit_reply("好的", []))
    session, _, _ = run(agent.message(session, "谢谢"))
    added = next(v for v in all_visits(session) if v.name == "看变脸表演")
    assert added.pinned is True
    assert session.state == "ready"
    assert svc.list_groups(iid)["wishlist"][0]["name"] == "看变脸表演"


def test_wishlist_coverage_skips_already_covered_wish():
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, trip_items=svc)
    session = _ready_hz_session(agent)
    # 「看变脸表演」 is covered by plan item 「川剧变脸表演（蜀风雅韵）」
    # once the wish core (变脸表演) substring-matches — no duplicate add.
    llm.replies.append(edit_reply("已加入", [_ADD_FACE_SHOW], wishes=["看变脸表演"]))
    session, _, _ = run(agent.message(session, "我想看变脸表演"))
    assert [v.name for v in all_visits(session)].count("川剧变脸表演（蜀风雅韵）") == 1


# --- wishlist absorption at v0 (2026-10-23 心愿单被规划吸收) -----------------


def _wishlist_agent(items):
    """Agent whose trip-center wishlist holds ``[(name, city)]`` entries."""
    svc = TripItemService()
    for name, city in items:
        svc.create(name, source="manual", city=city)
    return PlanningAgent(ScriptedLLM([v0_reply(SH_HZ_ITEMS)]), trip_items=svc)


def test_v0_absorbs_cityless_wishlist_into_must_visits():
    agent = _wishlist_agent([("李子坝站", None)])
    session = run(
        agent.start(device_id="d1", cities=["上海", "杭州"], days=2, preferences="亲子")
    )
    assert session.state == "ready"
    assert "李子坝站" in session.must_visits
    assert "李子坝站" in {v.name for v in all_visits(session)}
    assert any("心愿单" in a and "李子坝站" in a for a in session.assumptions)


def test_v0_absorbed_wishlist_is_pinned():
    agent = _wishlist_agent([("李子坝站", None)])
    session = run(
        agent.start(device_id="d1", cities=["上海", "杭州"], days=2, preferences="亲子")
    )
    absorbed = next(v for v in all_visits(session) if v.name == "李子坝站")
    assert absorbed.pinned is True


def test_absorb_wishlist_dedupes_same_site():
    agent = _wishlist_agent([("李子坝站", None)])
    session = run(
        agent.start(device_id="d1", cities=["上海", "杭州"], days=2, preferences="亲子")
    )
    assert session.must_visits == ["李子坝站"]
    assert agent._absorb_wishlist(session) == []  # rerun absorbs nothing new


def test_absorb_wishlist_skips_items_from_other_cities():
    agent = _wishlist_agent([("故宫", "北京")])
    session = run(
        agent.start(device_id="d1", cities=["上海", "杭州"], days=2, preferences="亲子")
    )
    assert session.must_visits == []
    assert not any("心愿单" in a for a in session.assumptions)
    assert "故宫" not in {v.name for v in all_visits(session)}


# --- start_date 出发日期持久化（2026-10-24，行程卡日期/天气基准）--------------


def test_start_date_flows_into_plan():
    agent = _wishlist_agent([("李子坝站", None)])
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州"],
            days=2,
            preferences="亲子",
            start_date="2026-10-25",
        )
    )
    assert session.state == "ready"
    assert session.start_date == "2026-10-25"
    assert session.plan.start_date == "2026-10-25"  # 随快照持久化的载体


def test_start_date_defaults_to_none():
    agent = _wishlist_agent([("李子坝站", None)])
    session = run(
        agent.start(device_id="d1", cities=["上海", "杭州"], days=2, preferences="亲子")
    )
    assert session.plan.start_date is None


def test_v0_absorbs_only_matching_city_tags():
    agent = _wishlist_agent([("李子坝站", "重庆"), ("西湖", "杭州")])
    session = run(
        agent.start(device_id="d1", cities=["上海", "杭州"], days=2, preferences="亲子")
    )
    assert session.must_visits == ["西湖"]
    assert "李子坝站" not in {v.name for v in all_visits(session)}
    assert any("心愿单" in a and "西湖" in a for a in session.assumptions)


# --- must-visit POI resolution must stay inside the trip's cities -----------


class MustVisitOnlyAmap(StubAmap):
    """Answers only the must-visit lookup; per-city keyword search is empty."""

    def __init__(self, poi: dict) -> None:
        super().__init__(pois=[poi])

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append((keywords, city))
        if keywords == POI_KEYWORD:
            return []  # per-city sight search: no results
        return self.pois


def test_must_visit_resolving_outside_trip_cities_is_rejected():
    """Junk input (a URL) once fuzzy-matched a HK office (将军澳) into a
    Chongqing plan; POIs outside the trip's cities must become placeholders."""
    amap = MustVisitOnlyAmap(
        {
            "name": "NTT Com Asia Limited",
            "city": "香港特别行政区",
            "source_poi_id": "B0FFHF2C40",
            "location": {"lon": 114.27739, "lat": 22.282694},
        }
    )
    agent = PlanningAgent(ScriptedLLM([]), amap_client=amap)
    candidates, assumptions = run(agent._collect_candidates(["重庆"], ["李子坝站"]))
    names = [c["name"] for c in candidates]
    assert "NTT Com Asia Limited" not in names
    assert "李子坝站" in names  # placeholder kept under its own name
    assert any("行程外城市" in a and "香港" in a for a in assumptions)


def test_must_visit_resolving_inside_trip_cities_is_kept():
    amap = MustVisitOnlyAmap(
        {
            "name": "李子坝(地铁站)",
            "city": "重庆市",
            "source_poi_id": "BV10045690",
            "location": {"lon": 106.53766, "lat": 29.552892},
        }
    )
    agent = PlanningAgent(ScriptedLLM([]), amap_client=amap)
    candidates, assumptions = run(agent._collect_candidates(["重庆"], ["李子坝站"]))
    resolved = [c for c in candidates if c["name"] == "李子坝(地铁站)"]
    assert resolved and resolved[0]["source_poi_id"] == "BV10045690"
    assert not any("行程外城市" in a for a in assumptions)


# --- 每时段备选 POI（v2.5.1 gap #17）----------------------------------------


# --- 品类愿望全城落实（2026-10-24 「我想茶馆喝茶」）--------------------------
# 茶馆/咖啡这类愿望不是店名：拿品类关键词走 /place/around 全城拉候选，
# 评分最高（无评分保高德综合序）的一家落实进行程，骨架 APPEND 进 pois。


class AroundAmap(StubAmap):
    """StubAmap + /place/around（关键字+坐标+半径）。"""

    def __init__(self, pois=None, around=None, exc=None):
        super().__init__(pois, exc=exc)
        self._around = around or []
        self.around_calls: list[tuple[str, str, int]] = []

    async def search_poi_around(
        self, keywords, *, location, radius=30000, page=1, offset=25
    ):
        self.around_calls.append((keywords, location, radius))
        return list(self._around)


_TEA_FAMOUS = {
    "name": "湖畔居茶楼",
    "city": "杭州",
    "category": "餐饮服务;茶艺馆;茶艺馆",
    "source_poi_id": "B-TEA-TOP",
    "location": {"lon": 120.15, "lat": 30.25},
    "address": "北山街",
    "rating": "4.7",
}

_TEA_PLAIN = {
    "name": "巷口茶馆",
    "city": "杭州",
    "category": "餐饮服务;茶艺馆;茶艺馆",
    "source_poi_id": "B-TEA-LOW",
    "location": {"lon": 120.10, "lat": 30.20},
    "address": "某路1号",
    "rating": "4.2",
}


def _teahouse_session(amap, store, svc, wish, cities=("上海", "杭州")):
    """Ready session（默认上海→杭州）；西湖带坐标充当搜索圆心，心愿单
    里有 ``wish``，下一轮 edit 回复已就位。"""
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    agent = PlanningAgent(llm, amap_client=amap, poi_details=store, trip_items=svc)
    session = run(agent.start(device_id="d1", cities=list(cities), days=2))
    assert session.state == "clarify"
    session, _, _ = run(agent.message(session, "喜欢博物馆"))
    assert session.state == "ready"
    westlake = next(v for v in all_visits(session) if v.name == "西湖")
    westlake.location = GeoPoint(lon=120.15, lat=30.25)
    svc.create(wish, source="chat", itinerary_id=session.plan.itinerary_id)
    llm.replies.append(edit_reply("好的", []))
    return agent, session


def test_category_search_keyword_detection():
    assert _category_search_keyword("喝茶") == "茶馆"
    assert _category_search_keyword("我想去喝咖啡") == "咖啡馆"
    assert _category_search_keyword("泡茶") == "茶馆"
    assert _category_search_keyword("找家茶馆坐坐") == "茶馆"
    # 专名/非品类愿望不走全城搜索
    assert _category_search_keyword("看变脸表演") is None
    assert _category_search_keyword("蜀风雅韵") is None


# --- 行程单模糊去重 (2026-10-24) -------------------------------------------


def _dup_visit(
    name: str,
    *,
    day: int = 2,
    poi: str | None = None,
    pinned: bool = False,
    city: str = "成都",
) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city=city,
        day=day,
        poi_id=poi,
        pinned=pinned,
        category="sight",
        duration_minutes=60,
    )


def test_site_dup_strips_intent_verbs_on_both_sides():
    # 线上事故对：变脸表演（川剧） vs 看变脸表演 —— 裸 _same_site 漏判
    assert _site_dup("看变脸表演", "变脸表演（川剧）")
    assert _site_dup("去喝茶", "茶馆喝茶")
    # 不同城市的具体站点不许误伤
    assert not _site_dup("成都博物馆", "重庆博物馆")
    assert not _site_dup("西湖", "外滩")


def test_dedupe_visit_keepers_merges_verb_and_venue_variants():
    first = _dup_visit("变脸表演（川剧）", pinned=True, city="成都")
    second = _dup_visit("看变脸表演", pinned=True, city="未标注")
    keepers, dropped = _dedupe_visit_keepers([first, second])
    assert [k.name for k in keepers] == ["变脸表演（川剧）"]
    assert dropped == ["看变脸表演"]


def test_dedupe_visit_keepers_richer_twin_wins_either_order():
    poor = _dup_visit("变脸表演", city="未标注")
    rich = _dup_visit("看变脸表演", poi="B-1", city="成都")
    keepers, dropped = _dedupe_visit_keepers([poor, rich])
    assert [k.item_id for k in keepers] == [rich.item_id]
    assert dropped == ["变脸表演"]
    keepers2, dropped2 = _dedupe_visit_keepers([rich, poor])
    assert [k.item_id for k in keepers2] == [rich.item_id]
    assert dropped2 == ["变脸表演"]


def test_dedupe_visit_keepers_keeps_distinct_sites():
    a = _dup_visit("成都博物馆", city="成都")
    b = _dup_visit("重庆博物馆", day=1, city="重庆")
    c = _dup_visit("重庆老街", day=1, city="重庆")
    keepers, dropped = _dedupe_visit_keepers([a, b, c])
    assert len(keepers) == 3
    assert dropped == []


def test_category_wish_resolves_city_famous_teahouse():
    svc = TripItemService()
    amap = AroundAmap(around=[_TEA_PLAIN, _TEA_FAMOUS])
    store = PoiDetailStore()
    agent, session = _teahouse_session(amap, store, svc, "喝茶")
    session, reply, _ = run(agent.message(session, "谢谢"))
    # 圆心=西湖坐标，关键词=茶馆
    assert amap.around_calls == [("茶馆", "120.150000,30.250000", 30000)]
    added = next(v for v in all_visits(session) if v.name == "喝茶")
    assert added.category == "food"
    assert added.pinned is True
    assert added.poi_id == "B-TEA-TOP"
    assert (added.location.lon, added.location.lat) == (120.15, 30.25)
    assert "湖畔居茶楼" in reply
    # 喝茶优选成都不在本次行程 → 回复提示
    assert "成都" in reply
    # 落实出的城市写回心愿单城市列
    iid = session.plan.itinerary_id
    assert svc.list_groups(iid)["wishlist"][0]["city"] == "杭州"
    # 骨架 APPEND 进 pois（store 内存态）：名称/坐标/类别，food 归类
    row = store._memory.get("B-TEA-TOP")
    assert row is not None
    assert row["name"] == "湖畔居茶楼"
    assert row["city"] == "杭州"
    assert row["category"] == "food"
    assert row["location"] == (120.15, 30.25)


def test_category_wish_without_ratings_keeps_amap_order():
    # 两家都无评分：max 取首位 → 保持高德综合排序（权重≈知名度）自然序
    plain = {**_TEA_PLAIN, "rating": None}
    famous = {**_TEA_FAMOUS, "rating": None}
    amap = AroundAmap(around=[plain, famous])
    store = PoiDetailStore()
    agent, session = _teahouse_session(amap, store, TripItemService(), "喝茶")
    session, _, _ = run(agent.message(session, "谢谢"))
    added = next(v for v in all_visits(session) if v.name == "喝茶")
    assert added.poi_id == "B-TEA-LOW"


def test_category_wish_falls_back_to_text_search_when_around_misses():
    amap = AroundAmap(pois=[_TEA_FAMOUS], around=[])
    store = PoiDetailStore()
    agent, session = _teahouse_session(amap, store, TripItemService(), "喝茶")
    session, reply, _ = run(agent.message(session, "谢谢"))
    assert amap.around_calls  # around 先试，未命中
    added = next(v for v in all_visits(session) if v.name == "喝茶")
    assert added.poi_id == "B-TEA-TOP"
    assert "湖畔居茶楼" in reply
    assert store._memory.get("B-TEA-TOP", {}).get("category") == "food"


def test_named_wish_skips_citywide_search():
    amap = AroundAmap(around=[_TEA_FAMOUS])
    store = PoiDetailStore()
    agent, session = _teahouse_session(amap, store, TripItemService(), "看变脸表演")
    session, _, _ = run(agent.message(session, "谢谢"))
    assert amap.around_calls == []
    assert any(v.name == "看变脸表演" for v in all_visits(session))
    assert store._memory.get("B-TEA-TOP") is None


def test_wish_city_hint_routes_teahouse_to_chengdu_in_trip():
    # 喝茶优选成都：成都本次行程含 → 落成都（严格模式，不走跨城圆心）
    tea_cd = {**_TEA_FAMOUS, "city": "成都", "source_poi_id": "B-TEA-CD"}
    svc = TripItemService()
    amap = AroundAmap(pois=[tea_cd])
    store = PoiDetailStore()
    agent, session = _teahouse_session(
        amap, store, svc, "喝茶", cities=("上海", "成都")
    )
    session, _, _ = run(agent.message(session, "谢谢"))
    assert amap.around_calls == []  # 成都无坐标站点 → 不硬拉跨城 around
    assert ("茶馆", "成都") in amap.calls
    added = next(v for v in all_visits(session) if v.name == "喝茶")
    assert added.category == "food"
    assert added.city == "成都"
    assert added.poi_id == "B-TEA-CD"
    iid = session.plan.itinerary_id
    assert svc.list_groups(iid)["wishlist"][0]["city"] == "成都"


def test_named_wish_city_hint_routes_to_chengdu():
    # 变脸一般是成都：专名愿望同样吃到城市提示
    opera = {
        "name": "蜀风雅韵剧院",
        "city": "成都",
        "category": "风景名胜",
        "source_poi_id": "B-OPERA-1",
        "location": {"lon": 104.06, "lat": 30.57},
    }
    amap = AroundAmap(pois=[opera])
    store = PoiDetailStore()
    agent, session = _teahouse_session(
        amap, store, TripItemService(), "看变脸表演", cities=("上海", "成都")
    )
    session, _, _ = run(agent.message(session, "谢谢"))
    assert amap.around_calls == []
    added = next(v for v in all_visits(session) if v.name == "看变脸表演")
    assert added.city == "成都"
    assert added.poi_id == "B-OPERA-1"


def test_poi_library_hit_skips_amap():
    # 「先去POIS里找」：底库已收录的茶馆直接用，不打高德
    store = PoiDetailStore()
    store._memory["B-TEA-LIB"] = {
        "city": "杭州",
        "name": "湖畔居茶楼",
        "category": "food",
        "location": (120.15, 30.25),
        "source": "amap",
    }
    svc = TripItemService()
    amap = AroundAmap(around=[_TEA_FAMOUS])
    agent, session = _teahouse_session(amap, store, svc, "喝茶")
    session, reply, _ = run(agent.message(session, "谢谢"))
    assert amap.around_calls == []
    assert all(k == POI_KEYWORD for k, _ in amap.calls)  # 仅 v0 景点拉取
    added = next(v for v in all_visits(session) if v.name == "喝茶")
    assert added.poi_id == "B-TEA-LIB"
    assert added.pinned is True
    assert "POI 底库" in reply
    iid = session.plan.itinerary_id
    assert svc.list_groups(iid)["wishlist"][0]["city"] == "杭州"


# --- 聊天心愿城市解析：提示表→POIS 底库→高德全国→问用户（2026-10-24）--------


def _wish_sync_session(wishes, *, amap=None, store=None, cities=("上海", "杭州")):
    """Ready session，下一轮 edit 回复带 wishes（走 sync 链路，非直接
    svc.create），返回 (agent, session, svc, llm)。"""
    amap = amap if amap is not None else AroundAmap(pois=[])
    store = store if store is not None else PoiDetailStore()
    svc = TripItemService()
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS), edit_reply("好的", [], wishes=wishes)])
    agent = PlanningAgent(llm, amap_client=amap, poi_details=store, trip_items=svc)
    session = run(agent.start(device_id="d1", cities=list(cities), days=2))
    session, _, _ = run(agent.message(session, "喜欢博物馆"))
    assert session.state == "ready"
    return agent, session, svc, llm


def _wish_row(svc, iid, name):
    rows = [r for g in svc.list_groups(iid).values() for r in g if r["name"] == name]
    return rows[0] if rows else None


def test_chat_name_wish_hint_out_of_trip_recorded_not_forced():
    # 专名愿望「看变脸表演」聊天入库：提示表定成都；成都不在行程 →
    # 不跨城硬塞，心愿单挂成都并回复提示
    agent, session, svc, _ = _wish_sync_session(["看变脸表演"])
    session, reply, _ = run(agent.message(session, "谢谢"))
    iid = session.plan.itinerary_id
    assert _wish_row(svc, iid, "看变脸表演")["city"] == "成都"
    assert all(v.name != "看变脸表演" for v in all_visits(session))
    assert "已记入心愿单（成都" in reply
    assert "未含成都" in reply


def test_chat_category_wish_keeps_nearby_fallback():
    # 品类愿望不定城市（已拍板语义）：喝茶提示成都但照旧就近落实杭州
    amap = AroundAmap(pois=[_TEA_FAMOUS])
    agent, session, svc, _ = _wish_sync_session(["喝茶"], amap=amap)
    session, _, _ = run(agent.message(session, "谢谢"))
    iid = session.plan.itinerary_id
    assert any(v.name == "喝茶" for v in all_visits(session))
    assert _wish_row(svc, iid, "喝茶")["city"] == "杭州"
    assert session.pending_wish_cities == []


def test_chat_name_wish_resolved_from_poi_library_unique_city():
    # POIS 底库全库精确同名唯一（福州三坊七巷）→ 直接定福州，不打高德
    store = PoiDetailStore()
    store._memory["B-SFQX-FZ"] = {
        "city": "福州",
        "name": "三坊七巷",
        "category": "attraction",
        "location": (119.29, 26.07),
        "source": "amap",
    }
    amap = AroundAmap(pois=[])
    agent, session, svc, _ = _wish_sync_session(["三坊七巷"], amap=amap, store=store)
    session, reply, _ = run(agent.message(session, "谢谢"))
    iid = session.plan.itinerary_id
    assert _wish_row(svc, iid, "三坊七巷")["city"] == "福州"
    assert ("三坊七巷", None) not in amap.calls  # POIS 已定，没烧全国配额
    assert "未含福州" in reply


def test_chat_name_wish_falls_back_to_nationwide_amap():
    # POIS 未收 → 高德全国 text（city=None）兜底；「杭州市」去尾记杭州
    amap = AroundAmap(
        pois=[
            {
                "name": "灵隐寺",
                "city": "杭州市",
                "category": "风景名胜",
                "source_poi_id": "B-LYS-1",
                "location": {"lon": 120.09, "lat": 30.24},
            }
        ]
    )
    agent, session, svc, _ = _wish_sync_session(["灵隐寺"], amap=amap)
    session, _, _ = run(agent.message(session, "谢谢"))
    iid = session.plan.itinerary_id
    assert ("灵隐寺", None) in amap.calls
    assert _wish_row(svc, iid, "灵隐寺")["city"] == "杭州"
    assert session.pending_wish_cities == []


def test_chat_wish_unresolved_asks_then_binds_city_without_llm():
    # 全部落空 → 记追问队列并问用户；下一轮「成都」确定性入账不烧 LLM
    agent, session, svc, llm = _wish_sync_session(["人民公园"])
    session, reply, _ = run(agent.message(session, "谢谢"))
    assert session.pending_wish_cities == ["人民公园"]
    assert "人民公园" in reply and "哪个城市" in reply
    calls = llm.calls
    session, reply2, _ = run(agent.message(session, "成都"))
    iid = session.plan.itinerary_id
    assert llm.calls == calls  # 答复轮不烧 LLM
    assert _wish_row(svc, iid, "人民公园")["city"] == "成都"
    assert session.pending_wish_cities == []
    assert "已记到成都" in reply2


def test_chat_wish_answers_any_and_drop():
    # 「都可以」= 不绑城市（保持放空语义）；「不要了」= 转 unwanted
    agent, session, svc, _ = _wish_sync_session(["人民公园", "银河系景观台"])
    session, _, _ = run(agent.message(session, "谢谢"))
    assert sorted(session.pending_wish_cities) == ["人民公园", "银河系景观台"]
    session, reply, _ = run(agent.message(session, "人民公园都可以"))
    iid = session.plan.itinerary_id
    assert _wish_row(svc, iid, "人民公园")["city"] in (None, "")
    assert "不限城市" in reply
    assert session.pending_wish_cities == ["银河系景观台"]
    session, reply2, _ = run(agent.message(session, "银河系景观台不要了"))
    assert _wish_row(svc, iid, "银河系景观台")["status"] == "unwanted"
    assert session.pending_wish_cities == []
    assert "移除" in reply2


def test_chat_wish_answer_unrecognized_falls_through():
    # 答复认不出（不是城市/都可以/不要了）→ 不吃消息，正常走对话
    agent, session, svc, llm = _wish_sync_session(["人民公园"])
    session, _, _ = run(agent.message(session, "谢谢"))
    calls = llm.calls
    llm.replies.append(edit_reply("好的", []))
    session, reply, _ = run(agent.message(session, "帮我加一天"))
    assert llm.calls > calls  # 走了正常对话流程
    assert session.pending_wish_cities == ["人民公园"]  # 追问保持


# --- 0009：候选库优先 / reason / 餐厅 v0 插入 -------------------------------


class LibraryStore(PoiDetailStore):
    """top_pois_in_city 桩：返回 12 条带富化字段的库候选。"""

    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        return [
            {
                "source_poi_id": f"L{i:03d}",
                "name": f"库景点{i}",
                "city": "上海",
                "category": "attraction",
                "address": f"库路{i}",
                "opening_hours": "09:00-17:00",
                "source": "amap",
                "rating": 4.5,
                "rating_count": 1200 + i,
                "tags": ["5a"] if i == 0 else [],
                "best_visit_time": "evening" if i == 0 else "any",
                "suggested_duration_min": 90 if i == 0 else None,
                "indoor": None,
                "rain_ok": None,
                "review_tags": [],
                "intro": "简介" if i == 0 else None,
                "location": (121.4 + i * 0.01, 31.2),
            }
            for i in range(12)
        ]


def test_v0_library_first_skips_amap_when_stocked():
    amap = StubAmap(AMAP_POIS)
    items = [
        {"name": "库景点0", "city": "上海", "day": 1, "duration_minutes": 60},
        {"name": "库景点1", "city": "上海", "day": 1, "duration_minutes": 60},
    ]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]),
        amap_client=amap,
        poi_details=LibraryStore(),
        auto_restaurants=False,
    )
    session = run(
        agent.start(device_id="d1", cities=["上海"], days=1, preferences="随便")
    )
    # 库存 12 ≥ LIBRARY_MIN_CANDIDATES → 城市候选不烧 amap text
    assert amap.calls == []
    visits = all_visits(session)
    assert {v.name for v in visits} >= {"库景点0", "库景点1"}
    # 库候选的时段属性透传进 VisitItem（solver 8.2.1 联动）
    v0 = next(v for v in visits if v.name == "库景点0")
    assert v0.best_visit_time == "evening"


def test_v0_reason_rolls_into_assumptions():
    items = [
        {
            "name": "外滩",
            "city": "上海",
            "day": 1,
            "duration_minutes": 120,
            "reason": "夜景代表",
        }
    ]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]), amap_client=StubAmap(AMAP_POIS)
    )
    session = run(
        agent.start(device_id="d1", cities=["上海"], days=1, preferences="随便")
    )
    assert any("选点理由" in a and "夜景代表" in a for a in session.assumptions)


def test_v0_auto_inserts_restaurant_for_foodless_day():
    items = [
        {"name": "外滩", "city": "上海", "day": 1, "duration_minutes": 90},
        {"name": "豫园", "city": "上海", "day": 1, "duration_minutes": 90},
    ]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]), amap_client=StubAmap(AMAP_POIS)
    )
    session = run(
        agent.start(device_id="d1", cities=["上海"], days=1, preferences="随便")
    )
    foods = [v for v in all_visits(session) if v.category == "food"]
    assert len(foods) == 1  # 无 food 的日子晚餐窗插 1 家
    assert any("顺路餐厅" in a for a in session.assumptions)


# --- G1：预约制门票提示（名单 v0 兜底） -------------------------------------


def test_reservation_hint_from_seed_list():
    items = [
        {"name": "故宫", "city": "北京", "day": 1, "duration_minutes": 180},
        {"name": "外滩", "city": "上海", "day": 1, "duration_minutes": 90},
    ]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]), amap_client=StubAmap(AMAP_POIS)
    )
    session = run(
        agent.start(device_id="d1", cities=["上海", "北京"], days=2, preferences="随便")
    )
    gugong = [v for v in all_visits(session) if "故宫" in v.name]
    assert gugong and gugong[0].reservation_hint
    assert "提前 7 天" in gugong[0].reservation_hint
    assert any("预约提醒" in a for a in session.assumptions)


# --- 8.1.4：露天属性透传（H5 雨天横幅数据源） -------------------------------


def test_rain_ok_passthrough_for_rain_banner():
    class RainyStore(LibraryStore):
        def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
            rows = super().top_pois_in_city(city, limit, exclude_food=exclude_food)
            rows[0]["rain_ok"] = "no"
            rows[1]["rain_ok"] = "yes"
            return rows

    items = [
        {"name": "库景点0", "city": "上海", "day": 1, "duration_minutes": 60},
        {"name": "库景点1", "city": "上海", "day": 1, "duration_minutes": 60},
    ]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]),
        amap_client=StubAmap(AMAP_POIS),
        poi_details=RainyStore(),
        auto_restaurants=False,
    )
    session = run(
        agent.start(device_id="d1", cities=["上海"], days=1, preferences="随便")
    )
    visits = all_visits(session)
    assert next(v for v in visits if v.name == "库景点0").rain_ok == "no"
    assert next(v for v in visits if v.name == "库景点1").rain_ok == "yes"


def test_en_fields_passthrough_for_bilingual_cards():
    """双语 P1：候选库 _en 字段 → VisitItem 并出（空则 None 前端回退）。"""

    class EnStore(LibraryStore):
        def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
            rows = super().top_pois_in_city(city, limit, exclude_food=exclude_food)
            rows[0]["name_en"] = "Gugong Palace"
            rows[0]["address_en"] = "4 Jingshan Front St"
            rows[0]["intro_en"] = "Imperial palace of Ming and Qing"
            # rows[1] 不给 _en——回退中文路径
            return rows

    items = [
        {"name": "库景点0", "city": "上海", "day": 1, "duration_minutes": 60},
        {"name": "库景点1", "city": "上海", "day": 1, "duration_minutes": 60},
    ]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]),
        amap_client=StubAmap(AMAP_POIS),
        poi_details=EnStore(),
        auto_restaurants=False,
    )
    session = run(
        agent.start(device_id="d1", cities=["上海"], days=1, preferences="随便")
    )
    visits = all_visits(session)
    v0 = next(v for v in visits if v.name == "库景点0")
    assert v0.name_en == "Gugong Palace"
    assert v0.address_en == "4 Jingshan Front St"
    assert v0.intro_en == "Imperial palace of Ming and Qing"
    v1 = next(v for v in visits if v.name == "库景点1")
    assert v1.name_en is None and v1.address_en is None


def test_lang_param_persists_on_session():
    """双语 P2：lang=en 落会话；非法 lang 忽略回中文默认。"""
    items = [{"name": "库景点0", "city": "上海", "day": 1, "duration_minutes": 60}]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]),
        amap_client=StubAmap(AMAP_POIS),
        poi_details=LibraryStore(),
        auto_restaurants=False,
    )
    s = run(
        agent.start(
            device_id="d1",
            cities=["上海"],
            days=1,
            preferences="随便",
            lang="en",
        )
    )
    assert s.lang == "en"
    s2 = run(agent.start(device_id="d2", cities=["上海"], days=1, lang="fr"))
    assert s2.lang is None  # 非法值忽略


class RecordingLLM(ScriptedLLM):
    """捕获 system 消息，验证 lang 指令真正到达 LLM（双语 P2 T4）。"""

    def __init__(self, replies):
        super().__init__(replies)
        self.system_msgs: list[str] = []

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        for m in messages:
            if getattr(m, "role", "") == "system":
                self.system_msgs.append(m.content)
        return await super().chat(
            messages, temperature=temperature, max_tokens=max_tokens
        )


def test_lang_en_directive_reaches_llm_system_prompt():
    """lang=en 时 EN 指令进系统提示词；lang 缺省则完全不出现。"""
    items = [{"name": "库景点0", "city": "上海", "day": 1, "duration_minutes": 60}]
    reply = v0_reply(items)

    rec = RecordingLLM([reply])
    agent = PlanningAgent(
        rec,
        amap_client=StubAmap(AMAP_POIS),
        poi_details=LibraryStore(),
        auto_restaurants=False,
    )
    run(
        agent.start(
            device_id="d1",
            cities=["上海"],
            days=1,
            preferences="随便",
            lang="en",
        )
    )
    assert any("LANGUAGE:" in m for m in rec.system_msgs), "EN 指令未达 LLM"

    rec2 = RecordingLLM([reply])
    agent2 = PlanningAgent(
        rec2,
        amap_client=StubAmap(AMAP_POIS),
        poi_details=LibraryStore(),
        auto_restaurants=False,
    )
    run(agent2.start(device_id="d2", cities=["上海"], days=1, preferences="随便"))
    assert not any("LANGUAGE:" in m for m in rec2.system_msgs), "zh 路径不应注入指令"
