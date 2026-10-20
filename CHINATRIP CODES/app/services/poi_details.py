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
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models import Poi

logger = logging.getLogger(__name__)

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
        self, *, limit: int = 200
    ) -> list[tuple[str, str | None, str | None]]:
        """POIs whose hours are missing or older than 24h (job targets)."""
        cutoff = datetime.now(timezone.utc) - _STALE_AFTER
        if self._db_available():
            try:
                with self._factory() as session:
                    rows = (
                        session.query(Poi)
                        .filter(
                            Poi.hours_updated_at.is_(None)
                            | (Poi.hours_updated_at < cutoff)
                        )
                        .limit(limit)
                        .all()
                    )
                    return [(r.source_poi_id, r.city, r.name_zh) for r in rows]
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: db unreachable, memory fallback",
                    exc_info=True,
                )
        out: list[tuple[str, str | None, str | None]] = []
        for pid, v in self._memory.items():
            ts = v.get("hours_updated_at")
            if ts is None or ts < cutoff:
                out.append((pid, v.get("city"), v.get("name")))
            if len(out) >= limit:
                break
        return out

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
    ) -> bool:
        """Persist display details; memory always written, DB best-effort."""
        now = datetime.now(timezone.utc)
        mem = self._memory.setdefault(source_poi_id, {})
        if city and not mem.get("city"):
            mem["city"] = city
        if name and not mem.get("name"):
            mem["name"] = name
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
        try:
            with self._factory() as session:
                row = (
                    session.query(Poi)
                    .filter_by(source="amap", source_poi_id=source_poi_id)
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
                    session.add(row)
                else:
                    if city and not row.city:
                        row.city = city
                    if name and not row.name_zh:
                        row.name_zh = name
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
