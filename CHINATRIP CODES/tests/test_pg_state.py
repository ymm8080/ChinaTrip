"""pg_state 映射纯函数 + PG 不可达降级测试（CI 无 PostgreSQL，不出网）."""

import contextlib
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy.exc import OperationalError

from app.services.itinerary import DayPlan, ItineraryPlan
from app.services.itinerary_store import ItineraryRecord, Snapshot
from app.services.pg_state import (
    PgItineraryStore,
    PgTripItemService,
    _pg_uuid,
    _pg_uuid_loose,
    item_to_row_values,
    record_to_row_values,
    snapshot_to_row_values,
)


def _plan(itinerary_id: str | None = None) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id=itinerary_id or f"it_{uuid4().hex}",
        cities=["上海", "杭州"],
        days=[
            DayPlan(day=1, base_city="上海", items=[]),
            DayPlan(day=2, base_city="杭州", items=[]),
        ],
        assumptions=[],
        start_date="2026-10-25",
    )


def _record() -> ItineraryRecord:
    plan = _plan()
    return ItineraryRecord(
        itinerary_id=plan.itinerary_id,
        owner_device_id="dev-1",
        plan=plan,
        created_at=datetime(2026, 10, 25, 8, 0, 0),
        updated_at=datetime(2026, 10, 25, 8, 0, 0),
    )


class _DeadSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
        raise OperationalError("stmt", {}, Exception("no pg"))


class _DeadFactory:
    def __call__(self):
        return _DeadSession()


# --- 纯映射 -------------------------------------------------------------------


def test_pg_uuid_prefix_and_bare_hex():
    h = uuid4().hex
    assert _pg_uuid(f"it_{h}", "it_") == UUID(hex=h)
    assert _pg_uuid(f"snap_{h}", "snap_") == UUID(hex=h)
    assert _pg_uuid(h) == UUID(hex=h)  # trip item id 是裸 hex


def test_pg_uuid_rejects_free_strings():
    # 高德源 POI ID / 自由字符串 / 空——都不落 FK 列
    assert _pg_uuid("B000A8UIN8") is None
    assert _pg_uuid("it_" + uuid4().hex) is None  # 前缀没剥（调用方给错 prefix）
    assert _pg_uuid(None) is None
    assert _pg_uuid("") is None


def test_pg_uuid_loose_deterministic_for_legacy_ids():
    # 历史短 id（实测 320 条里 317 条是 it-xxxxxxxx 形态）→ uuid5 代理键，
    # 同 id 同键（幂等重跑），不同 id 不同键
    legacy = "it-9a90fb0f"
    assert _pg_uuid_loose(legacy, "it_") == _pg_uuid_loose(legacy, "it_")
    assert _pg_uuid_loose("it-492455a7", "it_") != _pg_uuid_loose(legacy, "it_")
    # 合式 UUID 走严格解析，不进 uuid5 分支
    h = uuid4().hex
    assert _pg_uuid_loose(f"it_{h}", "it_") == UUID(hex=h)
    assert _pg_uuid_loose(None) is None


def test_record_to_row_values_and_boot_round_trip():
    record = _record()
    values = record_to_row_values(record)
    assert values["id"] == UUID(hex=record.itinerary_id[3:])
    assert values["cities"] == ["上海", "杭州"]  # 喂 weather.trip_cities
    assert values["title"] == "上海 → 杭州"
    assert values["owner_device_id"] == "dev-1"
    assert values["share_enabled"] is False
    # plan 列存 ItineraryRecord 整体文档；boot-load 靠它复原
    assert ItineraryRecord.model_validate(values["plan"]) == record


def test_snapshot_to_row_values_freezes_plan():
    record = _record()
    snapshot = Snapshot(
        snapshot_id=f"snap_{uuid4().hex}",
        name="v1",
        note=None,
        sync_version=1,
        plan=record.plan,
        created_at=datetime(2026, 10, 25, 9, 0, 0),
    )
    values = snapshot_to_row_values(snapshot, UUID(hex=record.itinerary_id[3:]))
    assert values["id"] == UUID(hex=snapshot.snapshot_id[5:])
    assert values["itinerary_id"] == UUID(hex=record.itinerary_id[3:])
    assert values["plan"]["cities"] == ["上海", "杭州"]
    assert values["plan"]["start_date"] == "2026-10-25"


def test_item_to_row_values_keeps_free_string_ids_in_payload():
    item = {
        "id": uuid4().hex,
        "itinerary_id": f"it_{uuid4().hex}",
        "name": "蜀风雅韵",
        "city": "成都",
        "note": "来自聊天",
        "status": "wishlist",
        "source": "chat",
        "poi_id": "B000A8UIN8",  # 高德源 ID，不是 UUID
        "address": "四川省川剧院",
        "opening_hours": None,
        "day": None,
        "position": None,
        "booking_id": None,
        "created_at": "2026-10-25T08:00:00+00:00",
        "updated_at": "2026-10-25T08:00:00+00:00",
    }
    values = item_to_row_values(item)
    assert values["poi_id"] is None  # 自由字符串不落 FK 列
    assert values["itinerary_id"] is None  # it_ 前缀没剥，不硬转
    assert values["status"] == "wishlist"
    assert values["created_at"] is not None and values["created_at"].year == 2026
    assert values["payload"] == item  # 原值全量在 payload


