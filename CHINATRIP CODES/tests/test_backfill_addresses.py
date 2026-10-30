# -*- coding: utf-8 -*-
"""backfill_addresses 纯函数层：WKT 解析 / source 优先档 / regeo 链路 stub。"""

import asyncio

from app.jobs.backfill_addresses import (
    _SOURCE_RANK,
    backfill_addresses,
    parse_lonlat,
)


def run(coro):
    return asyncio.run(coro)


class StubRegeo:
    """regeo 桩：可注入配额序列 / 恒失败。"""

    def __init__(
        self,
        *,
        vendor="stub",
        address="某省某市某路 1 号",
        quota_after=None,
        fail=False,
    ):
        self.vendor = vendor
        self.address = address
        self.quota_after = quota_after
        self.fail = fail
        self.calls = 0

    async def regeo(self, *, lon, lat):
        self.calls += 1
        if self.quota_after is not None and self.calls > self.quota_after:
            from app.services.amap_client import AmapQuotaExhaustedError

            raise AmapQuotaExhaustedError("quota", "121")
        if self.fail:
            raise RuntimeError("boom")
        return {"address": self.address}


class StoreStub:
    def __init__(self):
        self.upserts = []

    def upsert(self, poi_id, **kw):
        self.upserts.append((poi_id, kw))


def _row(i, source="chinatravel"):
    return {
        "poi_id": f"P{i}",
        "city": "成都",
        "name": f"点{i}",
        "source": source,
        "lonlat": (104.06, 30.65),
    }


def test_parse_lonlat():
    assert parse_lonlat("POINT(104.06 30.65)") == (104.06, 30.65)
    assert parse_lonlat("POINT(x y)") is None
    assert parse_lonlat(None) is None
    assert parse_lonlat("") is None


def test_source_rank_chinatravel_first():
    assert _SOURCE_RANK["chinatravel"] < _SOURCE_RANK["unesco"] < _SOURCE_RANK["5a"]


def test_quota_latch_falls_to_next_vendor_and_keeps_filling():
    store = StoreStub()
    primary = StubRegeo(vendor="baidu", quota_after=1)
    second = StubRegeo(vendor="amap")
    rows = [_row(1), _row(2), _row(3)]
    stats = run(backfill_addresses(store, [primary, second], rows=rows))
    assert stats["quota_stopped"] == 1
    assert stats["filled"] == 3
    assert len(store.upserts) == 3
    assert stats["by_vendor"] == {"baidu": 1, "amap": 2}
    assert second.calls == 2  # 主源死后剩余行走下一家


def test_all_quota_dead_stops_early():
    store = StoreStub()
    v1 = StubRegeo(vendor="v1", quota_after=0)
    v2 = StubRegeo(vendor="v2", quota_after=0)
    stats = run(backfill_addresses(store, [v1, v2], rows=[_row(1), _row(2)]))
    assert stats["filled"] == 0
    assert stats.get("stopped_no_channel") == 1
    assert stats["missed"] == 1  # 只处理第一行即停
    assert not store.upserts


def test_pure_failure_keeps_going_without_writes():
    store = StoreStub()
    primary = StubRegeo(fail=True)  # 退避重试一次仍炸
    stats = run(backfill_addresses(store, [primary], rows=[_row(1), _row(2)]))
    assert stats["filled"] == 0
    assert stats["missed"] == 2  # 纯失败不停：逐行记 miss，可能自愈
    assert stats.get("stopped_no_channel") == 0
    assert not store.upserts


def test_dry_run_counts_without_writes():
    store = StoreStub()
    primary = StubRegeo()
    stats = run(backfill_addresses(store, [primary], rows=[_row(1)], dry_run=True))
    assert stats["filled"] == 1
    assert stats["by_vendor"] == {"stub": 1}
    assert not store.upserts
