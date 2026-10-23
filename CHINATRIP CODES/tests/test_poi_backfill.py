"""poi_backfill 回源校验 + refresh_pois 新参数回归（无网络、内存 fake）.

铁律验证：外部源骨架行只在高德命中（名称相似 + 距离达标）时升级
source→amap；撞 ID 计 duplicate、未命中保留骨架、amap 挂全部计 error。
"""

import asyncio
import struct
import uuid

from geoalchemy2.elements import WKBElement

from app.jobs.refresh_pois import refresh_pois, rotate_cities
from app.models import Poi, Restaurant
from app.services.coords import haversine_m, make_point
from app.services.poi_backfill import (
    match_and_enrich,
    name_similar,
    normalize_name,
    skeleton_targets,
)
from app.services.poi_details import PoiDetailStore

# --- 内存 fake（只实现回源链用到的 query/get/commit） ------------------------


class FakeQuery:
    def __init__(self, rows, **kw):
        self._rows = rows
        self._kw = dict(kw)
        self._limit = None

    def filter_by(self, **kw):
        self._kw.update(kw)
        return self

    def filter(self, *criteria):  # SQL 条件由 Python 侧复筛兜底
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matched(self):
        rows = [
            r
            for r in self._rows
            if all(getattr(r, k, None) == v for k, v in self._kw.items())
        ]
        return rows[: self._limit] if self._limit is not None else rows

    def all(self):
        return self._matched()

    def one_or_none(self):
        rows = self._matched()
        return rows[0] if rows else None

    def first(self):
        rows = self._matched()
        return rows[0] if rows else None


class FakeSession:
    def __init__(self, rows):
        self.rows = list(rows)
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, model, pk):
        return next((r for r in self.rows if r.id == pk), None)

    def query(self, model):
        return FakeQuery(self.rows)

    def commit(self):
        self.commits += 1


class FakeFactory:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def __call__(self):
        return FakeSession(self.rows)


class StubAmap:
    """search_poi 固定返回候选列表；place_hours/search_hours 记调用。"""

    def __init__(self, candidates=None, error=False):
        self.calls = []
        self.detail_calls = []
        self.search_calls = []
        self._candidates = list(candidates or [])
        self._error = error

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append((keywords, city))
        if self._error:
            raise RuntimeError("amap down")
        return list(self._candidates)

    async def place_hours(self, poi_id):
        self.detail_calls.append(poi_id)
        return {"opening_hours": "09:00-17:00", "rating": None, "address": "某路1号"}

    async def search_hours(self, keyword, city=None):
        self.search_calls.append((keyword, city))
        return {
            "opening_hours": "09:00-21:00",
            "rating": None,
            "matched": keyword,
            "address": None,
        }


class _NullCtrip:
    async def hours_for(self, city, name):
        return None


def make_row(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        source="chinatravel",
        source_poi_id=f"ct-{uuid.uuid4().hex[:6]}",
        city="重庆",
        name_zh="洪崖洞",
        status="active",
        origin="chinatravel",
        location=make_point(106.578, 29.5628),
    )
    defaults.update(kw)
    return Poi(**defaults)


def cand(name="洪崖洞", poi_id="B001", lon=106.578, lat=29.5628, **extra):
    out = {
        "source": "amap",
        "source_poi_id": poi_id,
        "name": name,
        "city": "重庆",
        "address": "嘉陵江滨江路88号",
        "location": {"lon": lon, "lat": lat},
        "opening_hours": None,
        "rating": "4.6",
        "phone": "023-61234567",
    }
    out.update(extra)
    return out


# --- 纯函数 ------------------------------------------------------------------


def test_normalize_name_fullwidth_brackets_whitespace():
    assert normalize_name("洪崖洞（解放碑店）") == "洪崖洞"
    assert normalize_name("三峡博物馆【临时展馆】") == "三峡博物馆"
    assert normalize_name("洪崖洞 (Hongya Cave)") == "洪崖洞"
    assert normalize_name("　洪崖洞 ") == "洪崖洞"  # 全角空格 + 首尾空白
    assert normalize_name("Ｈｏｎｇｙａ ＣＡＶＥ") == "hongyacave"  # 全角→半角
    assert normalize_name("Hongya CAVE") == "hongyacave"
    assert normalize_name("") == ""


def test_name_similar_ratio():
    assert name_similar("洪崖洞", "洪崖洞") == 1.0
    assert name_similar("HONGYA CAVE", "hongya  cave") == 1.0  # 归一后同串
    # 3/8 字符重合 → 6/11 ≈ 0.545，低于命中阈值
    assert name_similar("洪崖洞", "洪崖洞民俗风貌区") < 0.75
    assert name_similar("洪崖洞", "磁器口古镇") < 0.5


# --- match_and_enrich ---------------------------------------------------------


