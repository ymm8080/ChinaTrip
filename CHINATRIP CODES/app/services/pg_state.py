"""H5 行程状态 PG 写穿（B 期「行程保存即入库」，2026-10-25）。

背景：H5 行程域此前只写 SQLite 状态库（state_persist.PersistentItineraryStore），
PG 的 itineraries/itinerary_snapshots/trip_items 三表自 alembic 0001 建表以来
0 行——天气巡检 trip_cities 查 PG 永远为空。本模块是行程库迁 PG 的写穿层：

* 内存 dict 仍是热路径（单 uvicorn 进程，itinerary-store 同款理由）；
* put/create/update/delete 写穿 PG（alembic 0015 加的 plan/owner/share/payload 列）；
* PG 不可达时熔断降级为纯内存（_pg_ok=False），服务不中断，恢复需重启进程；
*cities / itinerary_days.base_city / trip_items.city 三个投影列随写随更，
  weather.trip_cities 从此看到真实行程城市。

数据搬迁用 ops/migrate_h5_state_to_pg.py（幂等，SQLite 文件保留为备份）。
"""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import Itinerary, ItineraryDay, ItinerarySnapshot, TripItem
from app.services.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryRecord,
    Snapshot,
)
from app.services.trip_items import STATUS_WISHLIST, TripItemService

logger = logging.getLogger(__name__)

# 跨进程心愿查重锁（2026-10-28）：:8000 与 :8443 两个 uvicorn 进程共写一张
# trip_items 表，各自内存查重互相看不见 → 同名心愿重复入库（用户实报心愿单
# 多条 西湖）。任意 bigint 常量即可，全库仅此一处使用。
_TRIP_ITEMS_ADVISORY_KEY = 8633722


def _pg_uuid(stored_id: str | None, prefix: str = "") -> uuid_mod.UUID | None:
    """'it_<hex>' / 'snap_<hex>' / 裸 32-hex → UUID；不合式返回 None。

    trip_items 的 id/poi_id/booking_id 在 dict 里是自由字符串（poi_id 常是
    高德 B000A8UIN8 这类源 ID），只有真 UUID 才落 FK 列，原值始终在 payload。
    """
    if not stored_id:
        return None
    raw = (
        stored_id[len(prefix) :]
        if prefix and stored_id.startswith(prefix)
        else stored_id
    )
    try:
        return uuid_mod.UUID(hex=raw)
    except (ValueError, AttributeError):
        return None


def _pg_uuid_loose(stored_id: str | None, prefix: str = "") -> uuid_mod.UUID | None:
    """PG 主键代理：先按 hex UUID 解；不合式（历史短 id，如 it-9a90fb0f——
    实测 320 条里 317 条）→ uuid5 确定性代理键，重跑幂等。业务 id 原样
    留在 plan/payload 文档里（内存与 API 都用业务 id），PG PK 只是内部
    代理。FK 列仍用严格版 _pg_uuid——代理键不进外键，避免悬挂引用。"""
    strict = _pg_uuid(stored_id, prefix)
    if strict is not None or not stored_id:
        return strict
    return uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, f"chinatrip:{stored_id}")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _trip_title(cities: list[str]) -> str | None:
    if not cities:
        return None
    return " → ".join(cities)[:200]


def record_to_row_values(record: ItineraryRecord) -> dict:
    """ItineraryRecord → itineraries 行投影（纯函数，单测口径）。"""
    return {
        "id": _pg_uuid_loose(record.itinerary_id, "it_"),
        "cities": list(record.plan.cities or []),
        "title": _trip_title(record.plan.cities or []),
        "working_sync_version": record.working_sync_version,
        "active_snapshot_id": (
            _pg_uuid_loose(record.active_snapshot_id, "snap_")
            if record.active_snapshot_id
            else None
        ),
        "owner_device_id": record.owner_device_id,
        "owner_account_id": record.owner_account_id,
        "share_enabled": bool(record.share_enabled),
        "share_token": record.share_token,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "plan": record.model_dump(mode="json"),
    }


def snapshot_to_row_values(snapshot: Snapshot, itinerary_uuid: uuid_mod.UUID) -> dict:
    """Snapshot → itinerary_snapshots 行投影；plan 列存冻结的 ItineraryPlan 文档。"""
    return {
        "id": _pg_uuid_loose(snapshot.snapshot_id, "snap_"),
        "itinerary_id": itinerary_uuid,
        "name": snapshot.name,
        "note": snapshot.note,
        "sync_version": snapshot.sync_version,
        "created_at": snapshot.created_at,
        "plan": snapshot.plan.model_dump(mode="json"),
    }


