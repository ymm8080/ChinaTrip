"""Tests for the restaurant recommendation tool (§6.2 v1.7, iron rule 20)."""

import asyncio
from datetime import time

from app.services.itinerary.models import DayPlan, GeoPoint, VisitItem
from app.services.restaurants import (
    NO_LOCATION_DETOUR_SCORE,
    RestaurantCandidate,
    build_food_item,
    meal_window,
    rank_by_detour,
    recommend_restaurants,
    search_restaurants,
)

# 1 degree of latitude ~ 111.19 km, so lat 0.05 ~ 5.56 km from the origin.
ORIGIN = GeoPoint(lon=0.0, lat=0.0)


class StubAmap:
    """Minimal AmapSearchService stub: canned pois or a raised error."""

    def __init__(self, pois=None, error=None):
        self._pois = pois or []
        self._error = error
        self.calls = []

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append((keywords, city))
        if self._error is not None:
            raise self._error
        return self._pois


def make_poi(name, lon=0.0, lat=0.0, rating=None, poi_id=None, no_location=False):
    """amap-client-shaped dict; no_location POIs carry no coordinates."""
    return {
        "source": "amap",
        "source_poi_id": poi_id or f"poi-{name}",
        "name": name,
        "city": "杭州",
        "category": "餐饮服务;中餐厅",
        "address": f"{name}地址1号",
        "opening_hours": "周一至周日 10:00-22:00",
        "location": None if no_location else {"lon": lon, "lat": lat},
        **({} if rating is None else {"rating": rating}),
    }


def day_plan(day=1, base_city="杭州", items=None):
    return DayPlan(day=day, base_city=base_city, items=items or [])


def visit(item_id, start=None, end=None, duration=None, location=None):
    return VisitItem(
        item_id=item_id,
        name=f"景点{item_id}",
        city="杭州",
        day=1,
        start_time=start,
        end_time=end,
        duration_minutes=duration,
        location=location,
    )


# --- meal_window -----------------------------------------------------------


def test_meal_window_empty_day_returns_constants():
    assert meal_window(day_plan(), "lunch") == (time(11, 30), time(13, 30))
    assert meal_window(day_plan(), "dinner") == (time(17, 30), time(19, 30))


def test_meal_window_untimed_items_do_not_block():
    plan = day_plan(items=[visit("v1")])  # no times at all
    assert meal_window(plan, "lunch") == (time(11, 30), time(13, 30))
    # start_time alone (no end, no duration) defines no interval either
    plan2 = day_plan(items=[visit("v2", start=time(12, 0))])
    assert meal_window(plan2, "lunch") == (time(11, 30), time(13, 30))


def test_meal_window_item_inside_window_compresses_gap():
    plan = day_plan(items=[visit("v1", start=time(11, 30), end=time(12, 30))])
    assert meal_window(plan, "lunch") == (time(12, 30), time(13, 30))
    # right-hand compression: item overhanging the window end gets clipped
    plan2 = day_plan(items=[visit("v2", start=time(12, 30), end=time(14, 0))])
    assert meal_window(plan2, "lunch") == (time(11, 30), time(12, 30))


def test_meal_window_duration_only_item_blocks():
    plan = day_plan(
        items=[visit("v1", start=time(12, 0), duration=60)]  # end_time absent
    )
    # leftover gaps 11:30-12:00 and 13:00-13:30 are both < 60 min
    assert meal_window(plan, "lunch") is None


def test_meal_window_fully_occupied_returns_none():
    plan = day_plan(
        items=[
            visit("v1", start=time(11, 30), end=time(12, 30)),
            visit("v2", start=time(12, 30), end=time(13, 30)),
        ]
    )
    assert meal_window(plan, "lunch") is None


def test_meal_window_items_outside_window_are_ignored():
    plan = day_plan(
        items=[
            visit("v1", start=time(9, 0), end=time(11, 0)),
            visit("v2", start=time(14, 0), end=time(16, 0)),
        ]
    )
    assert meal_window(plan, "lunch") == (time(11, 30), time(13, 30))


