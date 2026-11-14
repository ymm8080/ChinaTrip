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
from datetime import date, datetime, time, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import Itinerary, ItineraryDay, ItinerarySnapshot, TripItem
from app.services.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryRecord,
    Snapshot,
)
from app.services.trip_changes import trip_header_fields
from app.services.trip_items import (
    STATUS_BOOKED,
    STATUS_WISHLIST,
    InvalidTransitionError,
    NotFoundError,
    TripItemService,
)

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


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _parse_time(value: object) -> time | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.timetz().replace(tzinfo=None)
    raw = str(value)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).timetz().replace(tzinfo=None)
    except ValueError:
        return None


def _wish_source_column(raw: str | None) -> str:
    """心愿单 SOURCE 列归一（2026-11-13 用户拍板：manual / conversation）。

    payload 保留原始来源（chat/paste/agent_recommend…）供状态机判定。
    """
    value = (raw or "manual").strip()
    if value in ("chat", "conversation"):
        return "conversation"
    if value in ("manual", "paste"):
        return "manual"
    return value


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
        # 2026-11-13（用户拍板 HEADER 列）：随每次 put 同步
        **trip_header_fields(record.plan),
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
    """trip-center 条目 dict → trip_items 行投影（列化字段 + payload 全量）。

    itinerary_id 用 loose 代理（2026-10-31 看水利工程案）：业务 id 是
    it-<8hex> 短格式，严格版解析为 None → 行程明明绑上了（payload 里有）
    列里却是 NULL，重启回灌/跨进程按行程过滤全丢。loose 与 itineraries
    行主键（record_to_row_values）同源，FK 可 JOIN；FK 目标不存在时由
    _insert_on/_write_through 的 IntegrityError 回退清列兜底。
    """
    return {
        "id": _pg_uuid_loose(item.get("id")),
        "itinerary_id": _pg_uuid_loose(item.get("itinerary_id"), "it_"),
        # 2026-11-13 数据库事实化：业务行程号与设备归属都进列（挂靠可查）
        "itinerary_ref": (item.get("itinerary_id") or None),
        "owner_device_id": (item.get("owner_device_id") or None),
        # 心愿单数据库字段（2026-11-13 拍板）
        "created_by": (item.get("created_by") or item.get("owner_device_id") or None),
        "arranged": (item.get("status") or "") in ("scheduled", "booked"),
        "exclusion_flag": bool(item.get("exclusion_flag"))
        or (item.get("status") or "") == "unwanted",
        "deletion_flag": bool(item.get("deletion_flag")),
        "deletion_date": _parse_date(item.get("deletion_date")),
        "deletion_time": _parse_time(item.get("deletion_time")),
        "deleted_by": (item.get("deleted_by") or None),
        "kind": (item.get("kind") or None),
        "duration_minutes": item.get("duration_minutes"),
        "must_visit": bool(item.get("must_visit")),
        "pinned": bool(item.get("pinned")),
        "tier": item.get("tier"),
        "site_rank": item.get("site_rank"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "planned_date": _parse_date(item.get("planned_date")),
        "start_time": _parse_time(item.get("start_time")),
        "end_time": _parse_time(item.get("end_time")),
        "rain_ok": (item.get("rain_ok") or None),
        "raw_command": (item.get("raw_command") or None),
        "name": item.get("name"),
        "city": item.get("city"),
        "note": item.get("note"),
        "status": item.get("status") or STATUS_WISHLIST,
        "source": _wish_source_column(item.get("source")),
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
                if not row.plan or row.is_deleted:
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
            # 2026-11-13 软删：头表 is_deleted 的行视为不存在（记录仍留审计）
            if row is None or not row.plan or row.is_deleted:
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
        if not self._pg_ok:
            return removed
        # 与 _write_pg 同款 loose 代理键（2026-10-30 删除复活事故）：存量
        # 行程业务 id 是 it-<8hex> 短格式，严格版解析为 None 会整段跳过
        # PG 删除——API 照样 204/「已删除」toast，下次 list 读穿透又把
        # 行从 PG 复活。键必须与写库一致。
        uid = _pg_uuid_loose(itinerary_id, "it_")
        if uid is None:
            return removed
        try:
            with self._session_factory() as session:
                # 2026-11-13（删行程后行程复活/排期没回心愿单）：trip_items
                # 的 itinerary_id 是指向 itineraries 的外键——释放后残留死
                # 行程 id 时 DELETE 撞 FK，异常被吞、接口照样 204，下次
                # list 又把行程读回来。删前统一摘引用（列 + payload 同源
                # 清空），跨进程/未回灌内存的行也被覆盖。
                session.execute(
                    text(
                        "UPDATE trip_items t"
                        " SET itinerary_id = NULL,"
                        " payload = (COALESCE(t.payload, '{}'::jsonb)"
                        " - 'itinerary_id')"
                        " || jsonb_build_object("
                        " 'trip_name',"
                        " COALESCE(i.title, array_to_string(i.cities, ' → ')))"
                        " FROM itineraries i"
                        " WHERE i.id = :uid AND t.itinerary_id = :uid"
                    ),
                    {"uid": uid},
                )
                # 2026-11-13 软删（用户拍板 DELETION FLAG）：明细/快照留审计，
                # 读口按 itineraries.is_deleted 过滤——不再物理删三表。
                # 2026-11-13（用户拍板 trip HEADER 带 DELETION FLAG）：
                # 改为软删——行留审计，读口按 is_deleted 过滤；明细/快照
                # 保留可回放（change log 另有逐次 diff）。
                now = datetime.now(timezone.utc)
                result = session.execute(
                    text(
                        "UPDATE itineraries"
                        " SET is_deleted = TRUE,"
                        " deleted_at = :now, updated_at = :now"
                        " WHERE id = :uid AND is_deleted = FALSE"
                    ),
                    {"uid": uid, "now": now},
                )
                rowcount = getattr(result, "rowcount", None)
                # 假库/驱动不给 rowcount 时按「SQL 无异常即成功」；真库用行数
                deleted = 1 if rowcount is None else rowcount
                session.commit()
                return removed or bool(deleted)
        except Exception as exc:
            logger.warning("pg_state: 行程 %s 删除写穿失败: %s", itinerary_id, exc)
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
    """trip-center 条目 PG 写穿 + list 读穿透（混合列 + payload 全量）。

    去重/状态机/list_groups 语义全部继承基类；本类负责落库与读权威。
    读穿透（2026-10-31 看水利工程案）：此前只有 itineraries 有读穿透，
    trip_items 内存权威——排期写在 A 进程（:8000 规划会话），B 进程
    （:8443 / 早于写入启动的进程）看板永远看不到，直到重启。现在
    list_groups 每次全量回灌 PG payload，旁路写入/跨进程删除立即可见；
    PG 不可达时熔断降级为纯内存（_pg_ok=False），行为同基类。FK 列
    （itinerary_id/poi_id/booking_id）仅当值能解析（含 loose 代理）时写入，
    IntegrityError（FK 目标不存在）回退清空 FK 列重试一次——dict 里这些
    字段是自由字符串，原值永远安全地存在 payload JSONB 里。
    """

    def __init__(self, session_factory) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._pg_ok = True
        self._boot_load()

    def _pg_reload_items(self) -> None:
        """全量回灌内存（boot 与 list 读穿透共用）；payload 为权威。

        2026-11-13 看板 500（KeyError: 'created_at'）：旧版 H5 迁移/
        旁路恢复脚本写库的 payload 协议不完整（可能没有 created_at，
        列里也是 NULL）。payload 缺失的投影列在此按列补齐，created_at
        最终退到 updated_at——下游 list_groups/去重不再裸取键。"""
        items: dict[str, dict] = {}
        with self._session_factory() as session:
            for row in session.query(TripItem).all():
                # 软删行（DELETION FLAG）永不回灌内存——看板/心愿单不显示
                if getattr(row, "deletion_flag", False):
                    continue
                payload = row.payload
                if not (isinstance(payload, dict) and payload.get("id")):
                    continue
                payload = dict(payload)
                for field in (
                    "name",
                    "city",
                    "note",
                    "status",
                    "source",
                    "day",
                    "position",
                    "address",
                    "opening_hours",
                    "owner_device_id",
                    "itinerary_ref",
                ):
                    if payload.get(field) is None:
                        value = getattr(row, field, None)
                        if value is not None:
                            payload[field] = value
                for field in ("created_at", "updated_at"):
                    if payload.get(field):
                        continue
                    value = getattr(row, field, None)
                    if value is None and field == "created_at":
                        value = row.updated_at
                    if value is not None:
                        payload[field] = value.isoformat()
                for field in (
                    "kind",
                    "duration_minutes",
                    "tier",
                    "site_rank",
                    "latitude",
                    "longitude",
                    "rain_ok",
                    "raw_command",
                ):
                    if payload.get(field) is None:
                        value = getattr(row, field, None)
                        if value is not None:
                            payload[field] = value
                for field in ("planned_date", "start_time", "end_time"):
                    if payload.get(field) is None:
                        value = getattr(row, field, None)
                        if value is not None:
                            payload[field] = value.isoformat()
                payload["must_visit"] = bool(getattr(row, "must_visit", False))
                payload["pinned"] = bool(getattr(row, "pinned", False))
                payload["created_by"] = payload.get("created_by") or getattr(
                    row, "created_by", None
                )
                payload["arranged"] = bool(getattr(row, "arranged", False))
                payload["exclusion_flag"] = bool(getattr(row, "exclusion_flag", False))
                items[str(payload["id"])] = payload
        self._items = items

    def _boot_load(self) -> None:
        try:
            self._pg_reload_items()
        except OperationalError as exc:
            self._pg_ok = False
            logger.warning("pg_state: PG 不可达，trip items 降级纯内存: %s", exc)

    def _try_refresh(self) -> None:
        if not self._pg_ok:
            return
        try:
            self._pg_reload_items()
        except OperationalError as exc:
            self._pg_ok = False
            logger.warning("pg_state: PG 读降级（trip items 纯内存兜底）: %s", exc)
        except Exception:
            logger.warning("pg_state: trip items 读穿透失败，本轮用内存", exc_info=True)

    def list_groups(
        self,
        itinerary_id: str | None = None,
        owner_device_id: str | None = None,
    ) -> dict:
        # 读穿透（PG 读权威）：看板/规划收口每次回库取新，跨进程排期立即可见。
        self._try_refresh()
        return super().list_groups(itinerary_id, owner_device_id)

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
                        source=source,
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
                " WHERE status <> 'unwanted' AND deletion_flag = false"
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
            # 2026-11-13 数据库事实化：查重同样按设备——别的设备的同名行
            # 不是同一条心愿（否则冒烟/别的浏览器会把用户的行动手合并）
            owner_device_id=kwargs.get("owner_device_id"),
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

    def release_itinerary(
        self,
        itinerary_id: str,
        *,
        now: datetime | None = None,
        actor: str | None = None,
    ) -> list[dict]:
        """跨进程释放（2026-11-13）：删行程可能落在没回灌内存的进程上
        （排期写在另一端口 / 另一实例）——内存里一条该行程的行都没有时先
        回库取权威，否则漏放的 scheduled 行会被 store 级 FK 清理留下半截
        状态（无行程却仍排期）。内存有命中就不重灌（避免冲掉热行）。"""
        if (
            self._pg_ok
            and itinerary_id
            and not any(
                it.get("itinerary_id") == itinerary_id for it in self._items.values()
            )
        ):
            self._try_refresh()
        return super().release_itinerary(itinerary_id, now=now, actor=actor)

    def delete(self, item_id: str, *, actor: str | None = None) -> None:
        """删除 = 软删（2026-11-13 用户拍板「心愿单也是数据库」）：行保留，
        打 DELETION FLAG + 删除日期/时间/人留档，看板不再返回。booked 有
        真实订单仍拒绝（先退订）；source=plan 引擎行同样软删。"""
        item = self._items.get(item_id)
        if item is None:
            raise NotFoundError(item_id)
        if item.get("status") == STATUS_BOOKED:
            raise InvalidTransitionError("booked_not_deletable")
        now = datetime.now(timezone.utc)
        payload = dict(item)
        payload["deletion_flag"] = True
        payload["deletion_date"] = now.date().isoformat()
        payload["deletion_time"] = now.strftime("%H:%M:%S")
        payload["deleted_by"] = actor or item.get("owner_device_id")
        self._items[item_id] = payload
        self._write_through(item_id)
        del self._items[item_id]
        logger.info(
            "trip_item_soft_deleted id=%s by=%s", item_id, payload["deleted_by"]
        )

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
                # 2026-11-13 PK/payload 错位兼容：历史恢复行的 PK 列与
                # payload id 不一致，只按 PK get 会 miss → 误插一条新行，
                # 旧行成幽灵（看板删不掉/重复计数）。按 payload id 兜底
                # 命中后就地更新，绝不改 PK（避免与既有行主键冲突）。
                payload_id = (values.get("payload") or {}).get("id")
                if payload_id:
                    row = (
                        session.query(TripItem)
                        .filter(TripItem.payload["id"].astext == str(payload_id))
                        .first()
                    )
            if row is None:
                row = TripItem(id=values["id"])
                session.add(row)
                updates = values
            else:
                updates = {k: v for k, v in values.items() if k != "id"}
            for key, val in updates.items():
                setattr(row, key, val)
            session.commit()
