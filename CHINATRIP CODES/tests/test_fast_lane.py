"""Tests for the fast lane (design §6.12 ②) — deterministic answers for
high-frequency intents, never the agent loop / main model. Offline stubs.
"""

import asyncio

from app.services.agent.plan import PlanSession
from app.services.fast_lane import FastLane
from app.services.itinerary import DayPlan, ItineraryPlan, VisitItem
from app.services.lang_ctx import set_lang
from app.services.translate import TranslationService


class StubPoiDetails:
    """get_by_name / search_keyword stub — deterministic, no DB."""

    def __init__(
        self,
        rows: dict[str, dict] | None = None,
        keyword_hits: list[dict] | None = None,
    ) -> None:
        self._rows = rows or {}
        self._keyword_hits = keyword_hits or []

    def get_by_name(self, city, name):
        row = self._rows.get(name)
        return dict(row) if row else None

    def search_keyword(self, city, tokens, *, limit=5):
        return list(self._keyword_hits[:limit])


class StubTripItems:
    def __init__(self, wishlist: list[dict] | None = None) -> None:
        self._wishlist = wishlist or []

    def list_groups(self, itinerary_id=None):
        return {"wishlist": list(self._wishlist)}


class StubTranslateAdapter:
    """Returns a fixed translation; counts calls."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    name = "stub"

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        from app.services.llm.base import ChatResult

        self.calls += 1
        return ChatResult(content=self.content, model="stub")


def make_visit(name: str) -> VisitItem:
    return VisitItem(item_id=f"i-{name}", name=name, city="重庆", day=1)


def make_session(visits: list[str] | None = None, cities=("重庆",)) -> PlanSession:
    base_city = cities[0] if cities else "无"
    plan = ItineraryPlan(
        itinerary_id="it-1",
        cities=list(cities),
        days=[
            DayPlan(
                day=1, base_city=base_city, items=[make_visit(n) for n in visits or []]
            )
        ],
    )
    return PlanSession(
        session_id="s1", device_id="d1", cities=list(cities), state="ready", plan=plan
    )


def answer(lane: FastLane, session, text, intent):
    return asyncio.run(lane.answer(session, text, intent))


def make_lane(poi=None, trip=None, translate_adapter=None) -> FastLane:
    return FastLane(
        poi_details=poi or StubPoiDetails(),
        trip_items=trip or StubTripItems(),
        translate=TranslationService(translate_adapter or StubTranslateAdapter("")),
    )


# --- poi_hours ---


def test_poi_hours_answers_from_plan_name_lookup():
    poi = StubPoiDetails(
        rows={"洪崖洞": {"opening_hours": "09:00-23:00", "hours_source": "amap"}}
    )
    lane = make_lane(poi=poi)
    session = make_session(visits=["洪崖洞", "长江索道"])
    result = answer(lane, session, "洪崖洞几点开门", "poi_hours")
    assert result is not None
    assert "09:00-23:00" in result.text
    assert result.data == {"name": "洪崖洞", "opening_hours": "09:00-23:00"}


def test_poi_hours_english_locale():
    set_lang("en")
    try:
        poi = StubPoiDetails(
            rows={"洪崖洞": {"opening_hours": "09:00-23:00", "hours_source": "amap"}}
        )
        lane = make_lane(poi=poi)
        result = answer(
            lane, make_session(visits=["洪崖洞"]), "洪崖洞几点开门", "poi_hours"
        )
        assert result.text.startswith("洪崖洞 opening hours:")
    finally:
        set_lang("zh")


def test_poi_hours_unknown_name_returns_none():
    lane = make_lane(poi=StubPoiDetails())
    assert (
        answer(lane, make_session(visits=["洪崖洞"]), "洪崖洞几点开门", "poi_hours")
        is None
    )


def test_poi_hours_known_name_no_hours_returns_none():
    poi = StubPoiDetails(rows={"洪崖洞": {"opening_hours": None}})
    lane = make_lane(poi=poi)
    assert (
        answer(lane, make_session(visits=["洪崖洞"]), "洪崖洞营业时间", "poi_hours")
        is None
    )


# --- wishlist ---


def test_wishlist_lists_names_from_trip_items():
    trip = StubTripItems(wishlist=[{"name": "洪崖洞"}, {"name": "磁器口"}])
    lane = make_lane(trip=trip)
    result = answer(lane, make_session(), "我的心愿单里有什么", "wishlist")
    assert result is not None
    assert "洪崖洞" in result.text and "磁器口" in result.text


def test_wishlist_empty_returns_none():
    lane = make_lane(trip=StubTripItems())
    assert answer(lane, make_session(), "我的心愿单", "wishlist") is None


# --- translate ---


def test_translate_strips_instruction_and_uses_flash_service():
    adapter = StubTranslateAdapter("How much is this mapo tofu")
    lane = make_lane(translate_adapter=adapter)
    result = answer(
        lane, make_session(), "帮我翻译一下 麻婆豆腐多少钱一份", "translate"
    )
    assert result is not None
    assert result.text == "How much is this mapo tofu"
    assert adapter.calls == 1


def test_translate_en_to_zh_direction():
    adapter = StubTranslateAdapter("麻婆豆腐多少钱一份")
    lane = make_lane(translate_adapter=adapter)
    result = answer(lane, make_session(), "translate Mapo tofu price", "translate")
    assert result is not None
    assert result.data["pair"] == "en-zh"


def test_translate_other_script_language_returns_none():
    # 泰文/日文等 v1 不接——回主车道，不虚构语向。
    lane = make_lane()
    assert answer(lane, make_session(), "翻译 ข้าวมันไก่", "translate") is None


def test_translate_only_instruction_returns_none():
    lane = make_lane()
    assert answer(lane, make_session(), "帮我翻译一下", "translate") is None


# --- restaurant ---


def test_restaurant_deterministic_hits_from_poi_base():
    poi = StubPoiDetails(
        keyword_hits=[
            {"name": "佩姐老火锅", "rating": 4.7, "address": "解放碑"},
            {"name": "佩姐老火锅", "rating": 4.7, "address": "解放碑"},  # 去重
            {"name": "山城小汤圆", "rating": 4.5, "address": "磁器口"},
        ]
    )
    lane = make_lane(poi=poi)
    result = answer(lane, make_session(), "附近有什么好吃的", "restaurant")
    assert result is not None
    assert "佩姐老火锅" in result.text
    assert result.data["names"] == ["佩姐老火锅", "山城小汤圆"]


def test_restaurant_no_city_returns_none():
    lane = make_lane(poi=StubPoiDetails(keyword_hits=[{"name": "x"}]))
    assert (
        answer(lane, make_session(cities=()), "附近有什么好吃的", "restaurant") is None
    )


def test_restaurant_no_hits_returns_none():
    lane = make_lane(poi=StubPoiDetails())
    assert answer(lane, make_session(), "附近有什么好吃的", "restaurant") is None


# --- answer cache + fallback ---


def test_answer_cache_hit_within_ttl():
    poi = StubPoiDetails(rows={"洪崖洞": {"opening_hours": "09:00-23:00"}})
    lane = make_lane(poi=poi)
    session = make_session(visits=["洪崖洞"])
    first = answer(lane, session, "洪崖洞几点开门", "poi_hours")
    assert first.cached is False
    second = answer(lane, session, "洪崖洞几点开门", "poi_hours")
    assert second.cached is True
    assert second.text == first.text


def test_unknown_intent_returns_none():
    lane = make_lane()
    assert answer(lane, make_session(), "随便", "mystery") is None
