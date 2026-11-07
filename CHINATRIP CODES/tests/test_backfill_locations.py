# -*- coding: utf-8 -*-
"""backfill_locations 纯函数层：命中校验 / 同城相容 / source 优先档."""

import asyncio

from app.jobs.backfill_locations import (
    _SOURCE_RANK,
    city_compatible,
    name_overlap,
    order_backfill_rows,
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


class StubGeocoder:
    """geocode 桩（地址→坐标）。"""

    def __init__(self, *, vendor="baidu", ok=True, quota=False):
        self.vendor = vendor
        self.ok = ok
        self.quota = quota
        self.calls = 0

    async def geocode(self, address: str, *, city: str | None = None) -> dict:
        self.city_seen = city
        self.calls += 1
        if self.quota:
            from app.services.amap_client import AmapQuotaExhaustedError

            raise AmapQuotaExhaustedError("quota", "302")
        if not self.ok:
            return {"lon": None, "lat": None, "level": None}
        return {"lon": 104.06, "lat": 30.65, "level": "门址"}


def _addr_row(i, name="九龙沟", address="四川省成都市某路 1 号"):
    r = _row(i, name)
    r.address = address
    return r


def test_geocode_track_fills_address_rows_without_search():
    from app.jobs.backfill_locations import backfill_rows

    store = StoreStub()
    geo = StubGeocoder()
    search = StubSearch("never", hits=[])
    stats = asyncio.run(backfill_rows(store, [search], [_addr_row(1)], geocoder=geo))
    assert stats["filled"] == 1
    assert stats["geocode_filled"] == 1
    assert stats["by_vendor"] == {"baidu_geocode": 1}
    assert search.calls == 0  # 地址命中即短路，不烧检索配额
    assert store.upserts[0][1]["location"] == (104.06, 30.65)
    assert geo.city_seen == "成都"  # 行城市作为地理编码上下文


def test_geocode_quota_death_falls_to_search_chain():
    from app.jobs.backfill_locations import backfill_rows

    store = StoreStub()
    geo = StubGeocoder(quota=True)
    hit = [{"name": "九龙沟", "city": "成都", "location": "104.0,30.6"}]
    search = StubSearch("amap", hits=hit)
    stats = asyncio.run(
        backfill_rows(store, [search], [_addr_row(1), _addr_row(2)], geocoder=geo)
    )
    assert stats["geocode_quota_stopped"] == 1
    assert stats["filled"] == 2
    assert stats["by_vendor"] == {"amap": 2}
    assert geo.calls == 1  # latch：第二行不再撞 geocode


def test_geocode_quota_death_with_dead_search_chain_stops_clean():
    # geocode 配额死 + 检索链全死/空：干净停机，剩余行不写 miss 台账
    # （配额烧尽可次日重试，台账只收确定性未命中，2026-11-03）。
    from app.jobs.backfill_locations import backfill_rows

    geo = StubGeocoder(quota=True)
    search = StubSearch("amap", quota_after=0)
    stats = asyncio.run(
        backfill_rows(
            StoreStub(),
            [search],
            [_addr_row(1), _addr_row(2), _addr_row(3)],
            geocoder=geo,
        )
    )
    assert stats.get("stopped_no_channel") == 1
    assert stats["missed"] == 0
    assert stats["geocode_quota_stopped"] == 1
    assert search.calls == 1  # 撞一次配额即 latch


def test_geocode_quota_death_with_empty_search_chain_stops_clean():
    # 探针预检后检索链为空（三家全死）+ geocode 中途烧尽：geocode 存活期
    # 的未命中仍是确定性 miss（入台账），geocode 死后剩余行零网络干净停机
    # 不写台账（2026-11-03）。
    from app.jobs.backfill_locations import backfill_rows

    class GeoDiesAtSecond(StubGeocoder):
        async def geocode(self, address, *, city=None):
            self.calls += 1
            if self.calls > 1:
                from app.services.amap_client import AmapQuotaExhaustedError

                raise AmapQuotaExhaustedError("quota", "302")
            return {"lon": None, "lat": None, "level": None}

    stats = asyncio.run(
        backfill_rows(
            StoreStub(),
            [],
            [_addr_row(1), _addr_row(2), _addr_row(3)],
            geocoder=GeoDiesAtSecond(),
        )
    )
    assert stats.get("stopped_no_channel") == 1
    assert stats["missed"] == 1  # 仅首行（geocode 存活期确定性未命中）入台账
    assert stats["geocode_quota_stopped"] == 1


def test_addressless_rows_geocode_by_city_and_name():
    # 无门址行（宽窄巷子类纯名字骨架）用 城市+名字 geocode（2026-10-30）。
    from app.jobs.backfill_locations import backfill_rows

    geo = StubGeocoder()
    stats = asyncio.run(
        backfill_rows(StoreStub(), [StubSearch("amap")], [_row(1)], geocoder=geo)
    )
    assert geo.calls == 1
    assert geo.city_seen == "成都"
    assert stats["by_vendor"] == {"baidu_geocode": 1}


def test_source_rank_covers_p2_sources():
    # 2026-11-01 master backlog #4/#9:4a/国保/遗址公园/名村/intl/预约名单
    # 入档,不再与 chinatravel 长尾同落 99 档混排。
    assert _SOURCE_RANK["4a"] == 8 > _SOURCE_RANK["histvillage"]  # 2026-11-01 拍板先放
    assert _SOURCE_RANK["intl"] == _SOURCE_RANK["reservation"] < _SOURCE_RANK["4a"]
    assert _SOURCE_RANK["guobao8"] == _SOURCE_RANK["relicpark"]
    assert _SOURCE_RANK["relicpark"] == _SOURCE_RANK["museum1"]
    assert _SOURCE_RANK["histvillage"] == _SOURCE_RANK["street"]
    assert _SOURCE_RANK["street"] < _SOURCE_RANK["4a"] < _SOURCE_RANK["chinatravel"]
    for src in ("4a", "guobao8", "relicpark", "histvillage", "intl", "reservation"):
        assert _SOURCE_RANK[src] < 99


def test_hot_city_first_within_same_rank():
    # 2026-11-03 数据债 P1-1「城市热度×tier」：档位内核心 40 城先补——
    # 博物馆长尾里成都/西安行的入池价值高于县域馆。
    from types import SimpleNamespace

    def row(name: str, city: str) -> SimpleNamespace:
        return SimpleNamespace(source="museum2", city=city, name_zh=name)

    hot = row("成都自然博物馆", "成都")
    hot_b = row("西安博物院", "西安")
    cold = row("英吉沙博物馆", "英吉沙")
    assert order_backfill_rows([cold, hot_b, hot]) == [hot, hot_b, cold]


def test_geocode_chain_falls_over_quota_dead_vendor_and_labels_actual_vendor():
    from app.services.map_provider import GeocodeChain

    class DeadGeo:
        vendor = "baidu"

        async def geocode(self, address: str, *, city: str | None = None) -> dict:
            from app.services.amap_client import AmapQuotaExhaustedError

            raise AmapQuotaExhaustedError("quota", "302")

    class OkGeo:
        vendor = "amap"

        async def geocode(self, address: str, *, city: str | None = None) -> dict:
            return {"lon": 104.0, "lat": 30.6, "level": "门址"}

    chain = GeocodeChain([DeadGeo(), OkGeo()])
    geo = asyncio.run(chain.geocode("成都某路", city="成都"))
    assert geo["lon"] == 104.0
    assert chain.last_vendor == "amap"


# --- 2026-11-04 P1#1 回退点入库闸：解析点=城市 gov 点→拒绝 ------------------


def _cq_row(i, name="金佛山", address=None):
    r = _row(i, name)
    r.city = "重庆"
    if address is not None:
        r.address = address
    return r


def test_geocode_city_fallback_point_rejected_falls_to_search():
    # 解析点=渝中区政府（城市回退点，距城 0km 恒过 500km 闸）→拒绝不入库，
    # 退检索链按名搜补上（181 行投毒的根因路径，P1#1）。
    from app.jobs.backfill_locations import backfill_rows

    class CqGeocoder(StubGeocoder):
        async def geocode(self, address, *, city=None):
            self.calls += 1
            return {"lon": 106.550464, "lat": 29.563761, "level": "门址"}

    store = StoreStub()
    geo = CqGeocoder()
    hit = [{"name": "金佛山", "city": "重庆", "location": "107.19,29.03"}]
    search = StubSearch("amap", hits=hit)
    stats = asyncio.run(backfill_rows(store, [search], [_cq_row(1)], geocoder=geo))
    assert stats["geocode_fallback_rejected"] == 1
    assert stats["filled"] == 1
    assert stats["by_vendor"] == {"amap": 1}  # 检索链补上，不是 geocode
    assert store.upserts[0][1]["location"] == (107.19, 29.03)


def test_geocode_fallback_point_without_search_hit_stays_empty():
    # 回退点被拒且检索无命中：宁缺勿错不落库（留待 donor/回源修复）。
    from app.jobs.backfill_locations import backfill_rows

    class CqGeocoder(StubGeocoder):
        async def geocode(self, address, *, city=None):
            return {"lon": 106.550464, "lat": 29.563761, "level": "门址"}

    stats = asyncio.run(
        backfill_rows(
            StoreStub(), [StubSearch("amap")], [_cq_row(1)], geocoder=CqGeocoder()
        )
    )
    assert stats["geocode_fallback_rejected"] == 1
    assert stats["filled"] == 0
    assert stats["missed"] == 1


def test_fallback_family_address_skips_geocode_track():
    # 地址同型闸：行地址=「渝中区上清寺」系（geocoder 写入的政府驻地
    # 地址，地址本身已投毒）→ geocode 轨道不烧配额，退检索按名搜。
    from app.jobs.backfill_locations import backfill_rows

    store = StoreStub()
    geo = StubGeocoder()
    hit = [{"name": "金佛山", "city": "重庆", "location": "107.19,29.03"}]
    search = StubSearch("amap", hits=hit)
    stats = asyncio.run(
        backfill_rows(
            store,
            [search],
            [_cq_row(1, address="重庆市渝中区上清寺人民支路69号")],
            geocoder=geo,
        )
    )
    assert geo.calls == 0  # 地址投毒，geocode 一次都不撞
    assert stats["fallback_addr_skipped"] == 1
    assert stats["filled"] == 1
    assert stats["by_vendor"] == {"amap": 1}


def test_search_hit_at_fallback_point_rejected():
    # 检索命中落回退点（同名 gov POI 类命中）→拒绝不落库。
    from app.jobs.backfill_locations import backfill_rows

    hit = [{"name": "金佛山", "city": "重庆", "location": "106.550464,29.563761"}]
    stats = asyncio.run(
        backfill_rows(StoreStub(), [StubSearch("amap", hits=hit)], [_cq_row(1)])
    )
    assert stats["search_fallback_rejected"] == 1
    assert stats["filled"] == 0


def test_other_city_geocode_results_unaffected():
    # 注册表外城市（成都）不误伤：geocode 正常落库。
    from app.jobs.backfill_locations import backfill_rows

    store = StoreStub()
    stats = asyncio.run(
        backfill_rows(store, [StubSearch("amap")], [_row(1)], geocoder=StubGeocoder())
    )
    assert stats["geocode_fallback_rejected"] == 0
    assert stats["filled"] == 1
    assert stats["geocode_filled"] == 1
