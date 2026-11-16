"""poi_access_services 的库内读口（供 access_services.configure_store 注入）。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


class AccessServiceStore:
    """按城市批量取班次（一次查询、进程内由调用方缓存）。"""

    def __init__(self, factory: Any) -> None:
        self._factory = factory

    def access_services(self, cities: list[str] | None = None) -> list[dict[str, Any]]:
        names = [c for c in (cities or []) if c]
        sql = """
            SELECT city, poi_name, mode, service_name, operator,
                   boarding_stop, boarding_lon, boarding_lat,
                   alight_stop, outbound_times, outbound_first, outbound_last,
                   outbound_frequency_minutes, ride_minutes,
                   return_times, return_first, return_last,
                   return_frequency_minutes, return_ride_minutes,
                   return_arrive_last, fare_cny, fare_kind, fare_note,
                   ticket_channel, ticket_url, last_mile_minutes,
                   note, note_en, source, source_url
                   official_url, official_status, window_source, fare_source,
                   poi_name_en, service_name_en, boarding_stop_en
              FROM poi_access_services
             WHERE active IS TRUE
        """
        params: dict[str, Any] = {}
        if names:
            sql += " AND city = ANY(:cities)"
            params["cities"] = names
        try:
            with self._factory() as session:
                rows = session.execute(text(sql), params).mappings().all()
        except Exception:  # noqa: BLE001 — 库不可用/未迁移都不能拦排程
            logger.warning("poi_access_services 读取失败，退回均值链", exc_info=True)
            return []
        return [dict(row) for row in rows]
