"""app.jobs.osm_diff 单测（不依赖 pyosmium：只测 should_import / handle_change）。

parse_osc 内部才 import osmium，本机未装也能全量跑这里。
seed/mark 用可注入替身，记录调用参数断言。
"""

from __future__ import annotations

from app.jobs import osm_diff
from app.models import Poi
from app.services.coords import haversine_m

FACTORY = object()  # 假 session_factory，仅透传给 seed/mark 替身记录


class SeedStub:
    """seed_upsert 替身：记录 (session_factory, model, **kwargs)。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, session_factory, model, **kwargs) -> str:
        self.calls.append(
            {"session_factory": session_factory, "model": model, **kwargs}
        )
        return "created"


class MarkStub:
    """mark_status 替身：记录位置参数，marked 控制返回值。"""

    def __init__(self, marked: bool = True) -> None:
        self.calls: list[dict] = []
        self.marked = marked

    def __call__(self, session_factory, model, source, source_poi_id, status) -> bool:
        self.calls.append(
            {
                "session_factory": session_factory,
                "model": model,
                "source": source,
                "source_poi_id": source_poi_id,
                "status": status,
            }
        )
        return self.marked


def _wkt_coords(geom) -> tuple[float, float]:
    """WKTElement -> (lon, lat)。"""
    text = str(geom)
    inner = text[text.index("(") + 1 : text.index(")")]
    lon, lat = inner.split()
    return float(lon), float(lat)


# ---------- should_import：标签过滤 ----------


def test_should_import_attraction_with_chinese_name():
    assert osm_diff.should_import({"name": "洪崖洞", "tourism": "attraction"}) == (
        "attraction"
    )


def test_should_import_restaurant_category():
    assert osm_diff.should_import({"name": "老火锅", "amenity": "restaurant"}) == (
        "restaurant"
    )


def test_should_import_park_and_museum():
    assert osm_diff.should_import({"name": "鹅岭公园", "leisure": "park"}) == "park"
    assert osm_diff.should_import({"name": "三峡博物馆", "tourism": "museum"}) == (
        "museum"
    )


def test_should_import_none_without_chinese_name():
    assert (
        osm_diff.should_import({"name": "Hongya Cave", "tourism": "attraction"}) is None
    )
    assert osm_diff.should_import({"tourism": "attraction"}) is None


def test_should_import_none_for_unmatched_tags():
    assert osm_diff.should_import({"name": "解放碑站", "highway": "bus_stop"}) is None


# ---------- handle_change：分派 ----------


def test_delete_marks_inactive():
    seed, mark = SeedStub(), MarkStub()
    stats = osm_diff._new_stats()
    result = osm_diff.handle_change(
        "delete",
        "node",
        123,
        {},
        None,
        session_factory=FACTORY,
        stats=stats,
        seed=seed,
        mark=mark,
    )
    assert result == "deleted"
    assert len(mark.calls) == 1
    call = mark.calls[0]
    assert call["model"] is Poi
    assert call["source"] == "osm"
    assert call["source_poi_id"] == "n123"
    assert call["status"] == "inactive"
    assert seed.calls == []
    assert stats["deleted"] == 1
    assert stats["inactive_marked"] == 1


def test_delete_prefix_by_type():
    for osm_type, prefix in (("node", "n"), ("way", "w"), ("relation", "r")):
        mark = MarkStub()
        osm_diff.handle_change(
            "delete",
            osm_type,
            9,
            {},
            None,
            session_factory=FACTORY,
            seed=SeedStub(),
            mark=mark,
        )
        assert mark.calls[0]["source_poi_id"] == f"{prefix}9"


def test_delete_mark_miss_counts_deleted_only():
    seed, mark = SeedStub(), MarkStub(marked=False)
    stats = osm_diff._new_stats()
    osm_diff.handle_change(
        "delete",
        "node",
        1,
        {},
        None,
        session_factory=FACTORY,
        stats=stats,
        seed=seed,
        mark=mark,
    )
    assert stats["deleted"] == 1
    assert stats["inactive_marked"] == 0


def test_create_without_coords_skipped():
    seed = SeedStub()
    stats = osm_diff._new_stats()
    tags = {"name": "洪崖洞", "tourism": "attraction"}
    result = osm_diff.handle_change(
        "modify",
        "way",
        456,
        tags,
        None,
        session_factory=FACTORY,
        stats=stats,
        seed=seed,
    )
    assert result == "skipped_no_coords"
    assert seed.calls == []
    assert stats["skipped_no_coords"] == 1


def test_create_addr_city_strips_suffix():
    seed = SeedStub()
    stats = osm_diff._new_stats()
    tags = {"name": "洪崖洞", "tourism": "attraction", "addr:city": "北京市"}
    result = osm_diff.handle_change(
        "modify",
        "node",
        789,
        tags,
        (116.397, 39.909),
        session_factory=FACTORY,
        stats=stats,
        seed=seed,
    )
    assert result == "created"
    assert seed.calls[0]["city"] == "北京"
    assert stats["no_city"] == 0


def test_create_without_addr_city_counts_no_city():
    seed = SeedStub()
    stats = osm_diff._new_stats()
    tags = {"name": "洪崖洞", "tourism": "attraction"}
    osm_diff.handle_change(
        "modify",
        "node",
        1,
        tags,
        (106.578, 29.561),
        session_factory=FACTORY,
        stats=stats,
        seed=seed,
    )
    assert seed.calls[0]["city"] == ""
    assert stats["no_city"] == 1


def test_create_converts_wgs84_to_gcj02():
    seed = SeedStub()
    tags = {"name": "洪崖洞", "tourism": "attraction", "addr:city": "重庆市"}
    wgs = (106.5783, 29.5608)
    result = osm_diff.handle_change(
        "modify",
        "node",
        1,
        tags,
        wgs,
        session_factory=FACTORY,
        seed=seed,
    )
    assert result == "created"
    call = seed.calls[0]
    assert call["source"] == "osm"
    assert call["source_poi_id"] == "n1"
    assert call["category"] == "attraction"
    assert call["name_zh"] == "洪崖洞"
    assert call["name_en"] is None
    assert call["origin"] == "osm"
    # 铁律：location 存 GCJ-02，wgs84_location 存原值，成对写入
    assert _wkt_coords(call["wgs84_lonlat"]) == wgs
    gcj = _wkt_coords(call["lonlat"])
    offset_m = haversine_m(*wgs, *gcj)
    assert 100 < offset_m < 1000  # 典型偏移 400-700m；未转换为 0


def test_create_restaurant_skipped_this_phase():
    seed = SeedStub()
    stats = osm_diff._new_stats()
    tags = {"name": "老火锅", "amenity": "restaurant"}
    result = osm_diff.handle_change(
        "modify",
        "node",
        5,
        tags,
        (106.55, 29.56),
        session_factory=FACTORY,
        stats=stats,
        seed=seed,
    )
    assert result == "skipped_restaurant"
    assert seed.calls == []
    assert stats["skipped_restaurant"] == 1


def test_unmatched_object_counts_no_name():
    seed = SeedStub()
    stats = osm_diff._new_stats()
    result = osm_diff.handle_change(
        "modify",
        "node",
        7,
        {"highway": "bus_stop", "name": "解放碑站"},
        (106.55, 29.56),
        session_factory=FACTORY,
        stats=stats,
        seed=seed,
    )
    assert result == "skipped_no_name"
    assert seed.calls == []
    assert stats["skipped_no_name"] == 1


def test_name_en_passed_through():
    seed = SeedStub()
    tags = {
        "name": "洪崖洞",
        "name:en": "Hongya Cave",
        "tourism": "attraction",
    }
    osm_diff.handle_change(
        "modify",
        "node",
        2,
        tags,
        (106.5783, 29.5608),
        session_factory=FACTORY,
        seed=seed,
    )
    assert seed.calls[0]["name_en"] == "Hongya Cave"
