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
    PlanningAgent,
    clarify_questions,
    current_violations,
)
from app.services.itinerary import RuleSeverity, TransferItem, VisitItem
from app.services.llm.base import ChatResult
from app.services.llm.zhipu import LLMError
from app.services.poi_details import PoiDetailStore


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


def edit_reply(reply: str, diffs, need=None) -> str:
    return json.dumps(
        {"reply": reply, "diffs": diffs, "need_clarification": need or []},
        ensure_ascii=False,
    )


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
    agent = PlanningAgent(llm, amap_client=amap)
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
    agent = PlanningAgent(llm, amap_client=StubAmap(AMAP_POIS))
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
