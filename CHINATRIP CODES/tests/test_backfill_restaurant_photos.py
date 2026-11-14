"""Tests for app.jobs.backfill_restaurant_photos（restaurants 照片回源 job）
+ poi_photos 的 v5 place/around 档（无 amap id 行）.

Job 侧骨架测试同 test_backfill_photos.py 口径：monkeypatch
fetch_photo_chain，验证只填空/尝试即落戳/配额熔断。链侧验证 around
档接入语义：命中名才收（"amap"）、未命中降级 wikimedia、无坐标与
amap=None 跳过 around。
"""

import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.services.amap_client import AmapQuotaExhaustedError


def make_row(**over) -> SimpleNamespace:
    base = dict(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        photos=None,
        photos_source=None,
        photos_fetched_at=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


class FakeSession:
    def __init__(self, row):
        self._row = row
        self.commits = 0

    def get(self, model, key):
        return self._row if self._row and self._row.id == key else None

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stats() -> dict:
    return {
        "targets": 0,
        "hits": 0,
        "no_data": 0,
        "errors": 0,
        "filled": {},
        "stop": None,
    }


# --- 坐标提取 _row_lonlat（纯函数） ----------------------------------------------


def test_row_lonlat_from_wkb_geography_column():
    from app.services.poi_photos import _row_lonlat

    wkb = from_shape(Point(106.55, 29.56), srid=4326)
    assert isinstance(wkb, WKBElement)
    lon, lat = _row_lonlat(wkb)
    assert (round(lon, 2), round(lat, 2)) == (106.55, 29.56)


def test_row_lonlat_from_lonlat_string_and_tuple_and_geopoint():
    from app.services.poi_photos import _row_lonlat

    assert _row_lonlat("106.55,29.56") == (106.55, 29.56)
    assert _row_lonlat((106.55, 29.56)) == (106.55, 29.56)
    assert _row_lonlat(SimpleNamespace(lon=106.55, lat=29.56)) == (106.55, 29.56)
    assert _row_lonlat(None) is None
    assert _row_lonlat("not-a-point") is None


def test_match_terms_full_name_plus_stripped_variant():
    from app.services.poi_photos import _match_terms

    assert _match_terms("老火锅（解放碑店）") == ["老火锅（解放碑店）", "老火锅"]
    assert _match_terms("洪崖洞") == ["洪崖洞"]
    assert _match_terms("  ") == []


def test_match_terms_adds_first_segment_for_subtitle_names():
    """副标题长名（·/空格分栏）补首段档：amap 侧真名通常只到首段。"""
    from app.services.poi_photos import _match_terms

    assert _match_terms("乔街深夜食堂·生腌熟醉·高压生蚝(滨盛路店)") == [
        "乔街深夜食堂·生腌熟醉·高压生蚝(滨盛路店)",
        "乔街深夜食堂·生腌熟醉·高压生蚝",
        "乔街深夜食堂",
    ]
    # 空格分栏同切；单字段不参与
    assert _match_terms("Tsuru 鹤日本料理") == ["Tsuru 鹤日本料理", "鹤日本料理"]
    assert _match_terms("南京晶丽酒店·南京精菜馆") == [
        "南京晶丽酒店·南京精菜馆",
        "南京晶丽酒店",
    ]


def test_search_keyword_prefers_first_segment():
    """around 关键词口径：首段 > 去括号全名 > 原串。"""
    from app.services.poi_photos import _search_keyword

    assert _search_keyword("乔街深夜食堂·生腌熟醉·高压生蚝(滨盛路店)") == "乔街深夜食堂"
    assert _search_keyword("老火锅（解放碑店）") == "老火锅"
    assert _search_keyword("洪崖洞") == "洪崖洞"
    assert _search_keyword("Yong") == "Yong"


def test_around_params_sends_segment_keyword(monkeypatch):
    """_around_params 组装：keywords=首段、radius/page_size/show_fields 口径不变。"""
    import app.services.poi_photos as pp

    monkeypatch.setattr(
        pp, "get_settings", lambda: SimpleNamespace(amap_api_key="test-key")
    )
    params = pp._around_params("南京晶丽酒店·南京精菜馆", (118.78, 32.06))
    assert params["keywords"] == "南京晶丽酒店"
    assert params["key"] == "test-key"
    assert params["location"] == "118.780000,32.060000"
    assert params["radius"] == "3000"
    assert params["page_size"] == "10"
    assert params["show_fields"] == "business,photos"


# --- fetch_photo_chain：v5 place/around 档（无 amap id 行） ----------------------


class _ChainPatch:
    """同时挂 around 与 wikimedia 两个桩，记录调用并按 state 出结果。"""

    def __init__(self, monkeypatch):
        import app.services.poi_photos as pp

        self.pp = pp
        self.around_calls: list[tuple[str, tuple[float, float]]] = []
        self.wikimedia_calls: list[str] = []
        self.around_result = None
        self.around_exc = None
        self.wikimedia_result = None
        self.wikimedia_exc = None

        async def fake_around(name_zh, lonlat):
            self.around_calls.append((name_zh, lonlat))
            if self.around_exc is not None:
                raise self.around_exc
            return self.around_result

        async def fake_wikimedia(name_zh):
            self.wikimedia_calls.append(name_zh)
            if self.wikimedia_exc is not None:
                raise self.wikimedia_exc
            return self.wikimedia_result

        monkeypatch.setattr(pp, "_amap_around_photos", fake_around)
        monkeypatch.setattr(pp, "_wikimedia", fake_wikimedia)


_PHOTOS = [{"title": "", "url": "https://img.example/r.jpg"}]


def _restaurant_row(**over) -> SimpleNamespace:
    base = dict(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        source="dianping",
        source_poi_id="",
        name_zh="老火锅（解放碑店）",
        city="重庆市",
        location=(106.55, 29.56),
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_chain_around_hit_returns_amap_and_skips_wikimedia(monkeypatch):
    patch = _ChainPatch(monkeypatch)
    patch.around_result = _PHOTOS
    photos, source = asyncio.run(
        patch.pp.fetch_photo_chain(_restaurant_row(), amap=object())
    )
    assert (photos, source) == (_PHOTOS, "amap")
    assert patch.around_calls == [("老火锅（解放碑店）", (106.55, 29.56))]
    assert patch.wikimedia_calls == []


def test_chain_around_miss_falls_to_wikimedia(monkeypatch):
    patch = _ChainPatch(monkeypatch)
    patch.around_result = None  # 未命中名/无图
    patch.wikimedia_result = _PHOTOS
    photos, source = asyncio.run(
        patch.pp.fetch_photo_chain(_restaurant_row(), amap=object())
    )
    assert (photos, source) == (_PHOTOS, "wikimedia")
    assert len(patch.around_calls) == 1
    assert patch.wikimedia_calls == ["老火锅（解放碑店）"]


def test_chain_around_quota_exhaustion_propagates_for_circuit_break(monkeypatch):
    patch = _ChainPatch(monkeypatch)
    patch.around_exc = AmapQuotaExhaustedError("quota")
    with pytest.raises(AmapQuotaExhaustedError):
        asyncio.run(patch.pp.fetch_photo_chain(_restaurant_row(), amap=object()))
    assert patch.wikimedia_calls == []  # 熔断：不降级继续烧下游


def test_chain_no_coordinates_skips_around(monkeypatch):
    patch = _ChainPatch(monkeypatch)
    patch.wikimedia_result = _PHOTOS
    row = _restaurant_row(location=None)
    photos, source = asyncio.run(patch.pp.fetch_photo_chain(row, amap=object()))
    assert patch.around_calls == []  # 无坐标：不敲 around
    assert (photos, source) == (_PHOTOS, "wikimedia")


def test_chain_amap_none_skips_around(monkeypatch):
    patch = _ChainPatch(monkeypatch)
    patch.wikimedia_result = _PHOTOS
    photos, source = asyncio.run(
        patch.pp.fetch_photo_chain(_restaurant_row(), amap=None)
    )
    assert patch.around_calls == []  # 无 key：整段 amap 跳过
    assert (photos, source) == (_PHOTOS, "wikimedia")


def test_chain_amap_id_rows_keep_old_path(monkeypatch):
    """有 amap id 的行不走 around（与 pois 现链一致）。"""
    patch = _ChainPatch(monkeypatch)
    patch.wikimedia_result = _PHOTOS

    class FakeAmap:
        async def place_hours(self, amap_id):
            return None

        async def search_poi(self, name, city=None):
            return []

    row = _restaurant_row(source="amap", source_poi_id="B001", location=(106.0, 29.0))
    photos, source = asyncio.run(patch.pp.fetch_photo_chain(row, amap=FakeAmap()))
    assert patch.around_calls == []
    assert (photos, source) == (_PHOTOS, "wikimedia")


# --- job：_write_row 只填空 + 尝试即落戳 ----------------------------------------


def test_write_row_fills_empty_photos_and_stamps_cooldown():
    from app.jobs.backfill_restaurant_photos import _write_row

    row = make_row()
    session = FakeSession(row)
    photos = [{"title": "", "url": "https://img.example/x.jpg"}]
    written = _write_row(lambda: session, row.id, photos, "amap")
    assert written == ["photos", "photos_source"]
    assert row.photos == photos
    assert row.photos_source == "amap"
    assert isinstance(row.photos_fetched_at, datetime)
    assert session.commits == 1


def test_write_row_never_overwrites_existing_photos():
    from app.jobs.backfill_restaurant_photos import _write_row

    existing = [{"title": "旧图", "url": "https://img.example/old.jpg"}]
    row = make_row(photos=existing, photos_source="wikimedia")
    session = FakeSession(row)
    new_photos = [{"title": "", "url": "https://img.example/new.jpg"}]
    written = _write_row(lambda: session, row.id, new_photos, "amap")
    assert written == []
    assert row.photos is existing  # 只填空铁律：不覆盖
    assert row.photos_source == "wikimedia"
    assert isinstance(row.photos_fetched_at, datetime)  # 戳照落


def test_write_row_empty_result_stamps_cooldown_fills_nothing():
    from app.jobs.backfill_restaurant_photos import _write_row

    row = make_row()
    session = FakeSession(row)
    written = _write_row(lambda: session, row.id, None, None)
    assert written == []
    assert row.photos is None
    assert row.photos_source is None
    assert isinstance(row.photos_fetched_at, datetime)


# --- job：_process_row 拉空落戳 / 配额熔断 ---------------------------------------


def _run_process(monkeypatch, *, chain_result=None, chain_exc=None):
    import app.jobs.backfill_restaurant_photos as job

    async def fake_chain(row, *, amap):
        if chain_exc is not None:
            raise chain_exc
        return chain_result

    monkeypatch.setattr(job, "fetch_photo_chain", fake_chain)
    row = make_row()
    session = FakeSession(row)
    stats = _stats()
    t = job._Target(row.id, "老火锅", "重庆市", "dianping", (106.55, 29.56))
    asyncio.run(job._process_row(None, lambda: session, t, asyncio.Semaphore(1), stats))
    return stats, session, row


def test_process_row_hit_fills_only_empty(monkeypatch):
    stats, session, row = _run_process(monkeypatch, chain_result=(_PHOTOS, "amap"))
    assert stats["hits"] == 1
    assert stats["filled"] == {"photos": 1, "photos_source": 1}
    assert row.photos == _PHOTOS
    assert row.photos_source == "amap"
    assert isinstance(row.photos_fetched_at, datetime)
    assert session.commits == 1


def test_process_row_no_data_stamps_cooldown(monkeypatch):
    stats, session, row = _run_process(monkeypatch, chain_result=(None, None))
    assert stats["no_data"] == 1
    assert stats["hits"] == 0
    assert isinstance(row.photos_fetched_at, datetime)
    assert row.photos is None  # around 未命中不写 photos
    assert session.commits == 1


def test_process_row_quota_exhaustion_stops_run(monkeypatch):
    stats, session, row = _run_process(
        monkeypatch, chain_exc=AmapQuotaExhaustedError("quota")
    )
    assert stats["stop"] == "quota_exhausted_stop"
    assert stats["hits"] == 0
    assert row.photos_fetched_at is None  # 未落戳：熔断行不占冷却，明日续跑
    assert session.commits == 0


def test_process_row_generic_error_counts_and_skips(monkeypatch):
    stats, _, row = _run_process(monkeypatch, chain_exc=RuntimeError("network down"))
    assert stats["errors"] == 1
    assert stats["hits"] == 0
    assert row.photos_fetched_at is None