# --- rank_by_detour --------------------------------------------------------


def test_rank_by_detour_nearest_candidate_ranks_first():
    near = RestaurantCandidate(name="近", location=GeoPoint(lon=0.0, lat=0.002))
    far = RestaurantCandidate(name="远", location=GeoPoint(lon=0.0, lat=0.05))
    ranked = rank_by_detour([far, near], route_points=[ORIGIN])
    assert ranked[0].name == "近"
    assert ranked[0].detour_score < 1.0  # ~0.22 km
    assert ranked[1].detour_score > 5.0  # ~5.6 km
    assert ranked[0].detour_score < ranked[1].detour_score


def test_rank_by_detour_no_location_ranks_last():
    near = RestaurantCandidate(name="近", location=GeoPoint(lon=0.0, lat=0.002))
    noloc = RestaurantCandidate(name="无坐标")
    ranked = rank_by_detour([noloc, near], route_points=[ORIGIN])
    assert ranked[-1].name == "无坐标"
    assert ranked[-1].detour_score == NO_LOCATION_DETOUR_SCORE


def test_rank_by_detour_takes_min_over_all_route_points():
    cand = RestaurantCandidate(name="中途", location=GeoPoint(lon=0.0, lat=0.008))
    ranked = rank_by_detour(
        [cand],
        route_points=[ORIGIN, GeoPoint(lon=0.0, lat=0.05)],
    )
    assert ranked[0].detour_score < 1.0  # nearest point wins (~0.89 km)


def test_rank_by_detour_rating_weight_flips_near_tie():
    plain = RestaurantCandidate(name="近无评分", location=GeoPoint(lon=0.0, lat=0.003))
    rated = RestaurantCandidate(
        name="远高评分", location=GeoPoint(lon=0.0, lat=0.004), rating=4.5
    )
    ranked = rank_by_detour([plain, rated], route_points=[ORIGIN])
    # 0.445 km - 4.5*0.1 = -0.005 beats 0.334 despite being farther away
    assert ranked[0].name == "远高评分"
    assert ranked[1].name == "近无评分"


# --- build_food_item -------------------------------------------------------


def test_build_food_item_fills_fields():
    cand = RestaurantCandidate(
        name="楼外楼",
        poi_id="B0FF0123",
        location=GeoPoint(lon=120.15, lat=30.25),
        rating=4.7,
        biz_type="中餐厅",
    )
    item = build_food_item(
        cand, day=3, city="杭州", window=(time(11, 30), time(13, 30)), item_id="f-1"
    )
    assert isinstance(item, VisitItem)
    assert item.item_id == "f-1"
    assert item.name == "楼外楼"
    assert item.poi_id == "B0FF0123"
    assert item.category == "food"
    assert item.city == "杭州"
    assert item.location == GeoPoint(lon=120.15, lat=30.25)
    assert item.day == 3
    assert item.start_time == time(12, 30)  # window midpoint
    assert item.end_time == time(13, 30)
    assert item.duration_minutes == 60
    assert item.pinned is False


def test_build_food_item_uses_compressed_window_midpoint():
    cand = RestaurantCandidate(name="知味观")
    item = build_food_item(
        cand, day=1, city="杭州", window=(time(12, 30), time(13, 30)), item_id="f-2"
    )
    assert item.start_time == time(13, 0)
    assert item.end_time == time(14, 0)


# --- search_restaurants ----------------------------------------------------


