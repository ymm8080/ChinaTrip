"""城市天气抓取作业（唯一连天气 API 的地方；DESIGN §6.2 矩阵行）。

两源流水：
  1. 0-7 天源（默认跟随 settings.map_provider，--src 可显式覆盖）：
     - 高德（实况 + 3~4 天预报）——个人 key 约 100 次/日配额，每城每次
       2 次调用，40 城全量 = 80 次/日，在配额内。
     - 百度天气（实况 + 5 天预报）——个人认证免配额量大（日 3 万级），
       district_id 与高德 adcode 同为 6 位行政区划码直接复用。
  2. Open-Meteo（14 天逐日，免 key 无配额）——8-14 天补齐（TREK 双轨方案），
     每次运行全量 40 城；重跑可用 --skip-amap 只补这一段。
末尾统一清理：fetched_at 超 7 天的行删除（不再抓取的城市滞留数据）。

时机与范围（2026-10-28 定稿）：产品一天刷新一次，schtasks 定 08:10 单次
（紧跟中央气象台 ~08:00 早间更新）；**默认全量 40 城**——任何新行程城市
开站第一次天气都从表里读（POST /api/weather/sync 纯读表从不出网），
不再依赖行程城市发现，也无「先有行程后补数据」的空窗。漏跑无碍——
latest-wins 幂等，下次运行自动补齐。--city 可显式缩小范围（手动补数）。

用法：
    python -m app.jobs.fetch_weather [--city 北京 --city 上海] [--skip-amap]
"""

import argparse
import asyncio
import json
import sys

from app.config import get_settings
from app.services.amap_client import AmapClient
from app.services.baidu_client import BaiduClient
from app.services.map_provider import map_ready
from app.services.weather import CITY_ADCODES, fetch_and_store
from app.services.weather_open_meteo import fetch_forecast14, purge_stale


def resolve_targets(*, cities: list[str] | None = None) -> list[str]:
    """抓取范围：--city 显式 > 默认全量 40 城（新城市开站即有表数据）。"""
    if cities:
        return cities
    return list(CITY_ADCODES)


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
        "--city",
        action="append",
        help="指定城市（可重复，如 --city 北京）；缺省=全量 40 城",
    )
    parser.add_argument(
        "--skip-amap",
        action="store_true",
        help="跳过 0-7 天短轨源（省配额），只跑 Open-Meteo 14 天 + 清理",
    )
    parser.add_argument(
        "--src",
        choices=("amap", "baidu"),
        default=None,
        help="0-7 天源（默认跟随 settings.map_provider）",
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

    targets = resolve_targets(cities=args.city or [])

    stats: dict = {}
    # weather 源轴（--src 缺省=map_provider）与图商键独立双轴设计（2026-10-27 双轨）。
    if not args.skip_amap and map_ready(settings):
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

    stats["forecast14"] = asyncio.run(fetch_forecast14(factory, targets))
    stats["stale_deleted"] = asyncio.run(purge_stale(factory))
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
