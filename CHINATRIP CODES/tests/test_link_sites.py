"""Video/note link -> trip-list tests (§6.5 extension): a pasted link that
names >=2 visitable sites pauses the plan conversation for one
mandatory/optional round; a single-site link IS the must-have site (no
round). Only the user-picked mandatory sites land in the trip-center
wishlist (product rule 2026-10-20); optional/unpicked candidates stay
out of the DB. Mandatory sites ride the v0/plan pipeline pinned (iron
rule 19).

All offline: RecordingLLM for GLM, StubReader for the fetch, StubAmap with
no results (placeholder candidates), real CP-SAT on tiny plans.
"""

import asyncio
import json
import os
from datetime import time

import pytest

from app.services.agent.plan import (
    PlanningAgent,
    _parse_resto_answer,
    _parse_site_answer,
    _same_site,
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


def _ready_agent(replies: list[str], reader: StubReader, trip_items, amap=None):
    llm = RecordingLLM(replies)
    agent = PlanningAgent(
        llm,
        amap_client=amap if amap is not None else StubAmap(),
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
    assert set(names) == {"总统府", "夫子庙"}  # picked 必去 only
    assert names["总统府"]["source"] == "paste"
    assert "必去" in names["总统府"]["note"]
    assert "老门东" not in names  # 未点选不入库
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
    assert "总统府" in reply
    names = [i["name"] for i in trip_items.list_groups()["wishlist"]]
    assert names == ["总统府"]  # picked 必去 only; unpicked stay out


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
    wishlist_names = [i["name"] for i in trip_items.list_groups()["wishlist"]]
    assert wishlist_names == ["总统府"]  # picked only


def test_single_site_link_is_auto_must_visit():
    """One site in the link = the must-have site (product rule 2026-10-19):
    no asking round, deterministic wishlist write + plan add."""
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
    session, reply, change = run(agent.message(session, "https://x/1 参考"))
    assert session.state == "ready"
    assert "颐和园" in reply and "必去" in reply
    assert session.must_visits == ["颐和园"]
    names = {i["name"]: i for i in trip_items.list_groups()["wishlist"]}
    assert set(names) == {"颐和园"}
    assert names["颐和园"]["source"] == "paste"
    assert "必去" in names["颐和园"]["note"]
    plan_names = {
        item.name
        for day in session.plan.days
        for item in day.items
        if isinstance(item, VisitItem)
    }
    assert "颐和园" in plan_names


def test_single_site_link_before_details_pins_into_later_v0():
    reader = StubReader(LinkDigest(url="https://x/1", title="t", text="只有颐和园"))
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        [_sites_reply(["颐和园"]), _v0_reply()],
        reader,
        trip_items,
    )
    session = run(
        agent.start(
            device_id="d",
            cities=[],
            days=0,
            preferences="按这个视频规划 https://x/1",
        )
    )
    assert session.state == "clarify"
    assert session.must_visits == ["颐和园"]
    assert [i["name"] for i in trip_items.list_groups()["wishlist"]] == ["颐和园"]

    session, reply, _ = run(agent.message(session, "北京 2 天"))
    assert session.state == "ready"
    pinned = [
        item
        for day in session.plan.days
        for item in day.items
        if isinstance(item, VisitItem) and item.pinned
    ]
    assert [v.name for v in pinned] == ["颐和园"]


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


# --- link restaurants (kind=food) + >5km ask round -----------------------


class GeoStubAmap:
    """Located stub: the per-city 景点 search answers sights around lat
    32.00; any other keyword is a must-visit name lookup answered as a
    food POI at ``food_lat`` (0.10 deg ≈ 11.1km far, 0.02 ≈ 2.2km near)."""

    def __init__(self, food_lat: float = 32.10) -> None:
        self.food_lat = food_lat

    async def search_poi(self, keywords, *, city=None, page=1):
        if keywords == "景点":
            return [
                {
                    "name": "夫子庙",
                    "city": city or "南京",
                    "category": "风景名胜;古迹",
                    "source_poi_id": "B1",
                    "address": "秦淮区",
                    "location": {"lon": 118.78, "lat": 32.00},
                },
                {
                    "name": "中山陵",
                    "city": city or "南京",
                    "category": "风景名胜;陵园区",
                    "source_poi_id": "B2",
                    "address": "玄武区",
                    "location": {"lon": 118.79, "lat": 32.01},
                },
            ]
        return [
            {
                "name": keywords,
                "city": city or "南京",
                "category": "餐饮服务;小吃店",
                "source_poi_id": "F1",
                "address": "某路1号",
                "location": {"lon": 118.78, "lat": self.food_lat},
            }
        ]


def _sites_kind_reply(name: str, kind: str = "food") -> str:
    return json.dumps({"sites": [{"name": name, "kind": kind}]}, ensure_ascii=False)


def _food_digest() -> LinkDigest:
    return LinkDigest(
        url="https://xhslink.com/abc",
        title="南京必吃",
        text="这家李记锅贴绝了，天天排队",
    )


def _food_link_agent(replies, food_lat=32.10):
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        replies,
        StubReader(_food_digest()),
        trip_items,
        amap=GeoStubAmap(food_lat=food_lat),
    )
    return llm, agent, trip_items