def item_to_row_values(item: dict) -> dict:
    """trip-center 条目 dict → trip_items 行投影（列化字段 + payload 全量）。"""
    return {
        "id": _pg_uuid_loose(item.get("id")),
        "itinerary_id": _pg_uuid(item.get("itinerary_id")),
        "name": item.get("name"),
        "city": item.get("city"),
        "note": item.get("note"),
        "status": item.get("status") or STATUS_WISHLIST,
        "source": item.get("source") or "manual",
        "poi_id": _pg_uuid(item.get("poi_id")),
        "day": item.get("day"),
        "position": item.get("position"),
        "address": (item.get("address") or None),
        "opening_hours": (item.get("opening_hours") or None),
        "booking_id": _pg_uuid(item.get("booking_id")),
        "created_at": _parse_iso(item.get("created_at")),
        "updated_at": _parse_iso(item.get("updated_at")),
        "payload": dict(item),
    }


class PgItineraryStore(InMemoryItineraryStore):
    """内存 dict 热路径 + PG 写穿（put/delete 落 itineraries 三表）。

    _pg_ok=False（PG 不可达/启动熔断）时退化为纯内存 store——API 行为
    与 InMemoryItineraryStore 完全一致，恢复靠重启进程重试 boot-load。
    """

    def __init__(self, session_factory) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._pg_ok = True
        self._boot_load()

    def _boot_load(self) -> None:
        try:
            self._pg_reload()
        except OperationalError as exc:
            self._pg_ok = False
            logger.warning("pg_state: PG 不可达，行程 store 降级纯内存: %s", exc)

    # ---- 读穿透（2026-10-28 双进程事故重构）：PG 是读权威 -----------------
    # 内存层降级为「PG 不可达兜底 + 写穿缓存」。get/list 每次回库取新，
    # 旁路写入（运维脚本 / 另一端口进程 :8000/:8443）立即可见，save 端点
    # 不再冻结到陈旧内存（当天 12:01 错快照事故根治）。

    def _pg_reload(self) -> None:
        """全量重载进内存（boot 与 list 读穿透共用）。"""
        records: dict[str, ItineraryRecord] = {}
        with self._session_factory() as session:
            for row in session.query(Itinerary).all():
                if not row.plan:
                    continue
                try:
                    record = ItineraryRecord.model_validate(row.plan)
                except Exception:
                    logger.warning(
                        "pg_state: itinerary %s payload 解析失败，跳过", row.id
                    )
                    continue
                records[record.itinerary_id] = record
        self._records = records

    def _try_refresh(self) -> None:
        if not self._pg_ok:
            return
        try:
            self._pg_reload()
        except OperationalError as exc:
            self._pg_ok = False
            logger.warning("pg_state: PG 读降级（纯内存兜底）: %s", exc)
        except Exception:
            logger.warning("pg_state: PG 读穿透失败，本轮用内存", exc_info=True)

    def _pg_get(self, itinerary_id: str) -> ItineraryRecord | None | object:
        uid = _pg_uuid_loose(itinerary_id, "it_")
        if uid is None:
            return None
        with self._session_factory() as session:
            row = session.get(Itinerary, uid)
            if row is None or not row.plan:
                return None
            return ItineraryRecord.model_validate(row.plan)

    def get(self, itinerary_id: str) -> ItineraryRecord | None:
        if self._pg_ok:
            try:
                record = self._pg_get(itinerary_id)
            except OperationalError as exc:
                self._pg_ok = False
                logger.warning("pg_state: PG 读降级（纯内存兜底）: %s", exc)
            except Exception:
                logger.warning(
                    "pg_state: 行程 %s 读穿透失败，本轮用内存",
                    itinerary_id,
                    exc_info=True,
                )
            else:
                if record is not None:
                    self._records[itinerary_id] = record
                return record
        return super().get(itinerary_id)

    def list_by_owner(self, owner_device_id: str) -> list[ItineraryRecord]:
        self._try_refresh()
        return super().list_by_owner(owner_device_id)

    def list_by_account(self, username: str) -> list[ItineraryRecord]:
        self._try_refresh()
        return super().list_by_account(username)

    def find_by_share_token(self, token: str) -> ItineraryRecord | None:
        self._try_refresh()
        return super().find_by_share_token(token)

    def list_all(self) -> list[ItineraryRecord]:
        self._try_refresh()
        return super().list_all()

    def put(self, record: ItineraryRecord) -> None:
        super().put(record)
        self._write_pg(record)

    def delete(self, itinerary_id: str) -> bool:
        removed = super().delete(itinerary_id)
        if removed and self._pg_ok:
            uid = _pg_uuid(itinerary_id, "it_")
            if uid is not None:
                try:
                    with self._session_factory() as session:
                        session.query(ItineraryDay).filter(
                            ItineraryDay.itinerary_id == uid
                        ).delete()
                        session.query(ItinerarySnapshot).filter(
                            ItinerarySnapshot.itinerary_id == uid
                        ).delete()
                        session.query(Itinerary).filter(Itinerary.id == uid).delete()
                        session.commit()
                except Exception as exc:
                    logger.warning(
                        "pg_state: 行程 %s 删除写穿失败: %s", itinerary_id, exc
                    )
        return removed

    def _write_pg(self, record: ItineraryRecord) -> None:
        if not self._pg_ok:
            return
        values = record_to_row_values(record)
        uid = values["id"]
        if uid is None:
            raise ValueError(f"itinerary_id 不合式: {record.itinerary_id}")
        try:
            with self._session_factory() as session:
                row = session.get(Itinerary, uid)
                if row is None:
                    row = Itinerary(id=uid)
                    session.add(row)
                for key, val in values.items():
                    setattr(row, key, val)
                # 快照 immutable：按 PK insert-if-absent
                for snap in record.snapshots:
                    sv = snapshot_to_row_values(snap, uid)
                    if sv["id"] is None or session.get(ItinerarySnapshot, sv["id"]):
                        continue
                    session.add(ItinerarySnapshot(**sv))
                # 工作副本日维度：先清后插（PG UNIQUE 里 NULL 不去重，直接
                # upsert 会堆重复行）；snapshot_id IS NULL = 工作副本约定
                session.query(ItineraryDay).filter(
                    ItineraryDay.itinerary_id == uid,
                    ItineraryDay.snapshot_id.is_(None),
                ).delete()
                for day in record.plan.days:
                    session.add(
                        ItineraryDay(
                            id=uuid_mod.uuid4(),
                            itinerary_id=uid,
                            snapshot_id=None,
                            day=day.day,
                            base_city=day.base_city,
                        )
                    )
                session.commit()
        except OperationalError as exc:
            self._pg_ok = False
            logger.warning("pg_state: PG 写穿熔断（降级纯内存）: %s", exc)
        except Exception as exc:
            logger.warning("pg_state: 行程 %s 写穿失败: %s", record.itinerary_id, exc)