# --- PG 不可达降级（CI / PG 宕机路径）------------------------------------------


def test_itinerary_store_degrades_to_memory_without_pg():
    store = PgItineraryStore(_DeadFactory())
    assert store._pg_ok is False
    record = _record()
    store.put(record)  # 不抛，内存生效
    assert store.get(record.itinerary_id) is record
    assert store.list_all() == [record]
    assert store.list_by_owner("dev-1") == [record]


def test_trip_items_degrade_to_memory_without_pg():
    svc = PgTripItemService(_DeadFactory())
    assert svc._pg_ok is False
    item = svc.create("外滩", source="manual", city="上海")
    assert item["name"] == "外滩"
    assert svc.list_groups()["wishlist"][0]["name"] == "外滩"
    svc.update(item["id"], status="unwanted")
    assert svc.list_groups()["unwanted"][0]["id"] == item["id"]
    assert svc.list_groups()["wishlist"] == []


def test_import_item_memory_fallback_without_pg():
    svc = PgTripItemService(_DeadFactory())
    item_id = uuid4().hex
    # 返回 False = PG 写穿不可用，但内存已收
    assert (
        svc.import_item({"id": item_id, "name": "灵隐寺", "status": "wishlist"})
        is False
    )
    assert svc.get(item_id)["name"] == "灵隐寺"


# --- 2026-10-28 跨进程查重（advisory 锁内 SQL 查重 + 命中不重插） -------------


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _TxSession:
    """boot 段 query()→空表；create 段 execute() 按 SQL 分流（锁语句返回
    空、查重语句返回预置命中行）。"""

    def __init__(self, dup_payload=None):
        self.dup_payload = dup_payload
        self.executed = []
        self.inserted = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def begin(self):
        return self

    def begin_nested(self):
        return contextlib.nullcontext()

    def query(self, model):
        return SimpleNamespace(all=lambda: [])

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params))
        if "pg_advisory_xact_lock" in sql:
            return _FakeResult([])
        return _FakeResult([(self.dup_payload,)] if self.dup_payload else [])

    def add(self, row):
        self.inserted.append(row)


class _TxFactory:
    def __init__(self, dup_payload=None):
        self.dup_payload = dup_payload
        self.sessions = []

    def __call__(self):
        session = _TxSession(self.dup_payload)
        self.sessions.append(session)
        return session


def _wish_payload(name="西湖", city="杭州"):
    return {
        "id": "abc123def456abc123def456abc12345",
        "name": name,
        "city": city,
        "status": "wishlist",
        "source": "paste",
        "itinerary_id": "it-1",
        "poi_id": None,
        "note": None,
        "day": None,
        "position": None,
        "address": None,
        "opening_hours": None,
        "booking_id": None,
        "created_at": "2026-10-28T08:00:00+00:00",
        "updated_at": "2026-10-28T08:00:00+00:00",
    }


def test_pg_create_hit_returns_other_process_row_without_reinsert():
    factory = _TxFactory(dup_payload=_wish_payload())
    svc = PgTripItemService(factory)
    item = svc.create("西湖", source="chat", itinerary_id="it-1", city=None)
    assert item["id"] == "abc123def456abc123def456abc12345"
    assert svc._items[item["id"]]["name"] == "西湖"  # 命中行回灌内存
    writer = factory.sessions[1]
    assert writer.inserted == []  # 不重插
    assert any("pg_advisory_xact_lock" in sql for sql, _ in writer.executed)


def test_pg_create_miss_inserts_inside_locked_transaction():
    factory = _TxFactory()
    svc = PgTripItemService(factory)
    item = svc.create("西湖", source="paste", itinerary_id="it-1", city="杭州")
    assert item["status"] == "wishlist"
    writer = factory.sessions[1]
    assert len(writer.inserted) == 1
    assert writer.inserted[0].name == "西湖"
    assert any("pg_advisory_xact_lock" in sql for sql, _ in writer.executed)


def test_pg_create_hit_on_rephrased_variant_shares_base_predicate():
    """2026-10-28 变脸补报：库内 变脸表演（川剧），新提交 看变脸 —— 基类
    谓词的规范化匹配收口，命中不重插，别名入 note。"""
    payload = _wish_payload(name="变脸表演（川剧）", city="成都")
    factory = _TxFactory(dup_payload=payload)
    svc = PgTripItemService(factory)
    item = svc.create("看变脸", source="chat", itinerary_id="it-1", city="成都")
    assert item["id"] == payload["id"]
    assert item["note"] == "别名：看变脸"
    writer = factory.sessions[1]
    assert writer.inserted == []