def _food_item(session):
    return next(
        v
        for d in session.plan.days
        for v in d.items
        if isinstance(v, VisitItem) and v.name == "李记锅贴"
    )


def test_food_link_far_from_sights_asks_then_skips():
    llm, agent, trip_items = _food_link_agent(
        [_sites_kind_reply("李记锅贴"), _v0_reply()]
    )
    session = run(
        agent.start(
            device_id="d",
            cities=[],
            days=0,
            preferences="按这个吃 https://xhslink.com/abc 规划",
        )
    )
    assert session.state == "clarify"
    assert session.must_visits == ["李记锅贴"]
    assert session.site_kinds["李记锅贴"] == "food"
    notes = {i["name"]: i for i in trip_items.list_groups()["wishlist"]}
    assert set(notes) == {"李记锅贴"}
    assert "餐饮" in notes["李记锅贴"]["note"]

    session, reply, _ = run(agent.message(session, "南京 2 天"))
    assert session.state == "resto_confirm"
    assert [r.name for r in session.pending_restos] == ["李记锅贴"]
    assert session.pending_restos[0].nearest_km > 5
    assert "超过 5 公里" in reply
    assert _food_item(session) is not None  # include-and-ask: it rides the v0

    session, reply, _ = run(agent.message(session, "不安排"))
    assert session.state == "ready"
    assert session.must_visits == []
    names = {
        item.name
        for day in session.plan.days
        for item in day.items
        if isinstance(item, VisitItem)
    }
    assert "李记锅贴" not in names
    assert llm.calls == 2  # extract + v0; the ask round stays deterministic


def test_food_link_near_sights_no_ask_pinned_into_meal_window():
    _, agent, _ = _food_link_agent(
        [_sites_kind_reply("李记锅贴"), _v0_reply()], food_lat=32.02
    )
    session = run(
        agent.start(
            device_id="d",
            cities=[],
            days=0,
            preferences="按这个吃 https://xhslink.com/abc 规划",
        )
    )
    session, reply, _ = run(agent.message(session, "南京 2 天"))
    assert session.state == "ready"
    food = _food_item(session)
    assert food.category == "food"
    assert food.pinned
    assert food.start_time is not None
    assert time(11, 30) <= food.start_time <= time(13, 30)
    assert food.duration_minutes == 60