class PgTripItemService(TripItemService):
    """trip-center 条目内存权威 + PG 写穿（混合列 + payload 全量）。

    去重/状态机/list_groups 语义全部继承基类；本类只负责落库。FK 列
    （itinerary_id/poi_id/booking_id）仅当值能解析成 UUID 时写入，
    IntegrityError（FK 目标不存在）回退清空 FK 列重试一次——dict 里这些
    字段是自由字符串，原值永远安全地存在 payload JSONB 里。
    """

    def __init__(self, session_factory) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._pg_ok = True
        self._boot_load()

    def _boot_load(self) -> None:
        try:
            with self._session_factory() as session:
                for row in session.query(TripItem).all():
                    payload = row.payload
                    if isinstance(payload, dict) and payload.get("id"):
                        self._items[str(payload["id"])] = payload
        except OperationalError as exc:
            self._pg_ok = False
            logger.warning("pg_state: PG 不可达，trip items 降级纯内存: %s", exc)

    def create(self, name: str, *, source: str, **kwargs) -> dict:
        """跨进程幂等创建（2026-10-28 用户报告心愿单多条 西湖）：:8000 与
        :8443 两个 uvicorn 进程共写一张 trip_items 表，各自内存查重互相看
        不见 → 同名心愿各插一行。改为在 PG advisory 事务锁内查重（回灌基
        类 _find_duplicate 谓词本体，无 SQL 镜像）+ 未命中才插入，两进程
        在该锁上
        串行化；命中即回灌内存并返回既有行。PG 不可达时熔断降级为纯内存
        语义（与 update/delete 一致）。"""
        if not self._pg_ok:
            return super().create(name, source=source, **kwargs)
        try:
            with self._session_factory() as session, session.begin():
                session.execute(
                    text("select pg_advisory_xact_lock(:key)"),
                    {"key": _TRIP_ITEMS_ADVISORY_KEY},
                )
                existing = self._db_find_duplicate(session, name, source, kwargs)
                if existing is not None:
                    payload = dict(existing)
                    # 与基类 create 的补空位语义一致（第二次带更全信息）。
                    self._enrich_duplicate(
                        payload,
                        name=name,
                        note=kwargs.get("note"),
                        city=kwargs.get("city"),
                        poi_id=kwargs.get("poi_id"),
                        address=kwargs.get("address"),
                        opening_hours=kwargs.get("opening_hours"),
                        now=kwargs.get("now"),
                    )
                    self._items[str(payload["id"])] = payload
                    self._write_through(payload["id"])
                    logger.info(
                        "trip_item_deduplicated_pg id=%s name=%s",
                        payload["id"],
                        payload.get("name"),
                    )
                    return payload
                item = super().create(name, source=source, **kwargs)
                values = item_to_row_values(item)
                if values["id"] is not None:
                    self._insert_on(session, values)
                return item
        except OperationalError as exc:
            self._pg_ok = False
            logger.warning("pg_state: PG 不可达，trip items 降级纯内存: %s", exc)
            return super().create(name, source=source, **kwargs)

    def _db_find_duplicate(
        self, session, name: str, source: str, kwargs: dict
    ) -> dict | None:
        """advisory 锁内拉取库内活跃行，回灌基类 _find_duplicate 谓词判定。
        2026-10-28 收口：谓词单一实现——SQL 镜像版曾与基类不同步（patch55
        参数自比较恒真事故），规范化/双向包含等模糊逻辑也不该在 SQL 里重
        写一份。表为几十行级、创建低频，全量拉取代价可忽略；PG 故障期的
        纯内存行仍由 super().create() 的内存查重兜底。"""
        rows = session.execute(
            text(
                "SELECT payload FROM trip_items"
                " WHERE status <> 'unwanted'"
                " ORDER BY created_at ASC NULLS LAST"
            )
        ).all()
        items = []
        for row in rows:
            payload = row[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, dict) and payload.get("id"):
                items.append(payload)
        return self._find_duplicate(
            name,
            source=source,
            itinerary_id=kwargs.get("itinerary_id"),
            city=kwargs.get("city"),
            poi_id=kwargs.get("poi_id"),
            items=items,
        )

    def _insert_on(self, session, values: dict) -> None:
        """advisory 锁内同事务落库。FK 目标不存在时清空 FK 列在 savepoint
        里重试一次（外层事务与锁不受影响，原值仍在 payload）；其余写失败
        仅告警——内存条目保留，降级语义与 _write_through 一致。"""
        try:
            with session.begin_nested():
                session.add(TripItem(**values))
        except IntegrityError:
            for fk in ("itinerary_id", "poi_id", "booking_id"):
                values[fk] = None
            try:
                with session.begin_nested():
                    session.add(TripItem(**values))
            except Exception as exc:
                logger.warning(
                    "pg_state: 条目 %s 锁内落库失败(FK 回退): %s",
                    values["id"],
                    exc,
                )
        except OperationalError as exc:
            self._pg_ok = False
            logger.warning("pg_state: PG 写穿熔断（trip items 降级纯内存）: %s", exc)
        except Exception as exc:
            logger.warning("pg_state: 条目 %s 锁内落库失败: %s", values["id"], exc)

    def update(self, item_id: str, **kwargs) -> dict:
        item = super().update(item_id, **kwargs)
        self._write_through(item_id)
        return item

    def delete(self, item_id: str) -> None:
        super().delete(item_id)
        if not self._pg_ok:
            return
        try:
            with self._session_factory() as session:
                uid = _pg_uuid(item_id)
                if uid is not None:
                    session.query(TripItem).filter(TripItem.id == uid).delete()
                else:
                    session.query(TripItem).filter(
                        TripItem.payload["id"].astext == item_id
                    ).delete()
                session.commit()
        except Exception as exc:
            logger.warning("pg_state: 条目 %s 删除写穿失败: %s", item_id, exc)

    def import_item(self, payload: dict) -> bool:
        """迁移脚本入口：整条 dict 入内存并写穿（幂等 upsert by id）。"""
        item_id = str(payload.get("id") or "")
        if not item_id:
            return False
        self._items[item_id] = payload
        self._write_through(item_id)
        return self._pg_ok

    def _write_through(self, item_id: str) -> None:
        if not self._pg_ok:
            return
        item = self._items.get(item_id)
        if item is None:
            return
        values = item_to_row_values(item)
        if values["id"] is None:
            logger.warning("pg_state: 条目 id 不合式，跳过落库: %s", item_id)
            return
        try:
            self._upsert(values)
        except IntegrityError:
            # FK 目标不存在（poi_id/itinerary_id 指向 PG 里没有的行）——
            # 清空 FK 列重试一次，原值仍在 payload
            for fk in ("itinerary_id", "poi_id", "booking_id"):
                values[fk] = None
            try:
                self._upsert(values)
            except Exception as exc:
                logger.warning("pg_state: 条目 %s 写穿失败(FK 回退): %s", item_id, exc)
        except OperationalError as exc:
            self._pg_ok = False
            logger.warning("pg_state: PG 写穿熔断（trip items 降级纯内存）: %s", exc)
        except Exception as exc:
            logger.warning("pg_state: 条目 %s 写穿失败: %s", item_id, exc)

    def _upsert(self, values: dict) -> None:
        with self._session_factory() as session:
            row = session.get(TripItem, values["id"])
            if row is None:
                row = TripItem(id=values["id"])
                session.add(row)
            for key, val in values.items():
                setattr(row, key, val)
            session.commit()
