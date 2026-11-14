# -*- coding: utf-8 -*-
"""2026-11-13 陕历博跨城串行程 + 脏地址回归锚。

三件用户可见事实：
1. 西安心愿「陕西历史博物馆」被挂进成都重庆行程（行程中心可见）；
2. 该 POI 行被写成 city='未标注' + 云南孟连地址（图商全国召回撞名）；
3. 心愿单城市必须在插入时就定（不能等事后补写）。

对应修复：
- P1 start() 清会话外的 _wish_bindings（单例 agent 跨行程残留）；
- P2 _sync_wish_rows 行城闸：行城不在本次行程 → 不换绑/不翻已排期；
- P3 兜底检索不传城市哨兵「未标注」+ 命中名不像整条丢弃；
- P4 POI 回写不落哨兵城市；
- P5 心愿建行先吃绑定落点城市。
"""

from __future__ import annotations

import asyncio
from datetime import time as T

from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    _hours_hit_mismatch,
)
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.trip_items import TripItemService
from tests.test_wish_bind import CountingLLM, PandaStore


def _agent(svc, *, amap_client=None):
    return PlanningAgent(
        CountingLLM(),
        trip_items=svc,
        poi_details=PandaStore(),
        amap_client=amap_client,
        auto_restaurants=False,
    )


def _visit(name, *, city, day, poi_id="POI1"):
    # 2026-11-13（陕历博灰卡案）：无时刻卡不算已排期——夹具给真时刻，
    # 「城在行程内 → 翻已排期」的锚才测的是城闸而不是时刻闸。
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city=city,
        day=day,
        duration_minutes=120,
        category="attraction",
        poi_id=poi_id,
        start_time=T(9, 0),
        end_time=T(11, 0),
    )


def _session(cities, plan):
    session = PlanSession(session_id="s-cc", device_id="d1", cities=cities)
    session.plan = plan
    return session


# ---------------- P2：行城闸（不把西安心愿挂进成都重庆） ----------------


def test_off_trip_wish_row_is_not_relinked_or_scheduled():
    """西安心愿行 × 成都重庆行程：即便 agent 缓存里还留着旧绑定、行程里
    恰好有同名条目，行也不得换绑/翻已排期。"""
    svc = TripItemService()
    row = svc.create("陕西历史博物馆", source="chat", city="西安")
    agent = _agent(svc)
    # 旧行程残留绑定（单例 agent 的跨会话脏状态）
    agent._wish_bindings["陕西历史博物馆"] = {
        "name": "陕西历史博物馆",
        "city": "西安",
        "source_poi_id": "POI-XA",
        "location": None,
    }
    plan = ItineraryPlan(
        itinerary_id="it-cc",
        cities=["上海", "成都", "重庆", "上海"],
        days=[
            DayPlan(
                day=5,
                base_city="上海",
                items=[_visit("陕西历史博物馆", city="未标注", day=5, poi_id="POI-XA")],
            )
        ],
    )
    agent._sync_wish_rows(_session(["上海", "成都", "重庆", "上海"], plan))

    fresh = svc.get(row["id"])
    assert fresh["status"] == "wishlist"
    assert not fresh["itinerary_id"]
    assert fresh["city"] == "西安"


def test_in_trip_wish_row_still_schedules():
    """反向锚：城在行程内的心愿仍照常换绑+翻已排期（闸不许误伤）。"""
    svc = TripItemService()
    row = svc.create("成都环球中心", source="chat", city="成都")
    agent = _agent(svc)
    agent._wish_bindings["成都环球中心"] = {
        "name": "成都环球中心",
        "city": "成都",
        "source_poi_id": "POI-CD",
        "location": None,
    }
    plan = ItineraryPlan(
        itinerary_id="it-cc",
        cities=["成都"],
        days=[
            DayPlan(
                day=2,
                base_city="成都",
                items=[_visit("成都环球中心", city="成都", day=2, poi_id="POI-CD")],
            )
        ],
    )
    agent._sync_wish_rows(_session(["成都"], plan))

    fresh = svc.get(row["id"])
    assert fresh["status"] == "scheduled"
    assert fresh["itinerary_id"] == "it-cc"
    assert fresh["day"] == 2


# ---------------- P1：会话级绑定隔离 ----------------


def test_start_clears_stale_wish_bindings():
    agent = _agent(TripItemService())
    agent._wish_bindings["陕西历史博物馆"] = {"city": "西安"}
    agent._wish_bind_misses.add("陕西历史博物馆")

    session = asyncio.run(
        agent.start(device_id="d1", cities=[], days=0, preferences="")
    )
    assert session.state == "clarify"
    assert agent._wish_bindings == {}
    assert agent._wish_bind_misses == set()


# ---------------- P3/P4：脏地址 ----------------


