"""PoiDetailStore + daily refresh job chain tests (v2.4.4, no network)."""

import asyncio

from app.jobs.refresh_pois import refresh_pois
from app.services.amap_client import AmapQuotaExhaustedError
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
    """0009 接口：detail_fields_for 返回全字段 dict。"""

    def __init__(self):
        self.calls = []

    async def detail_fields_for(self, city, name):
        self.calls.append((city, name))
        return {
            "opening_hours": "全年全天开放",
            "suggested_duration_min": 210,
            "rating": 4.7,
            "rating_count": 16000,
            "review_tags": ["亲子同乐"],
            "ticket_price_min": 24,
            "ticket_price_max": None,
        }


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

    async def search_hours(self, keyword, city=None, location=None):
        self.search_calls.append((keyword, city, location))
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
    # 0009 富化字段随链写回（内存态同键）
    assert got.get("suggested_duration_min") == 210
    assert got.get("rating") == 4.7
    assert got.get("rating_count") == 16000
    assert got.get("review_tags") == ["亲子同乐"]
    assert got.get("ticket_price_min") == 24


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
    # location 透传（无坐标行 None；有坐标行 "lon,lat" 供 around 降级）
    assert amap.search_calls == [("景点D", "重庆", None)]


def test_refresh_miss_cools_down_24h_without_writing_hours():
    store = PoiDetailStore()
    store.upsert("B8", city="重庆", name="景点E")
    stats = asyncio.run(refresh_pois(store, _NullCtrip(), None, limit=10))
    assert stats["miss"] == 1 and stats["miss_cooldown"] == 1
    got = store.get("B8")
    assert got.get("opening_hours") is None  # 冷却不写 hours
    assert got.get("hours_source") is None
    assert store.stale_pois() == []  # 盖戳后 24h 内不再进 stale 窗口


def test_stale_pois_returns_amap_location_string():
    store = PoiDetailStore()
    store.upsert("L1", city="重庆", name="有坐标", location=(106.578, 29.5628))
    store.upsert("L2", city="重庆", name="无坐标")
    rows = {t[0]: t for t in store.stale_pois()}
    assert rows["L1"][4] == "106.578,29.5628"
    assert rows["L2"][4] is None


class _PickCtrip:
    """按名称给 hours 的携程 stub：quota 熔断下携程链必须照跑。"""

    def __init__(self, hits):
        self._hits = hits
        self.calls = []

    async def detail_fields_for(self, city, name):
        self.calls.append(name)
        hours = self._hits.get(name)
        return {"opening_hours": hours} if hours else None


class _QuotaAmap(FakeAmap):
    async def place_hours(self, poi_id):
        self.detail_calls.append(poi_id)
        raise AmapQuotaExhaustedError("10021: USER_DAILY_QUERY_OVER_LIMIT")


def test_refresh_quota_exhausted_fails_fast_ctrip_keeps_running():
    store = PoiDetailStore()
    store.upsert("A1", city="重庆", name="甲景点")
    store.upsert("A2", city="重庆", name="乙景点")
    store.upsert("A3", city="重庆", name="丙景点")
    ctrip = _PickCtrip({"乙景点": "09:00-18:00"})
    amap = _QuotaAmap()
    stats = asyncio.run(refresh_pois(store, ctrip, amap, limit=10))
    assert stats["amap_quota_exhausted"] is True
    assert stats["amap_v5_detail"] == 0 and stats["amap_v5_search"] == 0
    assert stats["ctrip"] == 1  # 携程链不被熔断
    assert ctrip.calls == ["甲景点", "乙景点", "丙景点"]
    assert amap.detail_calls == ["A1"] and amap.search_calls == []
    assert stats["amap_skipped"] == 3  # 甲链③ + 丙链② + 丙链③
    assert stats["miss"] == 2 and stats["miss_cooldown"] == 2


class _NullCtrip:
    async def detail_fields_for(self, city, name):
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
    # is computed at failure time from the then-current constant).
    # Empty-retry constant too: the FIRST failure hits while memory is
    # still empty, so it latches _DB_DOWN_EMPTY_RETRY_SECONDS (2026-10-25)
    monkeypatch.setattr(mod, "_DB_DOWN_COOLDOWN_SECONDS", 0.05)
    monkeypatch.setattr(mod, "_DB_DOWN_EMPTY_RETRY_SECONDS", 0.05)
    assert store.get("B001") is None  # stall once, then memory
    store.upsert("B001", name="豫园", opening_hours="09:00-17:00")
    assert store.get("B001")["opening_hours"] == "09:00-17:00"
    assert down.calls == 1, "latch must suppress the second DB attempt"

    # cooldown expiry: attempts resume (and fail → memory still wins)
    import time as _time

    _time.sleep(0.06)
    assert store.get("B001")["opening_hours"] == "09:00-17:00"
    assert down.calls == 2


