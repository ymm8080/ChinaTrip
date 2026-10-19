"""Video/note link -> trip-list tests (§6.5 extension): a pasted link that
names >=2 visitable sites pauses the plan conversation for one
mandatory/optional round; every site lands in the trip-center wishlist and
mandatory sites ride the v0/plan pipeline pinned (iron rule 19).

All offline: RecordingLLM for GLM, StubReader for the fetch, StubAmap with
no results (placeholder candidates), real CP-SAT on tiny plans.
"""

import asyncio
import json

from app.services.agent.plan import (
    PlanningAgent,
    _parse_site_answer,
)
from app.services.itinerary import VisitItem
from app.services.llm.base import ChatResult
from app.services.trip_items import TripItemService
from app.services.web_reader import LinkDigest


def run(coro):
    return asyncio.run(coro)


class RecordingLLM:
    name = "recording"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        self.calls += 1
        return ChatResult(content=self.replies.pop(0), model="recording")


class StubAmap:
    async def search_poi(self, keywords, *, city=None, page=1):
        return []


class StubReader:
    def __init__(self, digest: LinkDigest):
        self.digest = digest
        self.calls: list[str] = []

    async def read(self, url: str) -> LinkDigest:
        self.calls.append(url)
        return self.digest


def _sites_reply(names: list[str]) -> str:
    return json.dumps({"sites": names}, ensure_ascii=False)


def _v0_reply() -> str:
    return json.dumps(
        {
            "items": [
                {"name": "夫子庙", "city": "南京", "category": "sight", "day": 1},
            ],
            "assumptions": [],
        },
        ensure_ascii=False,
    )


def _video_digest() -> LinkDigest:
    return LinkDigest(
        url="https://www.douyin.com/video/7389001",
        title="南京两日游",
        text="这趟南京去了总统府和老门东，夫子庙晚上去更好看",
    )


def _ready_agent(replies: list[str], reader: StubReader, trip_items):
    llm = RecordingLLM(replies)
    agent = PlanningAgent(
        llm,
        amap_client=StubAmap(),
        link_reader=reader,
        trip_items=trip_items,
    )
    return llm, agent


# --- answer parsing ------------------------------------------------------


def test_parse_site_answer_canonical():
    sites = ["总统府", "夫子庙", "老门东"]
    parsed = _parse_site_answer("必去：总统府、夫子庙；可选：老门东", sites)
    assert parsed == (["总统府", "夫子庙"], ["老门东"])


def test_parse_site_answer_all_optional_shortcut():
    sites = ["总统府", "夫子庙"]
    assert _parse_site_answer("都可选", sites) == ([], sites)
    assert _parse_site_answer("全部可选，先记着", sites) == ([], sites)


def test_parse_site_answer_optional_only_header():
    parsed = _parse_site_answer("可选：夫子庙", ["总统府", "夫子庙"])
    assert parsed == ([], ["夫子庙"])


def test_parse_site_answer_unrelated_text_is_none():
    assert _parse_site_answer("第二天改成下午出发", ["总统府"]) is None


# --- agent round trip ----------------------------------------------------


def test_two_site_link_asks_then_lands_in_wishlist():
    reader = StubReader(_video_digest())
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        [_v0_reply(), _sites_reply(["总统府", "夫子庙", "老门东"])],
        reader,
        trip_items,
    )
    session = run(
        agent.start(device_id="d", cities=["南京"], days=2, preferences="博物馆")
    )
    assert session.state == "ready"

    session, reply, _ = run(
        agent.message(session, "看看这个视频 https://www.douyin.com/video/7389001")
    )
    assert session.state == "site_confirm"
    assert session.pending_sites == ["总统府", "夫子庙", "老门东"]
    assert "必去" in reply and "可选" in reply
    assert trip_items.list_groups()["wishlist"] == []  # nothing written yet
    assert llm.calls == 2  # v0 + extraction; no edit turn was burned

    session, reply, change = run(
        agent.message(session, "必去：总统府、夫子庙；可选：老门东")
    )
    assert session.state == "ready"
    assert session.must_visits == ["总统府", "夫子庙"]
    names = {i["name"]: i for i in trip_items.list_groups()["wishlist"]}
    assert set(names) == {"总统府", "夫子庙", "老门东"}
    assert names["总统府"]["source"] == "paste"
    assert "必去" in names["总统府"]["note"]
    assert "可选" in names["老门东"]["note"]
    plan_names = {
        item.name
        for day in session.plan.days
        for item in day.items
        if isinstance(item, VisitItem)
    }
    assert {"总统府", "夫子庙"} <= plan_names  # mandatory ones entered the plan