def test_food_link_edit_round_far_defers_then_adds_on_accept():
    _, agent, _ = _food_link_agent([_v0_reply(), _sites_kind_reply("李记锅贴")])
    session = run(
        agent.start(device_id="d", cities=["南京"], days=2, preferences="博物馆")
    )
    assert session.state == "ready"

    session, reply, _ = run(agent.message(session, "https://xhslink.com/abc 必吃"))
    assert session.state == "resto_confirm"
    names = {
        item.name
        for day in session.plan.days
        for item in day.items
        if isinstance(item, VisitItem)
    }
    assert "李记锅贴" not in names  # deferred, not added yet

    session, reply, _ = run(agent.message(session, "要安排"))
    assert session.state == "ready"
    food = _food_item(session)
    assert food.pinned
    assert food.start_time is not None
    assert time(11, 30) <= food.start_time <= time(13, 30)


def test_parse_resto_answer_shapes():
    names = ["李记锅贴", "马祥兴"]
    assert _parse_resto_answer("要安排：李记锅贴；不安排：马祥兴", names) == (
        ["李记锅贴"],
        ["马祥兴"],
    )
    assert _parse_resto_answer("都要", names) == (names, [])
    assert _parse_resto_answer("都不安排", names) == ([], names)
    assert _parse_resto_answer("要安排", ["李记锅贴"]) == (["李记锅贴"], [])
    assert _parse_resto_answer("不安排", ["李记锅贴"]) == ([], ["李记锅贴"])
    assert _parse_resto_answer("keep", ["李记锅贴"]) == (["李记锅贴"], [])
    assert _parse_resto_answer("skip", ["李记锅贴"]) == ([], ["李记锅贴"])
    assert _parse_resto_answer("第二天改成下午出发", names) is None


# --- product rule 2026-10-20: wishlist holds only the picked 必去 -------


def test_unparseable_site_answer_keeps_round_open():
    """No recognizable pick: the round stays open (re-ask), nothing is
    recorded — the old fallback wrote the whole candidate list."""
    reader = StubReader(_video_digest())
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        [
            _v0_reply(),
            _sites_reply(["总统府", "夫子庙", "老门东"]),
            "not json",
            "still not json",
        ],
        reader,
        trip_items,
    )
    session = run(
        agent.start(device_id="d", cities=["南京"], days=2, preferences="博物馆")
    )
    url = "https://www.douyin.com/video/7389001"
    session, _, _ = run(agent.message(session, url))
    session, reply, _ = run(agent.message(session, "随便走走"))
    assert session.state == "site_confirm"  # round open, pick not lost
    assert session.pending_sites == ["总统府", "夫子庙", "老门东"]
    assert trip_items.list_groups()["wishlist"] == []
    assert "必去" in reply


def test_drop_answer_ends_round_with_empty_wishlist():
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
    url = "https://www.douyin.com/video/7389001"
    session, _, _ = run(agent.message(session, url))
    session, reply, _ = run(agent.message(session, "都不要了"))
    assert session.state == "ready"
    assert trip_items.list_groups()["wishlist"] == []
    assert "心愿单没有新增" in reply


def test_confirm_sites_records_only_picked():
    """confirm_sites (H5 chip path): picked 必去 ride straight to the
    wishlist write; unpicked candidates are never recorded."""
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
    url = "https://www.douyin.com/video/7389001"
    session, _, _ = run(agent.message(session, url))
    session, reply, _ = run(agent.confirm_sites(session, ["总统府"]))
    assert session.state == "ready"
    assert session.must_visits == ["总统府"]
    names = [i["name"] for i in trip_items.list_groups()["wishlist"]]
    assert names == ["总统府"]
    assert "未点选的 2 个地点没有写入心愿单" in reply
    assert llm.calls == 2  # v0 + extraction; no text round-trip burned


# --- video city understanding (重庆 wishlist regression, 2026-10-20) ------
# A video titled 重庆 must classify its sites as 重庆 even in a multi-city
# session — never from session.cities, never scattered round-robin.


