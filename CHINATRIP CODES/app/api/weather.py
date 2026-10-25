"""City weather API (v2.5 参考数据域) — read-only feed over the
weather_reports snapshot table (DESIGN §4.1 / §6.2 矩阵行).

Lookup by city name (中文或英文别名，「市」后缀容错) or 6-digit adcode.
Pure DB read — freshness comes from the scheduled fetch job
(08:10/11:10/18:10, after Amap's own 8/11/18 forecast updates); the
response carries report_time / fetched_at so the H5 can show 数据时间.

POST /sync：开站新鲜度巡检——行程城市 fetched_at 非今天（北京时间）或
无数据的内联刷新（高德 0-3 天 + Open-Meteo 14 天），其余只读秒回。
"""

import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.api.itineraries import get_store
from app.api.trip_items import get_trip_item_service
from app.config import get_settings
from app.db import get_session_factory
from app.models import WeatherReport
from app.services.agent.plan import CITY_ALIASES
from app.services.amap_client import AmapClient
from app.services.lang_ctx import L, is_en
from app.services.weather import (
    city_to_adcode,
    fetch_and_store,
    store_cities,
    trip_cities,
)
from app.services.weather_open_meteo import day_text_en, fetch_forecast14

router = APIRouter(prefix="/api/weather", tags=["weather"])

# 内联刷新城市上限——高德 ~2 次调用/城，兜底防配额被一次请求打穿
MAX_SYNC_CITIES = 12


def get_weather_session_factory() -> sessionmaker[Session]:
    """Indirection over db.get_session_factory so tests can override
    (dependency_overrides) without touching the lru_cache'd engine."""
    return get_session_factory()


def get_h5_store():
    """Indirection over the itinerary-store singleton so tests can inject
    an empty in-memory store instead of booting the real state domain."""
    return get_store()


def get_h5_trip_item_service():
    return get_trip_item_service()


class WeatherView(BaseModel):
    city: str | None = None
    adcode: str
    live: dict | None = None
    live_report_time: datetime | None = None
    forecast: dict | None = None
    forecast_report_time: datetime | None = None
    # Open-Meteo 14 天逐日（source=open-meteo, kind=forecast14），payload 与
    # forecast 同构（casts 数组）；0-3 天两源都有，前端先高德后此源
    forecast14: dict | None = None
    fetched_at: datetime | None = None


def _resolve_adcode(city: str) -> str:
    # 英文别名先归一到中文（与 KNOWN_CITIES/CITY_ALIASES 同口径），再查表
    normalized = CITY_ALIASES.get(city.strip().lower(), city)
    adcode = city_to_adcode(normalized)
    if not adcode:
        raise HTTPException(
            status_code=404,
            detail=L(f"未收录城市: {city}", f"City not covered: {city}"),
        )
    return adcode


def _payload_en(payload: dict | None) -> dict | None:
    """EN 请求读侧翻译：库里天气文案恒 zh（抓取作业无请求上下文），
    day_weather/night_weather 用 day_text_en 反查；未命中（高德上游独有
    zh 文案等）原样透传。zh 请求 payload 原样返回。"""
    if payload is None or not is_en():
        return payload
    out = dict(payload)
    if isinstance(out.get("casts"), list):
        out["casts"] = [
            {
                **cast,
                **{
                    key: day_text_en(cast[key])
                    for key in ("day_weather", "night_weather")
                    if isinstance(cast.get(key), str)
                },
            }
            if isinstance(cast, dict)
            else cast
            for cast in out["casts"]
        ]
    if isinstance(out.get("weather"), str):  # 高德 live 实况文案同一词汇表
        out["weather"] = day_text_en(out["weather"])
    return out


