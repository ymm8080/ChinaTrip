"""存储层读穿透回归测试（2026-10-28 双进程/旁路写入事故）。

钉死两条事故链不再复发：
1. 脚本/另一端口进程写持久层后，本进程（内存冷启动在先）必须立刻读到
   新数据——PgItineraryStore.get 与 PersistentPlanSessionStore.get 均
   以持久层为读权威，内存只是 PG 不可达/库读失败时的兜底。
2. PG 读熔断后行为退化为旧内存语义（_pg_ok=False 兜底链不回归）。

全部离线（fake PG 会话工厂 + tmp SQLite），镜像 test_pg_state 的不出网纪律。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.models import Itinerary, ItineraryDay, ItinerarySnapshot, TripItem
from app.services.agent.plan import PlanSession
from app.services.itinerary import DayPlan, ItineraryPlan
from app.services.itinerary_store import ItineraryRecord
from app.services.pg_state import PgItineraryStore, PgTripItemService
from app.services.state_persist import (
    PersistentPlanSessionStore,
    SqliteStateBackend,
)

# ---------- fakes -----------------------------------------------------------


class _FakePG:
    """极小 PG 模拟：itineraries / itinerary_snapshots 两张 dict 表，
    多个 store 实例共享同一「库」，模拟多进程/旁路写入。"""

    def __init__(self) -> None:
        self.rows: dict = {}
        self.snaps: dict = {}
        self.days: list = []
        self.trip_rows: list = []

    def factory(self):
        return _FakeSession(self)


class _FakeSession:
    def __init__(self, db: _FakePG) -> None:
        self._db = db
        self._pending: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
        if model is Itinerary:
            return SimpleNamespace(all=lambda: list(self._db.rows.values()))
        if model is TripItem:
            return SimpleNamespace(all=lambda: list(self._db.trip_rows))
        if model is ItineraryDay:
            return SimpleNamespace(
                filter=lambda *a, **k: SimpleNamespace(delete=lambda: 0)
            )
        raise AssertionError(f"unexpected query model {model}")

    def get(self, model, uid):
        if model is Itinerary:
            return self._db.rows.get(uid)
        if model is ItinerarySnapshot:
            return self._db.snaps.get(uid)
        return None

    def add(self, obj):
        self._pending.append(obj)

    def commit(self):
        for obj in self._pending:
            if isinstance(obj, Itinerary):
                self._db.rows[obj.id] = obj
            elif isinstance(obj, ItinerarySnapshot):
                self._db.snaps[obj.id] = obj
            else:
                self._db.days.append(obj)
        self._pending = []


class _DeadSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
        from sqlalchemy.exc import OperationalError

        raise OperationalError("stmt", {}, Exception("no pg"))

    def get(self, model, uid):
        from sqlalchemy.exc import OperationalError

        raise OperationalError("stmt", {}, Exception("no pg"))


def _dead_factory():
    return _DeadSession()


def _record(device: str = "dev-1") -> ItineraryRecord:
    plan = ItineraryPlan(
        itinerary_id=f"it_{uuid4().hex}",
        cities=["上海", "杭州"],
        days=[
            DayPlan(day=1, base_city="上海", items=[]),
            DayPlan(day=2, base_city="杭州", items=[]),
        ],
    )
    return ItineraryRecord(
        itinerary_id=plan.itinerary_id,
        owner_device_id=device,
        plan=plan,
        created_at=datetime(2026, 10, 28, 4, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 28, 4, 0, 0, tzinfo=timezone.utc),
    )


# ---------- PgItineraryStore 读穿透 ----------------------------------------


def test_itinerary_get_sees_side_channel_write_from_cold_memory():
    db = _FakePG()
    writer = PgItineraryStore(db.factory)  # boot-load：库空
    reader = PgItineraryStore(db.factory)  # 另一进程：内存也是冷的
    record = _record()
    writer.put(record)
    # 旧实现：reader 内存里没有 → None（12:01 错快照事故的同型）
    fresh = reader.get(record.itinerary_id)
    assert fresh is not None
    assert fresh.owner_device_id == "dev-1"


def test_itinerary_list_by_owner_sees_side_channel_write():
    db = _FakePG()
    writer = PgItineraryStore(db.factory)
    reader = PgItineraryStore(db.factory)
    record = _record(device="dev-rt")
    writer.put(record)
    ids = {r.itinerary_id for r in reader.list_by_owner("dev-rt")}
    assert record.itinerary_id in ids


def test_itinerary_get_pg_down_falls_back_to_memory():
    store = PgItineraryStore(_dead_factory)
    assert store._pg_ok is False  # boot 熔断
    record = _record()
    store.put(record)  # 写穿失败被吞，内存仍生效（旧降级语义）
    assert store.get(record.itinerary_id) is not None


# ---------- PgTripItemService 读穿透（2026-10-31 看水利工程案） --------------
# 排期写在规划进程，看板进程（早启动/另一端口）此前内存权威永远看不到，
# 行程中心按行程过滤即丢行。读穿透后旁路写入/删除必须立即可见。


def _water_payload() -> dict:
    return {
        "id": uuid4().hex,
        "name": "看水利工程",
        "status": "scheduled",
        "source": "chat",
        "city": "成都",
        "day": 5,
        "position": 1.0,
        "itinerary_id": "it-c94803b8",
        "created_at": "2026-10-30T23:45:21+00:00",
        "updated_at": "2026-10-30T23:45:21+00:00",
    }


def test_trip_items_list_sees_side_channel_scheduled_row():
    db = _FakePG()
    board = PgTripItemService(db.factory)  # 看板进程：boot 时库空
    db.trip_rows = [SimpleNamespace(payload=_water_payload())]  # 规划进程排期落库
    scheduled = board.list_groups()["scheduled"]
    assert [i["name"] for i in scheduled] == ["看水利工程"]
    assert scheduled[0]["itinerary_id"] == "it-c94803b8"


def test_trip_items_list_drops_side_channel_deleted_row():
    db = _FakePG()
    board = PgTripItemService(db.factory)
    db.trip_rows = [SimpleNamespace(payload=_water_payload())]
    assert board.list_groups()["scheduled"]
    db.trip_rows = []  # 另一进程删除（防复活）
    assert board.list_groups()["scheduled"] == []


def test_trip_items_list_pg_down_falls_back_to_memory():
    db = _FakePG()
    mode = {"dead": False}

    def factory():
        return _DeadSession() if mode["dead"] else _FakeSession(db)

    board = PgTripItemService(factory)
    payload = _water_payload()
    db.trip_rows = [SimpleNamespace(payload=payload)]
    assert board.list_groups()["scheduled"]  # 刷新进内存
    mode["dead"] = True
    groups = board.list_groups()  # 熔断 → 旧内存兜底，行不丢
    assert board._pg_ok is False
    assert [i["name"] for i in groups["scheduled"]] == ["看水利工程"]


# ---------- PersistentPlanSessionStore 读穿透 -------------------------------


def _session_store_pair(tmp_path):
    backend = SqliteStateBackend(str(tmp_path / "state.db"))
    writer = PersistentPlanSessionStore(backend)
    reader = PersistentPlanSessionStore(backend)  # 构造在写入之前：内存冷
    return writer, reader


def _plan_session(sid: str = "s-rt") -> PlanSession:
    return PlanSession(
        session_id=sid,
        device_id="dev-1",
        cities=["上海"],
        days=2,
        state="ready",
        plan=None,
        assumptions=[],
        history=[],
    )


def test_session_get_sees_side_channel_write_from_cold_memory(tmp_path):
    writer, reader = _session_store_pair(tmp_path)
    writer.save(_plan_session())
    # 旧实现：reader 内存没有 → None（脚本写库/uvicorn 不知情事故同型）
    got = reader.get("s-rt", device_id="dev-1")
    assert got is not None
    assert got.cities == ["上海"]


def test_session_get_enforces_device_scope_on_fresh_row(tmp_path):
    writer, reader = _session_store_pair(tmp_path)
    writer.save(_plan_session())
    assert reader.get("s-rt", device_id="dev-other") is None


def test_session_get_missing_stays_none(tmp_path):
    _, reader = _session_store_pair(tmp_path)
    assert reader.get("s-absent", device_id="dev-1") is None