def test_match_hit_upgrades_row_and_backfills():
    row = make_row()
    factory = FakeFactory([row])
    amap = StubAmap([cand()])
    stats = asyncio.run(match_and_enrich(factory, Poi, [row], amap))
    assert stats == {"matched": 1, "duplicate": 0, "miss": 0, "error": 0}
    assert row.source == "amap"
    assert row.source_poi_id == "B001"
    assert row.origin == "chinatravel"  # 初始发现渠道保留
    assert row.phone == "023-61234567"
    assert row.address == "嘉陵江滨江路88号"
    assert float(row.rating) == 4.6
    assert row.rating_source == "amap"
    assert amap.calls == [("重庆洪崖洞", "重庆")]
    assert row.updated_at is not None


def test_match_hit_photos_backfill_when_present():
    row = make_row()
    amap = StubAmap([cand(photos=[{"url": "https://x/1.jpg"}])])
    stats = asyncio.run(match_and_enrich(FakeFactory([row]), Poi, [row], amap))
    assert stats["matched"] == 1
    assert row.photos == [{"url": "https://x/1.jpg"}]
    assert row.photos_source == "amap"


def test_match_duplicate_amap_id_taken_by_other_row():
    row = make_row()
    owner = make_row(source="amap", source_poi_id="B001", name_zh="同名行")
    factory = FakeFactory([row, owner])
    stats = asyncio.run(match_and_enrich(factory, Poi, [row], StubAmap([cand()])))
    assert stats["duplicate"] == 1 and stats["matched"] == 0
    assert row.source == "chinatravel"  # 不升级
    assert row.source_poi_id.startswith("ct-")
    assert row.phone is None


def test_match_low_similarity_keeps_skeleton():
    row = make_row()
    amap = StubAmap([cand(name="磁器口古镇")])
    stats = asyncio.run(match_and_enrich(FakeFactory([row]), Poi, [row], amap))
    assert stats["miss"] == 1
    assert row.source == "chinatravel"  # 不 inactive 不删除
    assert row.phone is None and row.rating is None


def test_match_distance_boundary_500m():
    row = make_row()
    near = make_row()
    far = make_row()
    lat = 29.5628
    # 同经度纯纬度差：0.00449° ≈ 499.2m（≤500 命中）；0.0045° ≈ 500.4m（超限）
    amap_near = StubAmap([cand(lat=lat + 0.00449)])
    assert haversine_m(106.578, lat, 106.578, lat + 0.00449) <= 500
    stats_near = asyncio.run(
        match_and_enrich(FakeFactory([near]), Poi, [near], amap_near)
    )
    assert stats_near["matched"] == 1

    amap_far = StubAmap([cand(lat=lat + 0.0045)])
    assert haversine_m(106.578, lat, 106.578, lat + 0.0045) > 500
    stats_far = asyncio.run(match_and_enrich(FakeFactory([far]), Poi, [far], amap_far))
    assert stats_far["miss"] == 1
    assert row.source == "chinatravel"  # 原行未被波及


def test_match_amap_none_all_error_no_crash():
    row1, row2 = make_row(), make_row(name_zh="磁器口")
    stats = asyncio.run(
        match_and_enrich(FakeFactory([row1, row2]), Poi, [row1, row2], None)
    )
    assert stats == {"matched": 0, "duplicate": 0, "miss": 0, "error": 2}
    assert row1.source == "chinatravel"


def test_match_search_exception_row_error_continues():
    ok_row = make_row(name_zh="磁器口")
    bad_row = make_row()
    amap = StubAmap(error=True)
    stats = asyncio.run(
        match_and_enrich(FakeFactory([bad_row, ok_row]), Poi, [bad_row, ok_row], amap)
    )
    assert stats["error"] == 2  # 每行独立计 error，不 crash
    assert bad_row.source == "chinatravel"


def test_match_missing_coordinates_is_miss():
    row = make_row(location=None)  # 骨架行无坐标 → 无法确认距离 → 宁缺勿错
    stats = asyncio.run(
        match_and_enrich(FakeFactory([row]), Poi, [row], StubAmap([cand()]))
    )
    assert stats["miss"] == 1


def test_match_wkb_location_from_real_db_shape():
    # 真库读回是 WKBElement（hex WKB：byte order + type + X + Y）
    wkb = WKBElement(struct.pack("<BIdd", 1, 1, 106.578, 29.5628).hex(), srid=4326)
    row = make_row(location=wkb)
    stats = asyncio.run(
        match_and_enrich(FakeFactory([row]), Poi, [row], StubAmap([cand()]))
    )
    assert stats["matched"] == 1
    assert row.source == "amap"


def test_match_works_for_restaurant_model():
    row = Restaurant(
        id=uuid.uuid4(),
        source="chinatravel",
        source_poi_id="r-9",
        city="成都",
        name_zh="小龙坎",
        origin="chinatravel",
        location=make_point(104.065, 30.657),
    )
    amap = StubAmap(
        [cand(name="小龙坎", poi_id="B900", lon=104.065, lat=30.657, rating="4.2")]
    )
    stats = asyncio.run(match_and_enrich(FakeFactory([row]), Restaurant, [row], amap))
    assert stats["matched"] == 1
    assert row.source == "amap"
    assert row.source_poi_id == "B900"
    assert row.cuisine is None  # 回源不碰类别
    assert float(row.rating) == 4.2


# --- skeleton_targets ----------------------------------------------------------