def test_site_answer_via_llm_fallback():
    reader = StubReader(_video_digest())
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        [
            _v0_reply(),
            _sites_reply(["总统府", "夫子庙", "老门东"]),
            json.dumps(
                {"mandatory": ["总统府"], "optional": ["夫子庙", "老门东"]},
                ensure_ascii=False,
            ),
        ],
        reader,
        trip_items,
    )
    session = run(
        agent.start(device_id="d", cities=["南京"], days=2, preferences="博物馆")
    )
    session, _, _ = run(agent.message(session, "https://www.douyin.com/video/7389001"))
    session, reply, _ = run(agent.message(session, "总统府一定要去，其他随便"))
    assert session.must_visits == ["总统府"]
    assert "必去：总统府" in reply
    assert len(trip_items.list_groups()["wishlist"]) == 3


def test_first_message_link_in_preferences_goes_site_round_then_v0():
    reader = StubReader(_video_digest())
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        [
            _sites_reply(["总统府", "夫子庙", "老门东"]),
            _v0_reply(),
        ],
        reader,
        trip_items,
    )
    session = run(
        agent.start(
            device_id="d",
            cities=[],
            days=0,
            preferences="按这个视频规划 https://www.douyin.com/video/7389001",
        )
    )
    assert session.state == "site_confirm"
    assert session.pending_sites == ["总统府", "夫子庙", "老门东"]
    assert reader.calls == ["https://www.douyin.com/video/7389001"]

    session, reply, _ = run(
        agent.message(session, "南京 2 天；必去：总统府；可选：夫子庙、老门东")
    )
    assert session.state == "ready"
    assert session.cities == ["南京"] and session.days == 2
    assert session.must_visits == ["总统府"]
    pinned = [
        item
        for day in session.plan.days
        for item in day.items
        if isinstance(item, VisitItem) and item.pinned
    ]
    assert [v.name for v in pinned] == ["总统府"]
    assert len(trip_items.list_groups()["wishlist"]) == 3


def test_single_site_link_does_not_ask():
    reader = StubReader(LinkDigest(url="https://x/1", title="t", text="只有颐和园"))
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        [
            _v0_reply(),
            _sites_reply(["颐和园"]),
            json.dumps({"reply": "已参考。", "diffs": []}),
        ],
        reader,
        trip_items,
    )
    session = run(
        agent.start(device_id="d", cities=["南京"], days=2, preferences="博物馆")
    )
    session, reply, _ = run(agent.message(session, "https://x/1 参考"))
    assert session.state == "ready"
    assert reply == "已参考。"
    assert trip_items.list_groups()["wishlist"] == []


def test_site_extraction_failure_degrades_to_normal_edit():
    reader = StubReader(_video_digest())
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        [
            _v0_reply(),
            "not json at all",
            "still not json",
            json.dumps({"reply": "已参考。", "diffs": []}),
        ],
        reader,
        trip_items,
    )
    session = run(
        agent.start(device_id="d", cities=["南京"], days=2, preferences="博物馆")
    )
    session, reply, _ = run(
        agent.message(session, "https://www.douyin.com/video/7389001")
    )
    assert session.state == "ready"
    assert reply == "已参考。"