def test_search_restaurants_maps_pois_and_tolerates_missing_rating():
    stub = StubAmap(
        pois=[
            make_poi("近餐厅", lat=0.002, rating=4.5),
            make_poi("无评分餐厅", lat=0.05),  # rating key absent
            make_poi("无坐标餐厅", no_location=True),
            make_poi("字符串评分", lat=0.003, rating="4.6"),
        ]
    )
    out = asyncio.run(search_restaurants(stub, "杭州", anchor=ORIGIN))
    assert stub.calls == [("餐厅", "杭州")]
    assert [c.name for c in out] == ["近餐厅", "无评分餐厅", "无坐标餐厅", "字符串评分"]
    assert out[0].poi_id == "poi-近餐厅"
    assert out[0].address == "近餐厅地址1号"
    assert out[0].opening_hours == "周一至周日 10:00-22:00"
    assert out[0].biz_type == "餐饮服务;中餐厅"
    assert out[0].rating == 4.5
    assert out[1].rating is None
    assert out[2].location is None and out[2].walk_minutes is None
    assert out[3].rating == 4.6  # numeric strings are coerced
    assert out[0].walk_minutes == 3  # ~222 m at 80 m/min


def test_search_restaurants_limit_caps_results():
    stub = StubAmap(pois=[make_poi(f"r{i}") for i in range(5)])
    out = asyncio.run(search_restaurants(stub, "杭州", limit=2))
    assert [c.name for c in out] == ["r0", "r1"]


def test_search_restaurants_degrades_to_empty():
    assert asyncio.run(search_restaurants(None, "杭州")) == []
    broken = StubAmap(error=RuntimeError("amap down"))
    assert asyncio.run(search_restaurants(broken, "杭州")) == []


# --- recommend_restaurants -------------------------------------------------


def test_recommend_restaurants_builds_food_items_inside_window():
    stub = StubAmap(
        pois=[
            make_poi("远处餐厅", lat=0.05),
            make_poi("顺路餐厅", lat=0.002),
            make_poi("无坐标餐厅", no_location=True),
        ]
    )
    plan = day_plan(
        day=2,
        items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)],
    )
    items = asyncio.run(recommend_restaurants(stub, plan, "lunch"))
    assert stub.calls == [("餐厅", "杭州")]
    assert len(items) == 3
    # ranking order: detour puts the on-the-way candidate first
    assert [i.name for i in items] == ["顺路餐厅", "远处餐厅", "无坐标餐厅"]
    for item in items:
        assert isinstance(item, VisitItem)
        assert item.category == "food"
        assert item.day == 2
        assert item.city == "杭州"
        assert item.duration_minutes == 60
        assert item.pinned is False
        assert time(11, 30) <= item.start_time <= time(13, 30)
        assert item.start_time == time(12, 30)  # midpoint of the full window
        assert item.end_time == time(13, 30)
    assert len({i.item_id for i in items}) == 3
    assert items[2].location is None  # location-less candidate stays addable
    assert items[0].address == "顺路餐厅地址1号"  # address rides along to the item
    assert items[0].opening_hours == "周一至周日 10:00-22:00"


def test_recommend_restaurants_city_override_beats_base_city():
    stub = StubAmap(pois=[make_poi("本帮菜")])
    plan = day_plan(day=1, base_city="杭州")
    items = asyncio.run(recommend_restaurants(stub, plan, "dinner", city="上海"))
    assert stub.calls == [("餐厅", "上海")]
    assert items and items[0].city == "上海"


def test_recommend_restaurants_no_free_window_returns_empty():
    stub = StubAmap(pois=[make_poi("随便吃")])
    plan = day_plan(
        items=[
            visit("v1", start=time(11, 30), end=time(12, 30)),
            visit("v2", start=time(12, 30), end=time(13, 30)),
        ]
    )
    assert asyncio.run(recommend_restaurants(stub, plan, "lunch")) == []
    assert stub.calls == []  # iron rule 20: never even search without a gap


def test_recommend_restaurants_amap_failure_returns_empty():
    plan = day_plan()
    broken = StubAmap(error=RuntimeError("amap down"))
    assert asyncio.run(recommend_restaurants(broken, plan, "lunch")) == []
    assert asyncio.run(recommend_restaurants(None, plan, "lunch")) == []


def test_recommend_restaurants_returns_fewer_when_few_hits():
    stub = StubAmap(pois=[make_poi("独一家", lat=0.001)])
    plan = day_plan()
    items = asyncio.run(recommend_restaurants(stub, plan, "lunch"))
    assert len(items) == 1
    assert items[0].name == "独一家"
