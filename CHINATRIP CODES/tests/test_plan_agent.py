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
    },
    {
        "name": "豫园",
        "city": "上海",
        "category": "风景名胜",
        "source_poi_id": "B000A7U3C8",
        "location": {"lon": 121.49, "lat": 31.23},
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
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS)])
    amap = StubAmap(AMAP_POIS)
    agent = PlanningAgent(llm, amap_client=amap)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州"],
            days=2,
            preferences="博物馆",
        )
    )
    assert session.state == "ready"
    plan = session.plan
    assert len(plan.days) == 2
    visits = all_visits(session)
    transfers = all_transfers(session)
    assert len(visits) == 3
    assert len(transfers) == 1
    assert transfers[0].mode == "train"
    assert transfers[0].train_no == "G7351"
    assert (transfers[0].from_city, transfers[0].to_city) == ("上海", "杭州")
    assert [city for _, city in amap.calls] == ["上海", "杭州"]
    # solver placed every visit (§6.9 pipeline backend)
    assert all(v.start_time is not None for v in visits)
    # amap enrichment: matched candidate name carries the source poi_id
    by_name = {v.name: v for v in visits}
    assert by_name["外滩"].poi_id == "B000A7BD6C"
    assert "假设中等节奏、不早起" in session.assumptions


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
            cities=["三亚", "哈尔滨"],
            days=4,
            preferences="海岛与冰雪",
        )
    )
    transfers = all_transfers(session)
    assert transfers[0].mode == "flight"
    assert transfers[0].duration_minutes == 180
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
            cities=["上海", "苏州"],
            days=2,
            preferences="园林",
        )
    )
    transfers = all_transfers(session)
    assert transfers[0].mode == "car"
    assert 60 <= transfers[0].duration_minutes <= 180
    assert any("驾车" in a for a in session.assumptions)


def test_v0_poi_day_outside_city_window_is_clamped():
    llm = ScriptedLLM(
        [
            v0_reply(
                [
                    {
                        "name": "天涯海角",
                        "city": "三亚",
                        "category": "sight",
                        "day": 3,  # wrong: 三亚 window is day 1 only
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
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["三亚", "哈尔滨"],
            days=4,
            preferences="经典",
        )
    )
    sanya = [v for v in all_visits(session) if v.city == "三亚"]
    assert sanya and all(v.day == 1 for v in sanya)
    assert any("城市日程" in a for a in session.assumptions)


def test_v0_placeholder_selection_respects_city_windows():
    agent = PlanningAgent(
        ExplodingLLM(), amap_client=StubAmap(exc=RuntimeError("amap down"))
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["三亚", "哈尔滨"],
            days=4,
            preferences="无",
        )
    )
    visits = all_visits(session)
    sanya = [v for v in visits if v.city == "三亚"]
    haerbin = [v for v in visits if v.city == "哈尔滨"]
    assert sanya and all(v.day == 1 for v in sanya)
    assert haerbin and all(2 <= v.day <= 4 for v in haerbin)


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
    llm = ScriptedLLM(
        [
            v0_reply(SH_HZ_ITEMS),
            edit_reply(
                "已把豫园挪到第二天", [{"op": "move", "item_id": "v2", "new_day": 2}]
            ),
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
    session, reply, change = run(agent.message(session, "把豫园挪到第二天"))
    assert "豫园" in reply
    assert change is not None
    assert change.affected_items_count == 1
    assert change.change_summary
    moved = next(i for d in session.plan.days for i in d.items if i.item_id == "v2")
    # Day 2 is the 上海→杭州 transfer day (earliest train 07:15 minus the
    # 90min buffer leaves no morning slot): a Shanghai POI is physically
    # impossible there, so reconcile moves it back to day 1 with a note.
    assert moved.day == 1
    assert any("豫园" in a and "移至第1天" in a for a in session.plan.assumptions)
    assert not hard_errors(session)


def test_selfrepair_recovers_from_hard_violation():
    # v0 solves day1 as 外滩 08:00-09:30, 豫园 09:30-10:30; the first diff
    # retimes 外滩 to 09:00 -> rule-1 overlap -> repair round fixes it.
    llm = ScriptedLLM(
        [
            v0_reply(SH_HZ_ITEMS),
            edit_reply(
                "好的", [{"op": "retime", "item_id": "v1", "new_start_time": "09:00"}]
            ),
            repair_reply(
                [{"op": "retime", "item_id": "v1", "new_start_time": "08:00"}]
            ),
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
    session, reply, change = run(agent.message(session, "外滩改到九点开始"))
    assert llm.calls == 3  # v0 + edit + one repair round
    item = next(i for d in session.plan.days for i in d.items if i.item_id == "v1")
    assert item.start_time == time(8, 0)
    assert change is not None
    assert not hard_errors(session)


def test_selfrepair_exhausted_delivers_half_product():
    bad_edit = edit_reply(
        "试试", [{"op": "retime", "item_id": "v1", "new_start_time": "09:00"}]
    )
    bad_repairs = [
        repair_reply([{"op": "retime", "item_id": "v1", "new_start_time": "09:00"}])
        for _ in range(MAX_REPAIR_ROUNDS)
    ]
    llm = ScriptedLLM([v0_reply(SH_HZ_ITEMS), bad_edit] + bad_repairs)
    agent = PlanningAgent(llm)
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州"],
            days=2,
            preferences="博物馆",
        )
    )
    session, reply, change = run(agent.message(session, "外滩改到九点开始"))
    assert llm.calls == 2 + MAX_REPAIR_ROUNDS  # v0 + edit + 3 repairs
    assert "半成品" in reply
    assert change is not None  # the applied-but-invalid diffs still reported
    assert hard_errors(session)  # rule-1 overlap shipped, annotated


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
