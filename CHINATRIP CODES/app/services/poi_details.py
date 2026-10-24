"""POI display details (address + opening hours) store (v2.4.4).

用户拍板 2026-10-19: enrichment results live in the pois table; the daily
job (app.jobs.refresh_pois) runs the source chain — 携程 sight pages
first, then 高德 v5 detail / keyword search — and planning READS this
store instead of fetching live. When the database is unreachable (MVP dev
without the docker db) the store degrades to an in-process dict so
planning keeps working; the next job run against the DB repopulates it.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, or_

from app.models import Poi
from app.services.coords import gcj02_to_wgs84, make_point

logger = logging.getLogger(__name__)

# ST_AsText(点几何) → "POINT(lon lat)"（geography 同样 lon 在前）
_POINT_WKT_RE = re.compile(r"POINT\((\S+) (\S+)\)")

_STALE_AFTER = timedelta(hours=24)
# After a failed DB call, skip DB attempts for this long (memory
# serves instead). Bounds the down-db cost to ONE connect_timeout
# stall per window instead of one per call (2026-10-20 latency fix).
_DB_DOWN_COOLDOWN_SECONDS = 300.0


class PoiDetailStore:
    """Read/upsert POI display details; DB-backed with memory fallback."""

    def __init__(self, session_factory=None) -> None:
        self._factory = session_factory
        self._memory: dict[str, dict] = {}
        self._db_down_until = 0.0  # time.monotonic() deadline

    def _db_available(self) -> bool:
        return self._factory is not None and (time.monotonic() >= self._db_down_until)

    def _note_db_failure(self) -> None:
        self._db_down_until = time.monotonic() + _DB_DOWN_COOLDOWN_SECONDS

    # --- read ---------------------------------------------------------------

    def get(self, source_poi_id: str) -> dict | None:
        if self._db_available():
            try:
                with self._factory() as session:
                    row = (
                        session.query(Poi)
                        .filter_by(source="amap", source_poi_id=source_poi_id)
                        .one_or_none()
                    )
                    if row is None:
                        return None
                    return {
                        "poi_id": row.source_poi_id,
                        "address": row.address,
                        "opening_hours": row.opening_hours,
                        "hours_source": row.hours_source,
                        "hours_updated_at": (
                            row.hours_updated_at.isoformat()
                            if row.hours_updated_at
                            else None
                        ),
                    }
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: db read failed, memory fallback",
                    exc_info=True,
                )
        return self._memory.get(source_poi_id)

    def stale_pois(
        self,
        *,
        limit: int = 200,
        sources: tuple[str, ...] | None = None,
        city: str | None = None,
    ) -> list[tuple[str, str | None, str | None, str | None, str | None]]:
        """POIs whose hours are missing or older than 24h (job targets).

        返回 (source_poi_id, city, name_zh, source, location) 五元组；
        location 为 amap-ready "lon,lat"（GCJ-02，无坐标行 None）——链③
        text 配额尽(10021)时 client 降级 around-search 要用（2026-10-24）。
        sources 非 None 时只返回指定 source 的行（骨架行按渠道分批回源
        用）。city 过滤必须在 SQL 层做——查询无 ORDER BY，limit 窗口是
        物理顺序前 N 行；若窗口外过滤，单城刷批次会拿不到行（2026-10-23
        实测：首 200 行全北京，其余城 total=0 饿死）。
        """
        cutoff = datetime.now(timezone.utc) - _STALE_AFTER
        city_names = (
            {city, f"{city}市", (city or "").removesuffix("市")} if city else None
        )
        if self._db_available():
            try:
                with self._factory() as session:
                    q = session.query(
                        Poi, func.ST_AsText(Poi.location).label("loc_txt")
                    ).filter(
                        Poi.hours_updated_at.is_(None) | (Poi.hours_updated_at < cutoff)
                    )
                    if sources is not None:
                        q = q.filter(Poi.source.in_(list(sources)))
                    if city_names:
                        q = q.filter(Poi.city.in_(city_names))
                    rows = q.limit(limit).all()
                    out = []
                    for r, loc_txt in rows:
                        m = _POINT_WKT_RE.match(loc_txt or "")
                        out.append(
                            (
                                r.source_poi_id,
                                r.city,
                                r.name_zh,
                                r.source,
                                f"{m.group(1)},{m.group(2)}" if m else None,
                            )
                        )
                    return out
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: db unreachable, memory fallback",
                    exc_info=True,
                )
        out: list[tuple[str, str | None, str | None, str | None, str | None]] = []
        for pid, v in self._memory.items():
            ts = v.get("hours_updated_at")
            if ts is None or ts < cutoff:
                loc = v.get("location")
                out.append(
                    (
                        pid,
                        v.get("city"),
                        v.get("name"),
                        v.get("source") or "amap",
                        f"{loc[0]},{loc[1]}" if loc else None,
                    )
                )
        if sources is not None:
            out = [t for t in out if (t[3] or "") in sources]
        if city_names:
            out = [t for t in out if t[1] in city_names]
        return out[:limit]

    def ping(self) -> bool:
        # Explicit probe: ignores the down-latch so the daily job and
        # a mid-session db start recover without a process restart.
        if self._factory is None:
            return False
        try:
            with self._factory() as session:
                session.query(Poi.id).first()
            self._db_down_until = 0.0
            return True
        except Exception:
            return False

    # --- write --------------------------------------------------------------

    def get_by_name(self, city: str | None, name: str) -> dict | None:
        """Exact-name lookup so appended rows serve later no-poi_id items."""
        name = (name or "").strip()
        if not name:
            return None
        if self._db_available():
            try:
                with self._factory() as session:
                    row = session.query(Poi).filter(Poi.name_zh == name).first()
                    if row is None:
                        return None
                    return {
                        "poi_id": row.source_poi_id,
                        "address": row.address,
                        "opening_hours": row.opening_hours,
                        "hours_source": row.hours_source,
                    }
            except Exception:
                self._note_db_failure()
                logger.warning("poi_details: db get_by_name failed", exc_info=True)
        for key, v in self._memory.items():
            if v.get("name") == name:
                return dict(v, poi_id=key)
        return None

    def search_keyword(
        self, city: str | None, tokens: list[str], *, limit: int = 5
    ) -> list[dict]:
        """POI 底库关键字搜索（心愿落实先查库再打高德，用户拍板
        2026-10-24）。city 匹配同 stale_pois 三态；tokens 对 name_zh/
        category 做 LIKE。返回 amap 形状的骨架 dict（name/city/category/
        source_poi_id/location/address/opening_hours/source/rating），
        按（名字精确命中，有坐标，类别命中）降序。"""
        toks = [t for t in (tokens or []) if t]
        if not toks:
            return []
        city_names = None
        if city:
            c = city.strip()
            city_names = {c, f"{c}市", c.removesuffix("市")} - {""}

        def rank(h: dict) -> tuple[bool, bool, bool]:
            n = (h.get("name") or "").strip()
            return (
                any(n == t for t in toks),
                h.get("location") is not None,
                any(t in (h.get("category") or "") for t in toks),
            )

        if self._db_available():
            try:
                with self._factory() as session:
                    q = session.query(
                        Poi, func.ST_AsText(Poi.location).label("loc_txt")
                    )
                    if city_names:
                        q = q.filter(Poi.city.in_(city_names))
                    conds = []
                    for t in toks:
                        pat = f"%{t}%"
                        conds.append(Poi.name_zh.like(pat))
                        conds.append(Poi.category.like(pat))
                    rows = q.filter(or_(*conds)).limit(limit * 3).all()
                    hits = []
                    for row, loc_txt in rows:
                        m = _POINT_WKT_RE.match(loc_txt or "")
                        hits.append(
                            {
                                "source_poi_id": row.source_poi_id,
                                "name": row.name_zh,
                                "city": row.city,
                                "category": row.category,
                                "address": row.address,
                                "opening_hours": row.opening_hours,
                                "source": row.source,
                                "rating": None,
                                "location": (
                                    (float(m.group(1)), float(m.group(2)))
                                    if m
                                    else None
                                ),
                            }
                        )
                    hits.sort(key=rank, reverse=True)
                    return hits[:limit]
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: db keyword search failed, memory fallback",
                    exc_info=True,
                )
        hits = []
        for pid, v in self._memory.items():
            if city_names and v.get("city") not in city_names:
                continue
            name = v.get("name") or ""
            hay = f"{name} {v.get('category') or ''}"
            if not any(t in hay for t in toks):
                continue
            loc = v.get("location")
            hits.append(
                {
                    "source_poi_id": pid,
                    "name": name,
                    "city": v.get("city"),
                    "category": v.get("category"),
                    "address": v.get("address"),
                    "opening_hours": v.get("opening_hours"),
                    "source": v.get("source") or "amap",
                    "rating": None,
                    "location": tuple(loc) if loc else None,
                }
            )
        hits.sort(key=rank, reverse=True)
        return hits[:limit]

    def upsert(
        self,
        source_poi_id: str,
        *,
        city: str | None = None,
        name: str | None = None,
        address: str | None = None,
        opening_hours: str | None = None,
        hours_source: str | None = None,
        source: str = "amap",
        category: str | None = None,
        location: tuple[float, float] | None = None,
    ) -> bool:
        """Persist display details; memory always written, DB best-effort.

        category/location 是 v2.5 骨架字段（外部源仅写名称/坐标/类别，
        用户拍板 2026-10-24：关键字搜到的店 APPEND 进 pois，沿用现有
        food/attraction 归类）；location 为 GCJ-02 (lon, lat)，入库按
        v1.7 铁律成对写 wgs84 副本。
        """
        # 列宽 varchar(500)（高德多季节营业时间串可超长，2026-10-23 实测
        # 114/200 行因 StringDataRightTruncation 丢写），入库前截断
        address = address[:500] if address else address
        opening_hours = opening_hours[:500] if opening_hours else opening_hours
        now = datetime.now(timezone.utc)
        mem = self._memory.setdefault(source_poi_id, {})
        if city and not mem.get("city"):
            mem["city"] = city
        if name and not mem.get("name"):
            mem["name"] = name
        if source and not mem.get("source"):
            mem["source"] = source
        if category and not mem.get("category"):
            mem["category"] = category
        if location and not mem.get("location"):
            mem["location"] = location
        if address:
            mem["address"] = address
        if opening_hours:
            mem["opening_hours"] = opening_hours
        if hours_source:
            mem["hours_source"] = hours_source
        if opening_hours:
            mem["hours_updated_at"] = now
        if self._factory is None or not self._db_available():
            return True
        point = make_point(*location) if location else None
        try:
            with self._factory() as session:
                row = (
                    session.query(Poi)
                    .filter_by(source=source, source_poi_id=source_poi_id)
                    .one_or_none()
                )
                if row is None:
                    row = Poi(
                        id=uuid4(),
                        source=source,
                        source_poi_id=source_poi_id,
                        city=city,
                        name_zh=name,
                        address=address,
                        opening_hours=opening_hours,
                        hours_source=hours_source,
                        hours_updated_at=now,
                    )
                    if category:
                        row.category = category
                    if point is not None:
                        row.location = point
                        row.wgs84_location = make_point(*gcj02_to_wgs84(*location))
                    session.add(row)
                else:
                    if city and not row.city:
                        row.city = city
                    if name and not row.name_zh:
                        row.name_zh = name
                    if category and not row.category:
                        row.category = category
                    if point is not None and row.location is None:
                        row.location = point
                        row.wgs84_location = make_point(*gcj02_to_wgs84(*location))
                    if address:
                        row.address = address
                    if opening_hours:
                        row.opening_hours = opening_hours
                    if hours_source:
                        row.hours_source = hours_source
                    if opening_hours:
                        row.hours_updated_at = now
                session.commit()
            return True
        except Exception:
            self._note_db_failure()
            logger.warning("poi_details: db upsert failed (memory kept)", exc_info=True)
            return True

    def touch_hours_checked(self, source_poi_id: str) -> bool:
        """MISS 冷却：只盖 hours_updated_at=now，不写 hours/source。

        永久缺 hours 的行（骨架不可匹配等）原本每轮重复查询、一天
        多次烧 text 配额（2026-10-24 实测 200 连续超限）；盖戳即进
        24h 静默（stale_pois 窗口外）。内存同步盖；DB UPDATE 失败只
        记日志不抛（冷却失败无害，下轮多查一次而已）。
        """
        now = datetime.now(timezone.utc)
        mem = self._memory.get(source_poi_id)
        if mem is not None:
            mem["hours_updated_at"] = now
        if self._factory is None or not self._db_available():
            return True
        try:
            with self._factory() as session:
                session.query(Poi).filter(Poi.source_poi_id == source_poi_id).update(
                    {Poi.hours_updated_at: now}
                )
                session.commit()
        except Exception:
            self._note_db_failure()
            logger.warning("poi_details: hours touch failed", exc_info=True)
        return True


_store_singleton: PoiDetailStore | None = None


def get_poi_detail_store() -> PoiDetailStore:
    """Process-wide lazy singleton; DB factory wired when available."""
    global _store_singleton
    if _store_singleton is None:
        from app.db import get_session_factory

        try:
            factory = get_session_factory()
        except Exception:
            factory = None
        _store_singleton = PoiDetailStore(session_factory=factory)
    return _store_singleton
