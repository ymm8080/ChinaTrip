"""远郊景区专线班次回填（poi_access_services，2026-11-16 用户拍板）。

用户口径：「远郊景区专线，无论火车还是直达巴士，需要先搜网络或者高德地图数据
拿到接驳的出发地点和时刻表、路途时间、到达时间、回程出发时间、回城到达时间、
票价、购票渠道，然后存入远郊景点交通 DATABASE。」

两条来路，都是「先拿到事实再落库」，不做猜测：

* ``--file``：人工/半自动核对过的 JSON（``DESIGN/data/access_services_*.json``），
  字段与表一一对应，带 ``source``/``source_url``/``fetched_at``，可重复导入（按
  city+poi_name+service_name 覆盖）；
* ``--from-amap``：按线路名查高德公交线路（首末班、票价），拿到后与已有摘要
  合并（需要配 AK；本仓 ``map_provider`` 目前只暴露 transit_route，线路检索留
  接口、默认不跑）。

用法：
    python -m app.jobs.import_access_services --file DESIGN/data/xxx.json
    python -m app.jobs.import_access_services --file xxx.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from app.db import get_session_factory

logger = logging.getLogger(__name__)

_FIELDS = (
    "city",
    "poi_name",
    "mode",
    "service_name",
    "operator",
    "boarding_stop",
    "boarding_lon",
    "boarding_lat",
    "alight_stop",
    "alight_lon",
    "alight_lat",
    "outbound_times",
    "outbound_first",
    "outbound_last",
    "outbound_frequency_minutes",
    "ride_minutes",
    "return_times",
    "return_first",
    "return_last",
    "return_frequency_minutes",
    "return_ride_minutes",
    "return_arrive_last",
    "fare_cny",
    "fare_kind",
    "fare_note",
    "ticket_channel",
    "ticket_url",
    "last_mile_minutes",
    "note",
    "note_en",
    "source",
    "source_url",
)

_SQL = text(
    """
    INSERT INTO poi_access_services (city, poi_name, mode, service_name, operator,
        boarding_stop, boarding_lon, boarding_lat, alight_stop, alight_lon, alight_lat,
        outbound_times, outbound_first, outbound_last, outbound_frequency_minutes,
        ride_minutes, return_times, return_first, return_last,
        return_frequency_minutes, return_ride_minutes, return_arrive_last,
        fare_cny, fare_kind, fare_note, ticket_channel, ticket_url, last_mile_minutes,
        note, note_en, source, source_url, fetched_at, active, updated_at)
    VALUES (:city, :poi_name, :mode, :service_name, :operator,
        :boarding_stop, :boarding_lon, :boarding_lat, :alight_stop, :alight_lon,
        :alight_lat, :outbound_times, :outbound_first, :outbound_last,
        :outbound_frequency_minutes, :ride_minutes, :return_times, :return_first,
        :return_last, :return_frequency_minutes, :return_ride_minutes,
        :return_arrive_last, :fare_cny, :fare_kind, :fare_note, :ticket_channel,
        :ticket_url, :last_mile_minutes, :note, :note_en, :source, :source_url,
        :fetched_at, TRUE, now())
    ON CONFLICT (city, poi_name, service_name) DO UPDATE SET
        mode = EXCLUDED.mode,
        operator = EXCLUDED.operator,
        boarding_stop = EXCLUDED.boarding_stop,
        boarding_lon = EXCLUDED.boarding_lon,
        boarding_lat = EXCLUDED.boarding_lat,
        alight_stop = EXCLUDED.alight_stop,
        alight_lon = EXCLUDED.alight_lon,
        alight_lat = EXCLUDED.alight_lat,
        outbound_times = EXCLUDED.outbound_times,
        outbound_first = EXCLUDED.outbound_first,
        outbound_last = EXCLUDED.outbound_last,
        outbound_frequency_minutes = EXCLUDED.outbound_frequency_minutes,
        ride_minutes = EXCLUDED.ride_minutes,
        return_times = EXCLUDED.return_times,
        return_first = EXCLUDED.return_first,
        return_last = EXCLUDED.return_last,
        return_frequency_minutes = EXCLUDED.return_frequency_minutes,
        return_ride_minutes = EXCLUDED.return_ride_minutes,
        return_arrive_last = EXCLUDED.return_arrive_last,
        fare_cny = EXCLUDED.fare_cny,
        fare_kind = EXCLUDED.fare_kind,
        fare_note = EXCLUDED.fare_note,
        ticket_channel = EXCLUDED.ticket_channel,
        ticket_url = EXCLUDED.ticket_url,
        last_mile_minutes = EXCLUDED.last_mile_minutes,
        note = EXCLUDED.note,
        note_en = EXCLUDED.note_en,
        source = EXCLUDED.source,
        source_url = EXCLUDED.source_url,
        fetched_at = EXCLUDED.fetched_at,
        active = TRUE,
        updated_at = now()
    """
)


def _payload(row: dict) -> dict:
    out = {field: row.get(field) for field in _FIELDS}
    if isinstance(out.get("outbound_times"), list):
        out["outbound_times"] = json.dumps(out["outbound_times"], ensure_ascii=False)
    if isinstance(out.get("return_times"), list):
        out["return_times"] = json.dumps(out["return_times"], ensure_ascii=False)
    out["fetched_at"] = datetime.utcnow()
    return out


def import_file(path: Path, *, dry_run: bool = False) -> int:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("services") or []
    if not rows:
        logger.warning("空文件：%s", path)
        return 0
    if dry_run:
        for row in rows:
            logger.info(
                "[dry] %s / %s / %s %s→%s 车 %s 分 票价 %s",
                row.get("city"),
                row.get("poi_name"),
                row.get("service_name"),
                row.get("outbound_first"),
                row.get("outbound_last"),
                row.get("ride_minutes"),
                row.get("fare_note"),
            )
        return len(rows)
    factory = get_session_factory()
    with factory() as session:
        for row in rows:
            session.execute(_SQL, _payload(row))
        session.commit()
    logger.info("导入 %d 条班次：%s", len(rows), path.name)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入远郊专线班次")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    count = import_file(args.file, dry_run=args.dry_run)
    print(f"OK {count} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
