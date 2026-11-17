# -*- coding: utf-8 -*-
"""条目 id 唯一性（2026-11-13 「Day6 磁器口 换点 → HTTP 422 no_match」事故）。

根因：agent 的 `_item_seq` 是进程级计数，uvicorn 重启归零后，从行程库载
入的会话仍带着 v1…v30——新加的条目撞上旧号，同一计划两条 item_id=v1。
换点/删除/钉/移动都按 item_id 首命中定位，点第六天（重庆「磁器口转运楼」）
的卡会命中第三天（成都「杜甫草堂博物馆」）那条，再拿「成都」去 POI 库精确
匹配「洪崖洞」→ no_match → H5 看到 422。
"""

import asyncio

from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    PlanSessionStore,
    heal_item_ids,
)
from app.services.itinerary import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.itinerary.item_ids import ensure_unique_item_ids


class _StubLLM:
    async def chat(self, *args, **kwargs):  # pragma: no cover - replace 不烧 LLM
        raise AssertionError("replace_item must not call the LLM")


class _CityAwareStore:
    """candidate_by_name 桩：重庆有「洪崖洞」，成都查不到（真实库口径）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def candidate_by_name(self, city, name):
        self.calls.append((city, name))
        if city == "重庆" and name == "洪崖洞":
            return {
                "source_poi_id": "ct_重庆_9",
                "name": "洪崖洞",
                "city": "重庆",
                "category": "ancient_town",
                "tags": ["intl"],
                "location": {"lon": 106.5791, "lat": 29.5628},
                "suggested_duration_min": 120,
            }
        return None

    def db_degraded(self):
        return False

    def get(self, source_poi_id):
        return None

    def upsert(self, *a, **k):
        return None

    def search_keyword(self, city, tokens, *, limit=5):
        return []


def _session_with_dup_ids() -> PlanSession:
    museum = VisitItem(
        item_id="v1",
        name="成都杜甫草堂博物馆",
        poi_id="m1_c8af766ab1ff",
        category="museum",
        city="成都",
        location=GeoPoint(lon=104.0287, lat=30.6604),
        day=3,
        duration_minutes=135,
    )
    ciqikou = VisitItem(
        item_id="v1",
        name="磁器口转运楼",
        poi_id="ct_重庆_150",
        category="ancient_town",
        city="重庆",
        location=GeoPoint(lon=106.4518, lat=29.5783),
        day=6,
        duration_minutes=180,
    )
    return PlanSession(
        session_id="s-dup",
        device_id="device-1",
        plan=ItineraryPlan(
            itinerary_id="it-dup",
            cities=["成都", "重庆"],
            days=[
                DayPlan(day=3, base_city="成都", items=[museum]),
                DayPlan(day=6, base_city="重庆", items=[ciqikou]),
            ],
        ),
    )


def test_ensure_unique_item_ids_keeps_first_and_renames_later():
    session = _session_with_dup_ids()
    notes = ensure_unique_item_ids(session.plan)
    assert len(notes) == 1
    ids = [i.item_id for d in session.plan.days for i in d.items]
    assert ids[0] == "v1"
    assert ids[1] != "v1" and ids[1].startswith("v")
    # 幂等：再跑一次零改动
    assert ensure_unique_item_ids(session.plan) == []


def test_dup_id_replace_falls_back_to_the_matching_day():
    """同号时按 id 首命中第三天的成都条目——成都查不到洪崖洞，兜底换到
    第六天重庆那条（用户点第六天卡片却带旧 id 的场景）。"""

    session = _session_with_dup_ids()
    store = _CityAwareStore()
    agent = PlanningAgent(_StubLLM(), poi_details=store)
    asyncio.run(agent.replace_item(session, "v1", name="洪崖洞"))

    assert store.calls == [("成都", "洪崖洞"), ("重庆", "洪崖洞")]
    flat = [(d.day, i.name) for d in session.plan.days for i in d.items]
    assert (3, "成都杜甫草堂博物馆") in flat  # 别天那条不动
    assert (6, "洪崖洞") in flat


def test_heal_then_replace_lands_on_day6_card():
    session = _session_with_dup_ids()
    heal_item_ids(session)
    day6_id = session.plan.days[1].items[0].item_id
    assert day6_id != "v1"

    agent = PlanningAgent(_StubLLM(), poi_details=_CityAwareStore())
    asyncio.run(agent.replace_item(session, day6_id, name="洪崖洞"))

    flat = [(d.day, i.name) for d in session.plan.days for i in d.items]
    assert (3, "成都杜甫草堂博物馆") in flat
    assert (6, "洪崖洞") in flat


def test_alloc_item_id_skips_ids_already_in_plan():
    """序号归零重启后新条目必须跳过载入会话占用的 v1…（根因防复发）。"""

    session = _session_with_dup_ids()
    heal_item_ids(session)
    agent = PlanningAgent(_StubLLM(), poi_details=_CityAwareStore())
    agent._item_seq = 0
    fresh = agent.alloc_item_id(session.plan)
    assert fresh not in {i.item_id for d in session.plan.days for i in d.items}
    assert fresh == "v3"  # 计划内已占 v1 / v2


def test_store_get_heals_duplicate_item_ids():
    session = _session_with_dup_ids()
    store = PlanSessionStore()
    store.save(session)
    got = store.get("s-dup", device_id="device-1")
    assert got is not None
    ids = [i.item_id for d in got.plan.days for i in d.items]
    assert len(ids) == len(set(ids))
