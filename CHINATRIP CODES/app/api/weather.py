"""City weather API (v2.5 参考数据域) — read-only feed over the
weather_reports snapshot table (DESIGN §4.1 / §6.2 矩阵行).

Lookup by city name (中文或英文别名，「市」后缀容错) or 6-digit adcode.
Pure DB read — freshness comes from the scheduled fetch job
(08:10/11:10/18:10, after Amap's own 8/11/18 forecast updates); the
response carries report_time / fetched_at so the H5 can show 数据时间.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session_factory
from app.models import WeatherReport
from app.services.agent.plan import CITY_ALIASES
from app.services.weather import city_to_adcode

router = APIRouter(prefix="/api/weather", tags=["weather"])


def get_weather_session_factory() -> sessionmaker[Session]:
    """Indirection over db.get_session_factory so tests can override
    (dependency_overrides) without touching the lru_cache'd engine."""
    return get_session_factory()


class WeatherView(BaseModel):
    city: str | None = None
    adcode: str
    live: dict | None = None
    live_report_time: datetime | None = None
    forecast: dict | None = None
    forecast_report_time: datetime | None = None
    fetched_at: datetime | None = None


def _resolve_adcode(city: str) -> str:
    # 英文别名先归一到中文（与 KNOWN_CITIES/CITY_ALIASES 同口径），再查表
    normalized = CITY_ALIASES.get(city.strip().lower(), city)
    adcode = city_to_adcode(normalized)
    if not adcode:
        raise HTTPException(status_code=404, detail=f"未收录城市: {city}")
    return adcode


@router.get("", response_model=WeatherView)
def get_weather(
    city: str,
    session_factory: sessionmaker[Session] = Depends(get_weather_session_factory),
) -> WeatherView:
    adcode = _resolve_adcode(city)
    with session_factory() as session:
        rows = (
            session.query(WeatherReport)
            .filter(WeatherReport.source == "amap", WeatherReport.adcode == adcode)
            .all()
        )
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"暂无天气数据: {city}（等抓取作业跑完）"
        )
    live = next((r for r in rows if r.kind == "live"), None)
    forecast = next((r for r in rows if r.kind == "forecast"), None)
    fetched = [r.fetched_at for r in (live, forecast) if r is not None and r.fetched_at]
    return WeatherView(
        city=(live or forecast).city,
        adcode=adcode,
        live=live.payload if live else None,
        live_report_time=live.report_time if live else None,
        forecast=forecast.payload if forecast else None,
        forecast_report_time=forecast.report_time if forecast else None,
        fetched_at=max(fetched) if fetched else None,
    )
