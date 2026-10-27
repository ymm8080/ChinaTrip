"""城市天气抓取作业（高德天气 API，上游中国气象局；DESIGN §6.2 矩阵行）。

两源流水：
  1. 0-3 天源（默认跟随 settings.map_provider，--src 可显式覆盖）：
     - 高德（实况 + 3 天预报）——个人 key 约 100 次/日配额，每城每次 2 次
       调用；40 城全量×3 次/日 = 240 次/日会超，--all 仅限手动。
     - 百度天气（实况 + 5 天预报）——个人认证免配额量大（日 3 万级），
       district_id 与高德 adcode 同为 6 位行政区划码直接复用。
  2. Open-Meteo（14 天逐日，免 key 无配额）——4-14 天补齐（TREK 双轨方案），
     每次运行全量 40 城；重跑可用 --skip-amap 只补这一段。
末尾统一清理：fetched_at 超 7 天的行删除（不再抓取的城市滞留数据）。

时机：中央气象台城市预报每日约 08:00/11:00/18:00 三更（北京时间）；
产品只需一天一次，schtasks 定 08:10 单次（紧跟早间更新，拿全天最新
实况+7 天预报）；漏跑无碍——latest-wins 幂等，下次运行自动补齐，
且 H5 开站巡检（POST /api/weather/sync）对隔日数据现场自愈。

目标城市（优先级）：--city 显式 > --all 全量 40 城 > 默认行程涉及城市
（trip_items / itineraries 去重，见 app.services.weather.trip_cities）。

用法：
    python -m app.jobs.fetch_weather [--city 北京 --city 上海] [--all] [--skip-amap]
"""

import argparse
import asyncio
import json
import sys

from app.config import get_settings
from app.services.amap_client import AmapClient
from app.services.baidu_client import BaiduClient
from app.services.weather import (
    CITY_ADCODES,
    fetch_and_store,
    store_cities,
    trip_cities,
)
from app.services.weather_open_meteo import CITY_COORDS, fetch_forecast14, purge_stale


def resolve_targets(session, *, cities: list[str], fetch_all: bool) -> list[str]:
    if cities:
        return cities
    if fetch_all:
        return list(CITY_ADCODES)
    # PG 三表 + H5 状态域并集：api 层单例（PG 不可达时 store 自降级为空）。
    # 惰性导入——作业进程不在 import 时背起 FastAPI/存储栈。
    from app.api.itineraries import get_store
    from app.api.trip_items import get_trip_item_service

    names = set(trip_cities(session))
    names.update(store_cities(get_store(), get_trip_item_service()))
    return sorted(names)


def _ping(factory) -> bool:
    from app.models import WeatherReport

    try:
        with factory() as session:
            session.query(WeatherReport.id).first()
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="抓取城市天气入 weather_reports（高德天气 API，latest-wins）"
    )
    parser.add_argument(
        "--city", action="append", help="指定城市（可重复，如 --city 北京）"
    )
    parser.add_argument(
        "--all", action="store_true", help="全量 40 城（注意配额，仅手动单次）"
    )
    parser.add_argument(
        "--skip-amap",
        action="store_true",
        help="跳过高德（省配额），只跑 Open-Meteo 14 天 + 清理",
    )
    parser.add_argument(
        "--src",
        choices=("amap", "baidu"),
        default=None,
        help="0-3 天源（默认跟随 settings.map_provider）",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    src = args.src or settings.map_provider
    if src == "baidu":
        if not settings.baidu_ak:
            print(json.dumps({"error": "BAIDU_AK empty — set it in .env"}))
            return 1
    elif not settings.amap_api_key:
        print(json.dumps({"error": "AMAP_API_KEY empty — set it in .env"}))
        return 1

    from app.db import get_session_factory

    try:
        factory = get_session_factory()
    except Exception:
        factory = None
    if factory is None or not _ping(factory):
        print(
            json.dumps(
                {
                    "error": "database unreachable — "
                    "start docker db (docker compose up -d db) "
                    "and run alembic upgrade head (0007 weather_reports)"
                },
                ensure_ascii=True,
            )
        )
        return 1

    with factory() as session:
        targets = resolve_targets(session, cities=args.city or [], fetch_all=args.all)

    # 高德（有配额）只抓行程涉及城市，行程为空则无事可做；
    # Open-Meteo 14 天源（免 key 无配额）每次运行固定全量 40 主要城市
    targets14 = targets or list(CITY_COORDS)

    stats: dict = {}
    if targets and not args.skip_amap:
        if src == "baidu":
            client = BaiduClient(
                ak=settings.baidu_ak,
                base_url=settings.baidu_base_url,
                timeout_seconds=settings.amap_timeout_seconds,
            )
            stats = asyncio.run(
                fetch_and_store(factory, client, targets, source="baidu")
            )
        else:
            client = AmapClient(
                key=settings.amap_api_key,
                base_url=settings.amap_base_url,
                timeout_seconds=settings.amap_timeout_seconds,
            )
            stats = asyncio.run(fetch_and_store(factory, client, targets))

    stats["forecast14"] = asyncio.run(fetch_forecast14(factory, targets14))
    stats["stale_deleted"] = asyncio.run(purge_stale(factory))
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