class CityAmap(StubAmap):
    """One amap-style POI per keyword; records (keywords, city) calls."""

    def __init__(self, city_by_name=None):
        self.city_by_name = city_by_name or {}
        self.calls: list[tuple[str, str | None]] = []

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append((keywords, city))
        poi_city = self.city_by_name.get(keywords)
        if poi_city is None:
            return []
        return [
            {
                "source": "amap",
                "source_poi_id": f"B-{keywords}",
                "name": keywords,
                "city": poi_city,
                "category": "风景名胜;风景名胜",
                "address": None,
                "location": {"lon": 106.57, "lat": 29.55},
                "opening_hours": None,
                "rating": None,
            }
        ]


def _cq_video_digest() -> LinkDigest:
    return LinkDigest(
        url="https://www.douyin.com/video/7389002",
        title="重庆3天2夜攻略！十八梯、长江索道、大足石刻全打卡",
        text="这趟重庆玩了十八梯和长江索道，还包车去了大足石刻",
    )


def _cq_v0_reply() -> str:
    return json.dumps(
        {
            "items": [
                {
                    "name": "洪崖洞",
                    "city": "重庆",
                    "category": "sight",
                    "day": 1,
                    "duration_minutes": 90,
                },
                {
                    "name": "宽窄巷子",
                    "city": "成都",
                    "category": "sight",
                    "day": 2,
                    "duration_minutes": 90,
                },
                {
                    "name": "兵马俑",
                    "city": "西安",
                    "category": "sight",
                    "day": 3,
                    "duration_minutes": 90,
                },
            ],
            "assumptions": [],
        },
        ensure_ascii=False,
    )


def _multi_city_session(agent):
    return run(
        agent.start(
            device_id="d", cities=["重庆", "成都", "西安"], days=6, preferences="博物馆"
        )
    )


def _plan_visit(session, name):
    for day in session.plan.days:
        for item in day.items:
            if isinstance(item, VisitItem) and item.name == name:
                return item, day
    return None, None


def test_video_city_wins_over_multi_city_session():
    reader = StubReader(_cq_video_digest())
    trip_items = TripItemService()
    amap = CityAmap()  # no POI hits: the video-derived city must stand alone
    llm, agent = _ready_agent(
        [
            _cq_v0_reply(),
            json.dumps(
                {
                    "sites": [
                        {"name": "十八梯", "kind": "sight", "city": "重庆"},
                        {"name": "长江索道", "kind": "sight", "city": "重庆"},
                        {"name": "大足石刻", "kind": "sight", "city": "重庆"},
                    ]
                },
                ensure_ascii=False,
            ),
        ],
        reader,
        trip_items,
        amap=amap,
    )
    session = _multi_city_session(agent)
    session, _, _ = run(
        agent.message(session, "看这个 https://www.douyin.com/video/7389002")
    )
    assert session.state == "site_confirm"
    session, _, _ = run(agent.message(session, "必去：十八梯、长江索道、大足石刻"))
    wishlist = {i["name"]: i for i in trip_items.list_groups()["wishlist"]}
    assert {n: wishlist[n]["city"] for n in wishlist} == {
        "十八梯": "重庆",
        "长江索道": "重庆",
        "大足石刻": "重庆",
    }
    for name in ("十八梯", "长江索道", "大足石刻"):
        item, day = _plan_visit(session, name)
        assert item is not None, name
        assert item.city == "重庆"
        assert day.base_city == "重庆"  # not scattered onto 成都/西安 days
    must_lookups = [c for c in amap.calls if c[0] in ("十八梯", "长江索道", "大足石刻")]
    # 每个确认景点都按确认城市解析；条目缺坐标回填（backfill 2026-10-28）
    # 会复用同款专名查询，故不断言次数与顺序。
    for site in ("十八梯", "长江索道", "大足石刻"):
        assert (site, "重庆") in must_lookups, site


