"""故宫卡右侧固定亮「景山公园」替代项（2026-11-14 用户拍板）。"""

from app.services.agent.plan import _substitute_dup
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.poi_alternatives import attach_plan_alternatives

BJ = GeoPoint(lon=116.397, lat=39.918)


def _visit(name: str, category: str = "attraction", tier: int | None = 1) -> VisitItem:
    return VisitItem(
        item_id=f"v_{name}",
        name=name,
        city="北京",
        category=category,
        tier=tier,
        duration_minutes=120,
        location=BJ,
        day=1,
    )


def _row(name: str, tier: int = 8, category: str = "attraction") -> dict:
    return {
        "name": name,
        "name_en": None,
        "city": "北京",
        "category": category,
        "rating": 4.6,
        "rating_count": 100,
        "tags": [],
        "suggested_duration_min": 90,
        "location": (116.396, 39.925),
        "_tier": tier,
    }


class Store:
    def __init__(self, pool: list[dict], named: dict[str, dict] | None = None):
        self._pool = pool
        self._named = named or {}

    def alternatives_pool(self, city: str) -> list[dict]:
        return list(self._pool)

    def candidate_by_name(self, city, name):
        return self._named.get(name)


def _plan(*items) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it_test",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
    )


def test_palace_gets_jingshan_chip_even_when_pool_cannot_pick_it():
    """故宫主点：同级池只给得出天坛（5A），景山（公园档）仍要固定亮在右侧。"""
    store = Store(
        [_row("天坛", tier=2, category="temple")],
        named={"景山公园": _row("景山公园", tier=8)},
    )
    plan = _plan(_visit("故宫博物院"))
    out = attach_plan_alternatives(plan, store)
    item = out.days[0].items[0]
    assert item.alternatives, "故宫卡必须有备选区"
    assert item.alternatives[0].name == "景山公园"
    assert item.alternatives[0].category == "attraction"


def test_jingshan_not_duplicated_when_already_in_plan():
    store = Store([], named={"景山公园": _row("景山公园", tier=8)})
    plan = _plan(_visit("故宫博物院"), _visit("景山公园", tier=8))
    out = attach_plan_alternatives(plan, store)
    palace = next(i for i in out.days[0].items if i.name == "故宫博物院")
    names = [a.name for a in (palace.alternatives or [])]
    assert "景山公园" not in names


def test_other_sights_do_not_get_the_palace_standin():
    store = Store([], named={"景山公园": _row("景山公园", tier=8)})
    plan = _plan(_visit("天坛", category="temple", tier=2))
    out = attach_plan_alternatives(plan, store)
    item = out.days[0].items[0]
    assert not item.alternatives


def test_palace_and_jingshan_are_one_experience():
    assert _substitute_dup(
        "故宫博物院", "景山公园", "北京", "北京", "museum", "attraction"
    )
    assert not _substitute_dup(
        "故宫博物院", "四季民福烤鸭店（故宫店）", "北京", "北京", "museum", "food"
    )
    assert not _substitute_dup(
        "故宫博物院", "景山公园", "北京", "上海", "museum", "attraction"
    )