def test_db_down_empty_memory_short_cooldown_and_degraded_flag():
    """2026-10-25 占位事故修复：空内存失败走短冷却档（不再 5 分钟空
    候选窗口）；有数据仍走 300s 长档；无 DB 部署不算降级。"""
    import time as _time

    import app.services.poi_details as mod

    class DownFactory:
        def __call__(self):
            raise RuntimeError("connection refused")

    empty = mod.PoiDetailStore(session_factory=DownFactory())
    assert empty.top_pois_in_city("苏州") == []
    wait = empty._db_down_until - _time.monotonic()
    assert wait <= mod._DB_DOWN_EMPTY_RETRY_SECONDS
    assert wait < mod._DB_DOWN_COOLDOWN_SECONDS
    assert empty.db_degraded()

    loaded = mod.PoiDetailStore(session_factory=DownFactory())
    loaded.upsert("B1", city="苏州", name="拙政园")
    loaded._note_db_failure()
    wait_loaded = loaded._db_down_until - _time.monotonic()
    assert wait_loaded > mod._DB_DOWN_EMPTY_RETRY_SECONDS

    no_db = mod.PoiDetailStore(session_factory=None)
    assert not no_db.db_degraded()


def test_top_pois_tier_priority_5a_over_raw_rating():
    """2026-10-25 用户拍板 unesco>5A>4A>3A：名单行与名单互含命中行压过
    裸高分边缘点（城市阳台事件），tier 标签注入候选 tags 供 LLM 同享。"""
    store = PoiDetailStore()
    store.upsert("A1", city="杭州", name="城市阳台", rating=4.8)
    store.upsert("A2", city="杭州", name="灵隐飞来峰景区", rating=4.6)
    store.upsert("A3", city="杭州", name="灵隐飞来峰", source="5a")
    store.upsert("A4", city="杭州", name="杭州西湖文化景观", source="unesco")
    top = store.top_pois_in_city("杭州")
    names = [h["name"] for h in top]
    assert names.index("杭州西湖文化景观") < names.index("城市阳台")
    assert names.index("灵隐飞来峰景区") < names.index("城市阳台")
    by_name = {h["name"]: h for h in top}
    assert "5a" in by_name["灵隐飞来峰景区"]["tags"]


def test_top_pois_intl_pick_tier_over_raw_rating():
    """2026-10-25 intl 种子：TA/LP 人气榜行与 5A 同档（tier 3），
    标签注入打 intl 而非 5a，压过裸高分边缘点。"""
    store = PoiDetailStore()
    store.upsert("A1", city="上海", name="武康路", rating=4.3)
    store.upsert("A2", city="上海", name="城市边缘点", rating=4.8)
    store._memory["A1"]["tags"] = ["intl", "lp"]
    top = store.top_pois_in_city("上海")
    names = [h["name"] for h in top]
    assert names.index("武康路") < names.index("城市边缘点")
    tags = {h["name"]: h["tags"] for h in top}
    assert "intl" in tags["武康路"]
    assert "5a" not in tags["武康路"]


def test_top_pois_injected_tier_tag_respects_source_order():
    """2026-10-26 打标序：读路径注入的 unesco 排国外榜单之后，
    不垫到其它标签（如博物馆分级）后面。"""
    store = PoiDetailStore()
    store.upsert("A1", city="北京", name="故宫博物院", rating=4.5)
    store._memory["A1"]["source"] = "unesco"
    store._memory["A1"]["tags"] = ["ta", "lp", "intl", "国家一级博物馆"]
    top = store.top_pois_in_city("北京")
    tags = next(h["tags"] for h in top if h["name"] == "故宫博物院")
    assert tags[:3] == ["ta", "lp", "intl"]
    assert tags.index("unesco") < tags.index("国家一级博物馆")


# --- 0009：top_pois_in_city 确定性排序（内存态） ---


def test_top_pois_in_city_orders_by_quality_and_keeps_tag_rows():
    store = PoiDetailStore()
    store.upsert(
        "P1",
        city="重庆",
        name="评分高点评多",
        category="attraction",
        rating=4.8,
        rating_count=10000,
        location=(106.5, 29.5),
    )
    store.upsert(
        "P2",
        city="重庆",
        name="评分同但点评少",
        category="attraction",
        rating=4.8,
        rating_count=100,
        location=(106.5, 29.5),
    )
    store.upsert(
        "P3",
        city="重庆",
        name="UNESCO 无评分",
        category="attraction",
        location=(106.6, 29.6),
    )
    store.upsert("P4", city="重庆", name="餐厅", category="food")
    store.upsert("P5", city="北京", name="别城", category="attraction")
    # tags 不在 upsert 签名内（导入作业走 ORM）——内存态直塞测加成
    store._memory["P3"]["tags"] = ["unesco"]
    hits = store.top_pois_in_city("重庆市", 10)
    names = [h["name"] for h in hits]
    assert "餐厅" not in names and "别城" not in names
    assert names.index("评分高点评多") < names.index("评分同但点评少")
    assert "UNESCO 无评分" in names  # 无评分不埋没
    # 2026-10-25 用户拍板 unesco>5A>4A>3A：tier 居首压过裸评分，
    # tier 内部再按 quality 排（P1 先于 P2）
    assert names[0] == "UNESCO 无评分"
    top = hits[1]
    assert top["best_visit_time"] == "any"
    assert top["location"] == (106.5, 29.5)
