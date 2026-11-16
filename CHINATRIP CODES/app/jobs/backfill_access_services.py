"""远郊班次点 → poi_access_services 全量回填（2026-11-16 用户拍板）。

用户口径：「远郊景区专线，无论火车还是直达巴士，需要先搜网络或者高德地图数据拿到
接驳的出发地点和时刻表……然后存入远郊景点交通 DATABASE」「所有得远郊景点都
poi_access_services 都重新刷数据库」。

数据来路（不做猜测）：

* **官方口径优先**：`poi_access_services` 里已有 `source = official:*` 的行不动，
  那是人工核过的景区/运营方页面（如慕田峪前门旅游专线）；
* 其余远郊班次点，用本仓已有的**地图商实测档案**（`pois.access_*`，源
  `baidu-transit`）落成班次行：上车点/落客站/车上分钟/末段步行都是实测值，
  首末班从 `access_note` 里解析（`首班 07:00 / 末班 12:00` 或 `仅 08:30 一班`）。

「远郊」判据：dist(城心, POI) > `--min-km`（默认 25），与 `_mark_remote_visits`
同口径；城心取 `weather_open_meteo.CITY_COORDS`。

用法：
    python -m app.jobs.backfill_access_services [--dry-run] [--min-km 25]
        [--city 北京] [--limit 50]

只写 `poi_access_services`，不改 `pois.access_*`（那是另一条口径，卡片摘要仍用它）。
"""

from __future__ import annotations

import argparse
import logging
import math
import re
from datetime import UTC, datetime

from sqlalchemy import text

from app.db import get_session_factory
from app.services.weather_open_meteo import CITY_COORDS

logger = logging.getLogger(__name__)

#: 与移动端一致的「远郊」门槛（公里）。
REMOTE_KM = 10.0

#: 只回填有班次的接驳方式（与 itinerary.rules.SCHEDULED_ACCESS_MODES 同集合，
#: 另加 bus：城市公交也要留档，但引擎侧只有 train/shuttle/ferry 吃链）。
MODES = ("train", "shuttle", "ferry", "bus")

_FIRST_LAST_RE = re.compile(r"首班\s*(\d{1,2}:\d{2})\s*/\s*末班\s*(\d{1,2}:\d{2})")
_SINGLE_RE = re.compile(r"仅\s*(\d{1,2}:\d{2})\s*一班")
_TOTAL_RE = re.compile(r"全程约\s*(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分)?")
_LINE_RE = re.compile(r"^乘\s*([^：:]+)[：:]")
_BOARD_RE = re.compile(r"[：:]\s*([^→]+)→")

_SELECT_SQL = text(
    """
    SELECT id, name_zh, city, access_mode, access_minutes, access_gateway,
           access_gateway_minutes, access_boarding,
           ST_X(location::geometry), ST_Y(location::geometry),
           access_boarding_lon, access_boarding_lat,
           access_service_minutes, access_wait_minutes, access_last_mile_minutes,
           access_note, access_note_en
      FROM pois
     WHERE (status IS NULL OR status = 'active')
       AND location IS NOT NULL
       AND access_mode = ANY(:modes)
       AND access_boarding IS NOT NULL
    """
)

_OFFICIAL_SQL = text(
    """
    SELECT poi_name FROM poi_access_services
     WHERE city = :city AND active IS TRUE AND source LIKE 'official:%'
    """
)

_UPSERT_SQL = text(
    """
    INSERT INTO poi_access_services (
        city, poi_name, mode, service_name, operator,
        boarding_stop, boarding_lon, boarding_lat,
        alight_stop, alight_lon, alight_lat,
        outbound_times, outbound_first, outbound_last,
        outbound_frequency_minutes, ride_minutes,
        return_times, return_first, return_last,
        return_frequency_minutes, return_ride_minutes, return_arrive_last,
        fare_cny, fare_kind, fare_note, ticket_channel, ticket_url,
        last_mile_minutes, note, note_en, source, source_url,
        fetched_at, active, updated_at,
        official_status, window_source)

    VALUES (
        :city, :poi_name, :mode, :service_name, :operator,
        :boarding_stop, :boarding_lon, :boarding_lat,
        :alight_stop, :alight_lon, :alight_lat,
        CAST(:outbound_times AS jsonb), :outbound_first, :outbound_last,
        :outbound_frequency_minutes, :ride_minutes,
        NULL, NULL, NULL, NULL, NULL, NULL,
        NULL, NULL, NULL, NULL, NULL,
        :last_mile_minutes, :note, :note_en, :source, :source_url,
        :fetched_at, TRUE, now(), :official_status, :window_source)
    ON CONFLICT (city, poi_name, service_name) DO UPDATE SET
        mode = EXCLUDED.mode,
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
        last_mile_minutes = EXCLUDED.last_mile_minutes,
        note = EXCLUDED.note,
        note_en = EXCLUDED.note_en,
        source = EXCLUDED.source,
        source_url = EXCLUDED.source_url,
        official_status = EXCLUDED.official_status,
        window_source = EXCLUDED.window_source,
        fetched_at = EXCLUDED.fetched_at,
        active = TRUE,
        updated_at = now()
      WHERE poi_access_services.source NOT LIKE 'official:%'
    """
)