@router.get("", response_model=WeatherView)
def get_weather(
    city: str,
    session_factory: sessionmaker[Session] = Depends(get_weather_session_factory),
) -> WeatherView:
    adcode = _resolve_adcode(city)
    with session_factory() as session:
        # 不限 source：高德（live/forecast）与 Open-Meteo（forecast14）都按 kind 取
        rows = session.query(WeatherReport).filter(WeatherReport.adcode == adcode).all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=L(
                f"暂无天气数据: {city}（等抓取作业跑完）",
                f"No weather data yet: {city} (waiting for the fetch job)",
            ),
        )
    live = next((r for r in rows if r.kind == "live"), None)
    forecast = next((r for r in rows if r.kind == "forecast"), None)
    forecast14 = next((r for r in rows if r.kind == "forecast14"), None)
    present = [r for r in (live, forecast, forecast14) if r is not None]
    fetched = [r.fetched_at for r in present if r.fetched_at]
    return WeatherView(
        city=(present[0]).city,
        adcode=adcode,
        live=_payload_en(live.payload) if live else None,
        live_report_time=live.report_time if live else None,
        forecast=_payload_en(forecast.payload) if forecast else None,
        forecast_report_time=forecast.report_time if forecast else None,
        forecast14=_payload_en(forecast14.payload) if forecast14 else None,
        fetched_at=max(fetched) if fetched else None,
    )


class SyncRequest(BaseModel):
    cities: list[str] = []  # 空 = 行程涉及城市（服务端 trip_cities）


class CityWeatherStatus(BaseModel):
    city: str
    adcode: str
    fetched_at: datetime | None = None
    refreshed: bool = False


class SyncResult(BaseModel):
    today: str
    cities: list[CityWeatherStatus] = []


def _today_beijing() -> str:
    # fetched_at 存 UTC，用户在东八区——按北京时间判「今天」
    return (datetime.utcnow() + timedelta(hours=8)).date().isoformat()


@router.post("/sync", response_model=SyncResult)
def sync_weather(
    body: SyncRequest,
    session_factory: sessionmaker[Session] = Depends(get_weather_session_factory),
    store=Depends(get_h5_store),
    trip_item_svc=Depends(get_h5_trip_item_service),
) -> SyncResult:
    if body.cities:
        names = body.cities
    else:
        with session_factory() as session:
            names = trip_cities(session)
        # PG 三表 + H5 状态域并集：旧行程都在状态库里，只查三表永远为空
        names = sorted({*names, *store_cities(store, trip_item_svc)})

    adcode_city: dict[str, str] = {}
    for name in names:
        normalized = CITY_ALIASES.get(name.strip().lower(), name)
        adcode = city_to_adcode(normalized)
        if adcode:  # 未收录城市静默跳过（sync 是巡检，不该报错）
            adcode_city[adcode] = normalized.removesuffix("市")
    if not adcode_city:
        return SyncResult(today=_today_beijing(), cities=[])

    with session_factory() as session:
        rows = (
            session.query(WeatherReport)
            .filter(WeatherReport.adcode.in_(list(adcode_city)))
            .all()
        )
    fetched: dict[str, datetime] = {}
    for row in rows:
        if row.fetched_at and row.fetched_at > fetched.get(row.adcode, datetime.min):
            fetched[row.adcode] = row.fetched_at

    stale = [
        adcode
        for adcode in adcode_city
        if adcode not in fetched
        or (fetched[adcode] + timedelta(hours=8)).date().isoformat() != _today_beijing()
    ]

    refreshed: set[str] = set()
    if stale:
        targets = [adcode_city[a] for a in stale][:MAX_SYNC_CITIES]
        settings = get_settings()
        if settings.amap_api_key:
            client = AmapClient(
                key=settings.amap_api_key,
                base_url=settings.amap_base_url,
                timeout_seconds=settings.amap_timeout_seconds,
            )
            asyncio.run(fetch_and_store(session_factory, client, targets))
        asyncio.run(fetch_forecast14(session_factory, targets))
        refreshed = set(adcode_city[a] for a in stale[:MAX_SYNC_CITIES])
        now = datetime.utcnow()
        for adcode in stale[:MAX_SYNC_CITIES]:
            fetched[adcode] = now

    return SyncResult(
        today=_today_beijing(),
        cities=[
            CityWeatherStatus(
                city=adcode_city[adcode],
                adcode=adcode,
                fetched_at=fetched.get(adcode),
                refreshed=adcode_city[adcode] in refreshed,
            )
            for adcode in sorted(adcode_city)
        ],
    )
