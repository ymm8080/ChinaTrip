"""PoiDetailStore + daily refresh job chain tests (v2.4.4, no network)."""

import asyncio

from app.jobs.refresh_pois import refresh_pois
from app.services.poi_details import PoiDetailStore


def test_store_memory_roundtrip():
    store = PoiDetailStore()  # no session factory → memory mode
    assert store.get("B1") is None
    assert store.upsert(
        "B1",
        city="重庆",
        name="洪崖洞",
        opening_hours="全年全天开放",
        hours_source="ctrip",
    )
    got = store.get("B1")
    assert got["opening_hours"] == "全年全天开放"
    assert got["hours_source"] == "ctrip"
    assert got["city"] == "重庆"


def test_store_get_by_name_after_append():
    store = PoiDetailStore()
    store.upsert(
        "ctrip:重庆:洪崖洞",
        city="重庆",
        name="洪崖洞",
        source="ctrip",
        opening_hours="全年全天开放",
        hours_source="ctrip",
    )
    got = store.get_by_name("重庆市", "洪崖洞")
    assert got is not None and got["poi_id"] == "ctrip:重庆:洪崖洞"
    assert got["opening_hours"] == "全年全天开放"
    assert store.get_by_name("重庆", "不存在") is None


def test_store_db_failure_keeps_memory():
    def bad_factory():
        raise RuntimeError("db down")

    store = PoiDetailStore(session_factory=bad_factory)
    assert store.ping() is False
    assert store.upsert(
        "B2", city="c", name="n", opening_hours="h", hours_source="ctrip"
    )
    assert store.get("B2")["opening_hours"] == "h"


class FakeCtrip:
    def __init__(self):
        self.calls = []

    async def hours_for(self, city, name):
        self.calls.append((city, name))
        return "全年全天开放"


class FakeAmap:
    def __init__(self, detail_hours="09:00-17:00", search_hours="09:00-21:00"):
        self.detail_calls = []
        self.search_calls = []
        self._detail_hours = detail_hours
        self._search_hours = search_hours

    async def place_hours(self, poi_id):
        self.detail_calls.append(poi_id)
        return {
            "opening_hours": self._detail_hours,
            "rating": None,
            "address": "某路1号",
        }

    async def search_hours(self, keyword, city=None):
        self.search_calls.append((keyword, city))
        return {
            "opening_hours": self._search_hours,
            "rating": None,
            "matched": keyword,
            "address": None,
        }


def test_refresh_chain_ctrip_first_and_wins():
    store = PoiDetailStore()
    store.upsert("B1", city="重庆", name="景点A")
    store.upsert("B2", city="重庆", name="景点B")
    ctrip = FakeCtrip()
    amap = FakeAmap()
    stats = asyncio.run(refresh_pois(store, ctrip, amap, limit=10))
    assert stats["total"] == 2 and stats["ctrip"] == 2
    # 携程先：amap 从未被问询
    assert ctrip.calls == [("重庆", "景点A"), ("重庆", "景点B")]
    assert amap.detail_calls == [] and amap.search_calls == []
    got = store.get("B1")
    assert got["opening_hours"] == "全年全天开放"
    assert got["hours_source"] == "ctrip"


def test_refresh_falls_to_v5_detail_then_search_not_needed():
    store = PoiDetailStore()
    store.upsert("B9", city="重庆", name="景点C")
    amap = FakeAmap()
    stats = asyncio.run(refresh_pois(store, _NullCtrip(), amap, limit=10))
    assert stats["amap_v5_detail"] == 1 and stats["amap_v5_search"] == 0
    assert amap.search_calls == []  # detail 命中 → 关键词搜索不触发
    got = store.get("B9")
    assert got["opening_hours"] == "09:00-17:00"
    assert got["address"] == "某路1号"


def test_refresh_search_is_final_amap_fallback():
    store = PoiDetailStore()
    store.upsert("B7", city="重庆", name="景点D")
    amap = FakeAmap(detail_hours=None)  # detail 无数据
    stats = asyncio.run(refresh_pois(store, _NullCtrip(), amap, limit=10))
    assert stats["amap_v5_search"] == 1
    assert store.get("B7")["opening_hours"] == "09:00-21:00"
    assert store.get("B7")["hours_source"] == "amap_v5_search"


def test_refresh_miss_keeps_stale_for_next_run():
    store = PoiDetailStore()
    store.upsert("B8", city="重庆", name="景点E")
    stats = asyncio.run(refresh_pois(store, _NullCtrip(), None, limit=10))
    assert stats["miss"] == 1 and stats["total"] == 1


class _NullCtrip:
    async def hours_for(self, city, name):
        return None


def test_db_down_latch_skips_subsequent_attempts(monkeypatch):
    """2026-10-20 latency fix: one failed connect latches DB attempts
    off for the cooldown — a down docker db costs ONE connect_timeout
    stall, not one per call; memory keeps serving and ping() clears
    the latch."""
    import app.services.poi_details as mod

    class DownFactory:
        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            raise RuntimeError("connection refused")

    down = DownFactory()
    store = mod.PoiDetailStore(session_factory=down)
    # tiny cooldown, patched BEFORE the first failure (the deadline
    # is computed at failure time from the then-current constant)
    monkeypatch.setattr(mod, "_DB_DOWN_COOLDOWN_SECONDS", 0.05)
    assert store.get("B001") is None  # stall once, then memory
    store.upsert("B001", name="豫园", opening_hours="09:00-17:00")
    assert store.get("B001")["opening_hours"] == "09:00-17:00"
    assert down.calls == 1, "latch must suppress the second DB attempt"

    # cooldown expiry: attempts resume (and fail → memory still wins)
    import time as _time

    _time.sleep(0.06)
    assert store.get("B001")["opening_hours"] == "09:00-17:00"
    assert down.calls == 2