def _minutes(hhmm: str | None) -> int:
    if not hhmm:
        return 0
    hour, _, minute = hhmm.partition(":")
    return int(hour) * 60 + int(minute)


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def _parse(note: str | None) -> dict:
    """从 access_note 里抠线路名/首末班/单班/总时长。抠不到就给空值。"""
    out: dict = {
        "service_name": None,
        "boarding": None,
        "first": None,
        "last": None,
        "single": None,
    }
    if not note:
        return out
    line = _LINE_RE.search(note)
    if line:
        out["service_name"] = line.group(1).strip()
    board = _BOARD_RE.search(note)
    if board:
        out["boarding"] = board.group(1).strip()
    hit = _FIRST_LAST_RE.search(note)
    if hit:
        out["first"], out["last"] = hit.group(1), hit.group(2)
    single = _SINGLE_RE.search(note)
    if single:
        out["single"] = single.group(1)
    return out


def _total_minutes(note: str | None) -> int | None:
    if not note:
        return None
    hit = _TOTAL_RE.search(note)
    if not hit:
        return None
    hours = int(hit.group(1) or 0)
    mins = int(hit.group(2) or 0)
    total = hours * 60 + mins
    return total or None


def backfill(
    *,
    min_km: float = REMOTE_KM,
    city: str | None = None,
    limit: int = 0,
    dry_run: bool = False,
) -> dict:
    factory = get_session_factory()
    stats = {"candidates": 0, "written": 0, "skipped_official": 0, "with_window": 0}
    with factory() as session:
        rows = session.execute(_SELECT_SQL, {"modes": list(MODES)}).all()
        official: dict[tuple[str, str], bool] = {}
        for row in rows:
            poi_city = (row[2] or "").strip()
            if city and poi_city not in (city, city + "市"):
                continue
            center = CITY_COORDS.get(poi_city)
            if not center:
                continue
            lon, lat = float(row[8]), float(row[9])
            km = _km((lon, lat), (center[1], center[0]))
            if km <= min_km:
                continue
            stats["candidates"] += 1
            key = (poi_city, row[1])
            if key not in official:
                hit = session.execute(_OFFICIAL_SQL, {"city": poi_city}).scalars().all()
                for name in hit:
                    official[(poi_city, name)] = True
                official.setdefault(key, False)
            if official.get(key):
                stats["skipped_official"] += 1
                continue
            parsed = _parse(row[15])
            total = _total_minutes(row[15])
            ride = row[12] or 0
            wait = row[13] or 0
            last_mile = row[14] or 0
            if not ride and total:
                ride = max(0, total - wait - last_mile)
            payload = {
                "city": poi_city,
                "poi_name": row[1],
                "mode": row[3],
                "service_name": (parsed["service_name"] or f"{row[3]}接驳")[:160],
                "operator": None,
                "boarding_stop": (parsed["boarding"] or row[7] or None),
                "boarding_lon": row[10],
                "boarding_lat": row[11],
                "alight_stop": row[5],
                "alight_lon": lon,
                "alight_lat": lat,
                "outbound_times": (
                    f'["{parsed["single"]}"]' if parsed["single"] else None
                ),
                "outbound_first": parsed["first"],
                "outbound_last": parsed["last"] or parsed["single"],
                "outbound_frequency_minutes": None,
                "ride_minutes": ride or None,
                "last_mile_minutes": last_mile or None,
                "note": (row[15] or "")[:400] or None,
                "note_en": (row[16] or "")[:400] or None,
                "source": "baidu-transit",
                "source_url": None,
                "fetched_at": datetime.now(UTC).replace(tzinfo=None),
                "official_status": "pending",
                "window_source": (
                    "baidu" if (parsed["first"] or parsed["single"]) else None
                ),
            }
            # 上车点坐标从 pois 里没有单列（只有名字），留空由引擎按档案兜底
            if parsed["first"] or parsed["single"]:
                stats["with_window"] += 1
            if dry_run:
                logger.info(
                    "[dry] %s/%s %s 首 %s 末 %s 单 %s 车 %s 分",
                    poi_city,
                    row[1],
                    payload["service_name"],
                    parsed["first"],
                    parsed["last"],
                    parsed["single"],
                    ride,
                )
            else:
                session.execute(_UPSERT_SQL, payload)
            stats["written"] += 1
            if limit and stats["candidates"] >= limit:
                break
        if not dry_run:
            session.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="远郊班次点回填 poi_access_services")
    parser.add_argument("--min-km", type=float, default=REMOTE_KM)
    parser.add_argument("--city", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stats = backfill(
        min_km=args.min_km, city=args.city, limit=args.limit, dry_run=args.dry_run
    )
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