def test_skeleton_targets_filters_source_and_status():
    active_ct = make_row()
    inactive = make_row(status="inactive")
    active_osm = make_row(source="osm")
    amap_row = make_row(source="amap")
    factory = FakeFactory([active_ct, inactive, active_osm, amap_row])
    out = skeleton_targets(factory, Poi)
    assert {r.id for r in out} == {active_ct.id, active_osm.id}
    out_osm = skeleton_targets(factory, Poi, sources=("osm",))
    assert {r.id for r in out_osm} == {active_osm.id}
    assert len(skeleton_targets(factory, Poi, limit=1)) == 1


# --- refresh_pois 新参数回归 -----------------------------------------------------


def test_rotate_cities_pure_function():
    week = ["a", "b", "c", "d", "e", "f", "g"]
    assert rotate_cities(week, 0) == ["a"]
    assert rotate_cities(week, 6) == ["g"]
    assert [rotate_cities(week, d)[0] for d in range(7)] == week  # 一周覆盖全城
    eight = ["a", "b", "c", "d", "e", "f", "g", "h"]
    assert rotate_cities(eight, 0) == ["a", "h"]  # 每 7 取 1，负载 1/7
    assert rotate_cities(["a", "b", "c"], 1) == ["b"]  # 不足 7 城循环覆盖
    assert rotate_cities([], 3) == []


def test_refresh_source_filter_and_skeleton_skips_v5_detail():
    store = PoiDetailStore()
    store.upsert("B1", city="重庆", name="景点A")  # amap 行
    store.upsert("C1", city="北京", name="骨架B", source="chinatravel")  # 骨架行
    # stale_pois 四元组 + sources 过滤
    assert ("C1", "北京", "骨架B", "chinatravel") in store.stale_pois()
    assert [t[0] for t in store.stale_pois(sources=("chinatravel",))] == ["C1"]

    amap = StubAmap()
    stats = asyncio.run(
        refresh_pois(store, _NullCtrip(), amap, limit=10, sources=("chinatravel",))
    )
    assert stats["total"] == 1
    # 无 --match：骨架行跳过链②（poi_id 非高德 ID 直查无意义）→ 链③关键词命中
    assert amap.detail_calls == []
    assert stats["amap_v5_search"] == 1 and stats["miss"] == 0


def test_refresh_match_upgrades_then_v5_detail_fills_hours():
    row = make_row(source_poi_id="ct-1")
    factory = FakeFactory([row])
    store = PoiDetailStore()
    store.upsert("ct-1", city="重庆", name="洪崖洞", source="chinatravel")
    amap = StubAmap([cand(poi_id="B001")])
    stats = asyncio.run(
        refresh_pois(
            store,
            _NullCtrip(),
            amap,
            limit=10,
            match=True,
            session_factory=factory,
        )
    )
    assert stats["matched"] == 1 and stats["duplicate"] == 0
    # 升级后 source_poi_id 是高德 ID → 链② 直查命中，链③ 未触发
    assert stats["amap_v5_detail"] == 1 and stats["amap_v5_search"] == 0
    assert amap.detail_calls == ["B001"]
    assert store.get("B001")["opening_hours"] == "09:00-17:00"
    assert row.source == "amap" and row.source_poi_id == "B001"
    assert row.phone == "023-61234567" and row.origin == "chinatravel"


def test_refresh_match_without_factory_degrades_gracefully():
    store = PoiDetailStore()
    store.upsert("C1", city="重庆", name="骨架A", source="chinatravel")
    amap = StubAmap()
    stats = asyncio.run(refresh_pois(store, _NullCtrip(), amap, limit=10, match=True))
    assert stats["matched"] == 0 and stats["duplicate"] == 0
    # 无法匹配 → 骨架行仍跳链②、走链③关键词兜底
    assert amap.detail_calls == []
    assert stats["amap_v5_search"] == 1


def test_refresh_match_without_amap_counts_error_not_crash():
    row = make_row(source_poi_id="ct-1")
    factory = FakeFactory([row])
    store = PoiDetailStore()
    store.upsert("ct-1", city="重庆", name="洪崖洞", source="chinatravel")
    stats = asyncio.run(
        refresh_pois(
            store,
            _NullCtrip(),
            None,
            limit=10,
            match=True,
            session_factory=factory,
        )
    )
    assert stats["matched"] == 0 and stats["duplicate"] == 0
    assert stats["miss"] == 1  # 行保留，下次有 amap 再试


def test_refresh_cities_filter_for_rotate_subset():
    store = PoiDetailStore()
    store.upsert("B1", city="重庆", name="景点A")
    store.upsert("B2", city="北京", name="景点B")
    stats = asyncio.run(refresh_pois(store, _NullCtrip(), None, cities=["重庆"]))
    assert stats["total"] == 1
    stats_bj = asyncio.run(refresh_pois(store, _NullCtrip(), None, cities=["北京市"]))
    assert stats_bj["total"] == 1  # 去「市」后缀同口径
    stats_none = asyncio.run(refresh_pois(store, _NullCtrip(), None))
    assert stats_none["total"] == 2  # 缺省不过滤 = 现状行为