def test_title_city_fallback_when_llm_omits_city():
    reader = StubReader(_cq_video_digest())
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        [_cq_v0_reply(), json.dumps({"sites": ["十八梯", "长江索道"]})],
        reader,
        trip_items,
    )
    session = _multi_city_session(agent)
    session, _, _ = run(
        agent.message(session, "看这个 https://www.douyin.com/video/7389002")
    )
    session, _, _ = run(agent.message(session, "必去：十八梯、长江索道"))
    wishlist = {i["name"]: i for i in trip_items.list_groups()["wishlist"]}
    assert wishlist["十八梯"]["city"] == "重庆"
    assert wishlist["长江索道"]["city"] == "重庆"
    item, day = _plan_visit(session, "十八梯")
    assert item is not None and item.city == "重庆"
    assert day.base_city == "重庆"


def test_amap_city_overrides_wrong_extracted_city():
    reader = StubReader(_cq_video_digest())
    trip_items = TripItemService()
    # LLM misread the video as 西安; amap knows the POI is 重庆市.
    amap = CityAmap({"十八梯": "重庆市"})
    llm, agent = _ready_agent(
        [
            _cq_v0_reply(),
            json.dumps(
                {"sites": [{"name": "十八梯", "kind": "sight", "city": "西安"}]},
                ensure_ascii=False,
            ),
        ],
        reader,
        trip_items,
        amap=amap,
    )
    session = _multi_city_session(agent)
    # Single-site link: auto-must, no confirm round — one message does it all.
    session, _, _ = run(
        agent.message(session, "看这个 https://www.douyin.com/video/7389002")
    )
    assert ("十八梯", "西安") in amap.calls  # lookup scoped to the guess…
    item, day = _plan_visit(session, "十八梯")
    assert item is not None and item.city == "重庆"  # …amap truth wins
    assert day.base_city == "重庆"
    wishlist = {i["name"]: i for i in trip_items.list_groups()["wishlist"]}
    assert wishlist["十八梯"]["city"] == "重庆"


# --- variant-name dedupe (plan already holds the site) ---------------------


def test_same_site_variants():
    assert _same_site("大足石刻", "大足石刻")
    assert _same_site("大足石刻", "重庆大足石刻景区")
    assert _same_site("大足石刻", "大足石刻（宝顶山）")
    assert not _same_site("大足石刻", "洪崖洞")
    assert not _same_site("", "大足石刻")


def test_planned_site_repicked_from_video_not_duplicated():
    """Plan already holds 大足石刻; the video pick names a variant
    (大足石刻景区): no second plan row, no wishlist row, and the existing
    entry is pinned so the 必去 intent still lands."""
    reader = StubReader(LinkDigest(url="https://x/2", title="t", text="只有大足石刻"))
    trip_items = TripItemService()
    llm, agent = _ready_agent(
        [
            json.dumps(
                {
                    "items": [
                        {
                            "name": "大足石刻",
                            "city": "重庆",
                            "category": "sight",
                            "day": 1,
                        },
                    ],
                    "assumptions": [],
                },
                ensure_ascii=False,
            ),
            _sites_reply(["大足石刻景区"]),
        ],
        reader,
        trip_items,
    )
    session = run(
        agent.start(device_id="d", cities=["重庆"], days=2, preferences="石刻")
    )
    session, reply, _ = run(agent.message(session, "https://x/2 参考"))
    assert session.state == "ready"
    assert "未重复" in reply
    visits = [
        item
        for day in session.plan.days
        for item in day.items
        if isinstance(item, VisitItem) and _same_site(item.name, "大足石刻")
    ]
    assert len(visits) == 1
    assert visits[0].pinned
    # 产品规则 2026-10-20：点选必去照写心愿单（仅计划层去重）
    wishlist = [i["name"] for i in trip_items.list_groups()["wishlist"]]
    assert wishlist == ["大足石刻景区"]


@pytest.fixture(autouse=True)
def _llm_select_mode():
    """本文件守护 LLM 选点（备用模式）语义；算法主路径见 test_algo_v0.py。"""
    os.environ["PLAN_SELECT_MODE"] = "llm"
    yield
    os.environ.pop("PLAN_SELECT_MODE", None)