def test_hours_hit_mismatch_rejects_remote_namesake():
    assert _hours_hit_mismatch("陕西历史博物馆", "孟连县民族历史博物馆") is True
    assert _hours_hit_mismatch("陕西历史博物馆", "陕西历史博物馆") is False
    assert _hours_hit_mismatch("陕西历史博物馆", "陕西历史博物馆（新馆）") is False
    assert _hours_hit_mismatch("大雁塔", "大雁塔·大慈恩寺") is False
    # 无命中（matched 缺省）不判脏
    assert _hours_hit_mismatch("陕西历史博物馆", None) is False


class _BaiduStub:
    vendor = "baidu"


def test_hours_chain_never_sends_unspecified_city_and_drops_mismatch():
    """城市哨兵不下传图商；撞名命中（孟连地址）整条丢弃，不写回条目。"""
    seen: dict = {}

    async def search_hours(name, city=None):
        seen["city"] = city
        return {
            "opening_hours": None,
            "address": "云南省普洱市孟连傣族拉祜族佤族自治县滨河西路",
            "matched": "孟连县民族历史博物馆",
            "poi_id": "B-MENG",
        }

    agent = _agent(TripItemService(), amap_client=_BaiduStub())
    item = VisitItem(
        item_id="v1",
        name="陕西历史博物馆",
        city="未标注",
        day=1,
        duration_minutes=120,
        category="attraction",
    )
    out = asyncio.run(agent._hours_chain(item, None, None, search_hours, None))

    assert seen["city"] is None  # 哨兵没有下传给图商
    assert out is None  # 脏命中整条丢弃，地址不落到条目
    assert item.address is None
    assert item.poi_id is None


# ---------------- 建行即定城（H5 手填/粘贴/推荐建行） ----------------


class _LibStore:
    def __init__(self, rows, boom=False):
        self.rows = rows
        self.boom = boom

    def search_keyword(self, city, tokens, limit=20):
        if self.boom:
            raise RuntimeError("db down")
        return list(self.rows)


def test_create_city_resolved_from_library_when_unique(monkeypatch):
    import app.services.poi_details as pd

    store = _LibStore(
        [
            {"name": "陕西历史博物馆", "city": "西安", "location": (1, 2)},
            {"name": "陕西历史博物馆（临时展）", "city": "西安", "location": (1, 2)},
        ]
    )
    monkeypatch.setattr(pd, "get_poi_detail_store", lambda: store)

    from app.api.trip_items import _city_from_library

    assert _city_from_library("陕西历史博物馆") == "西安"


def test_create_city_left_empty_when_ambiguous_or_unavailable(monkeypatch):
    import app.services.poi_details as pd
    from app.api.trip_items import _city_from_library

    two_cities = _LibStore(
        [
            {"name": "历史博物馆", "city": "西安"},
            {"name": "历史博物馆", "city": "成都"},
        ]
    )
    monkeypatch.setattr(pd, "get_poi_detail_store", lambda: two_cities)
    assert _city_from_library("历史博物馆") is None

    monkeypatch.setattr(pd, "get_poi_detail_store", lambda: _LibStore([], boom=True))
    assert _city_from_library("陕西历史博物馆") is None

    monkeypatch.setattr(pd, "get_poi_detail_store", lambda: _LibStore([]))
    assert _city_from_library("看熊猫") is None


# ---------------- 读口死行程闸：判活不可得不判死 ----------------


class _NoItinStore:
    """行程活库里查不到（未保存的会话行程就是这种）。"""

    def get(self, itinerary_id):
        return None


def _scheduled_row(svc, name="成都环球中心", itin="it-unsaved"):
    row = svc.create(name, source="chat", city="成都")
    svc.link_itinerary(row["id"], itin, force=True)
    svc.update(row["id"], status="scheduled", day=2)
    return svc.get(row["id"])


def test_list_items_without_device_never_flips_scheduled(monkeypatch):
    """07:08 事故态：无 X-Device-ID 的看板请求把两个已排期心愿打回心愿单。"""
    from app.api.trip_items import list_trip_items

    svc = TripItemService()
    row = _scheduled_row(svc)

    body = asyncio.run(
        list_trip_items(
            itinerary_id=None, x_device_id=None, service=svc, store=_NoItinStore()
        )
    )

    assert any(i["id"] == row["id"] for i in body["scheduled"])
    assert not any(i["id"] == row["id"] for i in body["wishlist"])
    assert svc.get(row["id"])["status"] == "scheduled"


def test_list_items_with_device_still_heals_dead_itinerary(monkeypatch):
    """反向锚：拿到本设备活表、行程确实不在册 → 照旧回心愿单（旧语义不丢）。"""
    import app.api.plan as plan_api

    class _Store:
        @staticmethod
        def live_itinerary_ids(device_id):
            return set()

    monkeypatch.setattr(plan_api, "get_plan_sessions", lambda: _Store())

    from app.api.trip_items import list_trip_items

    svc = TripItemService()
    row = _scheduled_row(svc)

    body = asyncio.run(
        list_trip_items(
            itinerary_id=None, x_device_id="dev-1", service=svc, store=_NoItinStore()
        )
    )

    assert any(i["id"] == row["id"] for i in body["wishlist"])
    assert svc.get(row["id"])["status"] == "wishlist"
