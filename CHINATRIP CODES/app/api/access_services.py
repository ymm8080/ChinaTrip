"""远郊景点交通审核台 API（2026-11-16 用户「LET'S HV A WEBPAGE PUBLISHED」）。

一页式审核：列出所有远郊班次行 + 官方核实状态，支持就地改（首末班 / 车上分钟 /
票价 / 上车点 / 官方 URL / 状态）。改完立刻生效——`window_source` 跟着改成
`official`，`access_services.STRICT_OFFICIAL` 只认这个，所以「页面里填的」就是
「排期用的」，不搞第二份数据。

路由：
* ``GET  /api/v1/access-services``       —— 全量（可按 city / status 过滤）
* ``PATCH /api/v1/access-services/{id}`` —— 局部更新（只写传了的字段）
* ``GET  /api/v1/access-services/summary`` —— 按城市/状态计数
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.db import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/access-services", tags=["access-services"])

_LIST_SQL = """
SELECT s.id, s.city, s.poi_name, s.poi_name_en, s.mode, s.service_name,
       s.service_name_en, s.operator,
       s.boarding_stop, s.boarding_stop_en, s.boarding_lon, s.boarding_lat,
       s.alight_stop, s.outbound_times, s.outbound_first, s.outbound_last,
       s.outbound_frequency_minutes, s.ride_minutes,
       s.return_times, s.return_first, s.return_last, s.return_ride_minutes,
       s.fare_cny, s.fare_kind, s.fare_note, s.ticket_channel, s.ticket_url,
       s.last_mile_minutes, s.note, s.note_en,
       s.source, s.source_url, s.official_url, s.official_status,
       s.window_source, s.fare_source, s.active, s.updated_at,
       p.access_note, p.access_mode, p.access_minutes
  FROM poi_access_services s
  LEFT JOIN pois p ON p.city = s.city AND p.name_zh = s.poi_name
 WHERE s.active IS TRUE
   AND (:city = '' OR s.city = :city)
   AND (:status = '' OR COALESCE(s.official_status, 'pending') = :status)
 ORDER BY s.city, s.poi_name, s.service_name
"""

_SUMMARY_SQL = """
SELECT city, COALESCE(official_status, 'pending') AS status, count(*)
  FROM poi_access_services
 WHERE active IS TRUE
 GROUP BY 1, 2
 ORDER BY 1, 2
"""

_EDITABLE = (
    "outbound_first",
    "outbound_last",
    "outbound_times",
    "outbound_frequency_minutes",
    "ride_minutes",
    "return_first",
    "return_last",
    "return_times",
    "return_ride_minutes",
    "fare_cny",
    "fare_kind",
    "fare_note",
    "ticket_channel",
    "ticket_url",
    "boarding_stop",
    "boarding_stop_en",
    "boarding_lon",
    "boarding_lat",
    "last_mile_minutes",
    "note",
    "note_en",
    "official_url",
    "official_status",
    "service_name_en",
)


class AccessServicePatch(BaseModel):
    """审核台可改字段（None=不动）。"""

    outbound_first: str | None = None
    outbound_last: str | None = None
    outbound_times: list[str] | None = None
    outbound_frequency_minutes: int | None = None
    ride_minutes: int | None = None
    return_first: str | None = None
    return_last: str | None = None
    return_times: list[str] | None = None
    return_ride_minutes: int | None = None
    fare_cny: float | None = None
    fare_kind: str | None = None
    fare_note: str | None = None
    ticket_channel: str | None = None
    ticket_url: str | None = None
    boarding_stop: str | None = None
    boarding_stop_en: str | None = None
    boarding_lon: float | None = None
    boarding_lat: float | None = None
    last_mile_minutes: int | None = None
    note: str | None = None
    note_en: str | None = None
    official_url: str | None = None
    official_status: str | None = None
    service_name_en: str | None = None
    mark_official: bool = False


def _factory():
    return get_session_factory()


def _row_to_dict(row) -> dict:
    keys = row._mapping.keys()
    out = {key: row._mapping[key] for key in keys}
    for key in ("boarding_lon", "boarding_lat", "fare_cny"):
        if out.get(key) is not None:
            out[key] = float(out[key])
    if out.get("updated_at") is not None:
        out["updated_at"] = out["updated_at"].isoformat()
    return out


@router.get("")
def list_services(
    response: Response,
    city: str = Query(""),
    status: str = Query(""),
) -> dict:
    """全量班次行（审核台数据源）。"""
    response.headers["Cache-Control"] = "no-store"
    with _factory()() as session:
        rows = session.execute(text(_LIST_SQL), {"city": city, "status": status}).all()
    return {"items": [_row_to_dict(row) for row in rows], "count": len(rows)}


@router.get("/summary")
def summary() -> dict:
    with _factory()() as session:
        rows = session.execute(text(_SUMMARY_SQL)).all()
    return {
        "buckets": [{"city": row[0], "status": row[1], "count": row[2]} for row in rows]
    }


@router.patch("/{row_id}")
def update_service(row_id: int, patch: AccessServicePatch) -> dict:
    """局部更新一条班次行；`mark_official` 把时刻/票价来源标成官方。"""
    data = patch.model_dump(exclude_unset=True, exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="nothing_to_update")

    sets: list[str] = []
    params: dict = {"row_id": row_id}
    for field in _EDITABLE:
        if field not in data:
            continue
        value = data[field]
        if field in ("outbound_times", "return_times"):
            sets.append(f"{field} = CAST(:{field} AS jsonb)")
            params[field] = json.dumps(value, ensure_ascii=False)
        else:
            sets.append(f"{field} = :{field}")
            params[field] = value

    if data.get("mark_official"):
        # 页面里填的就是排期要用的：时刻标官方，票价有值也标官方
        sets.append(
            "window_source = CASE WHEN :has_window THEN 'official' ELSE NULL END"
        )
        sets.append("fare_source = CASE WHEN :has_fare THEN 'official' ELSE NULL END")
        params["has_window"] = bool(
            data.get("outbound_first")
            or data.get("outbound_last")
            or data.get("outbound_times")
        )
        params["has_fare"] = bool(data.get("fare_cny"))
        sets.append("official_status = COALESCE(:official_status, official_status)")
        params["official_status"] = data.get("official_status") or "verified"
    sets.append("updated_at = now()")

    sql = f"UPDATE poi_access_services SET {', '.join(sets)} WHERE id = :row_id"
    with _factory()() as session:
        result = session.execute(text(sql), params)
        if not result.rowcount:
            raise HTTPException(status_code=404, detail="not_found")
        session.commit()
        row = session.execute(
            text("SELECT * FROM poi_access_services WHERE id = :row_id"),
            {"row_id": row_id},
        ).first()
    return {"item": _row_to_dict(row) if row is not None else None}
