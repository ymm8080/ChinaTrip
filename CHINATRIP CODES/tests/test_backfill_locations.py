# -*- coding: utf-8 -*-
"""backfill_locations 纯函数层：命中校验 / 同城相容 / source 优先档."""

import asyncio

from app.jobs.backfill_locations import (
    _SOURCE_RANK,
    city_compatible,
    name_overlap,
    pick_hit,
)


def _hit(name, city, loc="104.06,30.65"):
    return {"name": name, "city": city, "location": loc}


def test_pick_hit_takes_first_valid():
    hits = [
        _hit("九龙沟漂流", "四川省成都市大邑县", None),  # 无坐标跳过
        {"name": "贡院", "city": "南京市", "location": "118.79,32.05"},  # 异城拒
        _hit("九龙沟", "成都市"),  # 名称互含过
    ]
    assert pick_hit(hits, "九龙沟漂流", "成都")["name"] == "九龙沟"


def test_pick_hit_rejects_wrong_city_even_if_name_equal():
    hits = [_hit("西湖", "杭州市")]
    assert pick_hit(hits, "西湖", "兰州") is None


def test_pick_hit_accepts_empty_hit_city():
    hits = [{"name": "白云山索道", "city": "", "location": "113.3,23.1"}]
    assert pick_hit(hits, "白云山索道", "广州") is not None


def test_name_overlap_strips_punctuation_and_parens():
    assert name_overlap("洪崖洞（民俗风貌区）", "洪崖洞民俗风貌区")
    assert name_overlap("西湖", "西湖风景名胜区")  # 短侧≥2 字即互含（防异地靠城校验）
    assert not name_overlap("灵隐寺", "飞来峰景区")  # 无互含拒


def test_city_compatible_tolerates_suffix_and_prefix():
    assert city_compatible("成都", "成都市")
    assert city_compatible("成都市", "四川省成都市")
    assert not city_compatible("成都", "杭州")


def test_source_rank_orders_named_lists_first():
    assert _SOURCE_RANK["unesco"] < _SOURCE_RANK["5a"] < _SOURCE_RANK["scenic"]
    assert _SOURCE_RANK["5a"] < _SOURCE_RANK["amap"]


class StubSearch:
    def __init__(self, vendor, *, hits=None, quota_after=None):
        self.vendor = vendor
        self.hits = hits or []
        self.quota_after = quota_after
        self.calls = 0

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls += 1
        if self.quota_after is not None and self.calls >= self.quota_after:
            from app.services.amap_client import AmapQuotaExhaustedError

            raise AmapQuotaExhaustedError("quota", "302")
        return self.hits


class StoreStub:
    def __init__(self):
        self.upserts = []

    def upsert(self, poi_id, **kw):
        self.upserts.append((poi_id, kw))


class _Row:
    source_poi_id = ""
    name_zh = ""
    city = ""
    source = "5a"


def _row(i, name="九龙沟"):
    r = _Row()
    r.source_poi_id = f"P{i}"
    r.name_zh = name
    r.city = "成都"
    return r


def test_backfill_rows_latches_dead_vendor_and_falls_over():
    from app.jobs.backfill_locations import backfill_rows

    store = StoreStub()
    hit = [{"name": "九龙沟", "city": "成都", "location": "104.0,30.6"}]
    v1 = StubSearch("first", hits=hit, quota_after=2)
    v2 = StubSearch("second", hits=hit)
    stats = asyncio.run(backfill_rows(store, [v1, v2], [_row(1), _row(2), _row(3)]))
    assert stats["filled"] == 3
    assert stats["quota_stopped"] == 1
    assert stats["by_vendor"] == {"first": 1, "second": 2}
    assert v1.calls == 2  # latch：配额死后不再撞死家
    assert len(store.upserts) == 3


def test_backfill_rows_stops_when_all_vendors_dead():
    from app.jobs.backfill_locations import backfill_rows

    v1 = StubSearch("first", quota_after=0)
    v2 = StubSearch("second", quota_after=0)
    stats = asyncio.run(backfill_rows(StoreStub(), [v1, v2], [_row(1), _row(2)]))
    assert stats["filled"] == 0
    assert stats.get("stopped_no_channel") == 1
    assert stats["missed"] == 1  # 只处理第一行即停


def test_hit_lonlat_accepts_dict_string_and_tuple():
    from app.jobs.backfill_locations import hit_lonlat

    assert hit_lonlat({"location": {"lon": 104.06, "lat": 30.65}}) == (104.06, 30.65)
    assert hit_lonlat({"location": "104.06,30.65"}) == (104.06, 30.65)
    assert hit_lonlat({"location": (104.06, 30.65)}) == (104.06, 30.65)
    assert hit_lonlat({"location": {"lng": 1, "lat": 2}}) is None  # 非约定键
    assert hit_lonlat({"location": None}) is None
