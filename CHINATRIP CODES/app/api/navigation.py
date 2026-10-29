"""Navigation endpoints — inbound five-mode coverage (design v2.2 §6.13).

Walking/transit routes are proxied through AmapClient (web-service key never
leaves the server); taxi/driving hand off via keyless deeplinks (iron rule 22);
train/flight legs are itinerary-layer reminders + the always-free missed-
connection fallback (§6.7). All endpoints are fast-lane: no LLM involved.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.amap_client import AmapClient, AmapError, AmapTimeoutError
from app.services.deeplinks import compose_deeplink
from app.services.map_provider import map_ready
from app.services.trains import get_train_service
from app.services.transport_reminders import (
    build_departure_reminders,
    missed_connection_fallback,
)

from .amap import get_amap_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/nav", tags=["navigation"])


class Location(BaseModel):
    lon: float
    lat: float


class Destination(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    lon: float
    lat: float


class WalkingRequest(BaseModel):
    origin: Location
    destination: Location


class TransitRequest(BaseModel):
    origin: Location
    destination: Location
    city: str = Field(min_length=1, max_length=32)
    cityd: str | None = Field(default=None, max_length=32)


class DeeplinkRequest(BaseModel):
    mode: str = Field(pattern="^(taxi|driving)$")
    destination: Destination
    origin: Destination | None = None


class TransportLeg(BaseModel):
    type: str = Field(pattern="^(train|flight)$")
    departure_time: datetime
    station_name: str = Field(min_length=1, max_length=128)
    station_location: Location | None = None
    from_city: str | None = Field(default=None, max_length=32)
    to_city: str | None = Field(default=None, max_length=32)
    date: str | None = Field(default=None, max_length=10)


def _fmt(loc: Location) -> str:
    return f"{loc.lon:.6f},{loc.lat:.6f}"


@router.post("/walking")
async def walking(
    req: WalkingRequest,
    settings: Settings = Depends(get_settings),
    client: AmapClient = Depends(get_amap_client),
) -> dict:
    if not map_ready(settings):
        raise HTTPException(status_code=503, detail="amap_not_configured")
    try:
        route = await client.walking_route(_fmt(req.origin), _fmt(req.destination))
    except AmapTimeoutError:
        raise HTTPException(status_code=504, detail="amap_timeout") from None
    except AmapError as exc:
        logger.warning("nav walking amap error: infocode=%s", exc.infocode)
        raise HTTPException(status_code=502, detail="amap_error") from exc
    return {"route": route}


@router.post("/transit")
async def transit(
    req: TransitRequest,
    settings: Settings = Depends(get_settings),
    client: AmapClient = Depends(get_amap_client),
) -> dict:
    if not map_ready(settings):
        raise HTTPException(status_code=503, detail="amap_not_configured")
    cityd = req.cityd if req.cityd else None
    try:
        plans = await client.transit_route(
            _fmt(req.origin), _fmt(req.destination), city=req.city, cityd=cityd
        )
    except AmapTimeoutError:
        raise HTTPException(status_code=504, detail="amap_timeout") from None
    except AmapError as exc:
        logger.warning("nav transit amap error: infocode=%s", exc.infocode)
        raise HTTPException(status_code=502, detail="amap_error") from exc
    return {"plans": plans[:3]}


@router.post("/deeplink")
async def deeplink(req: DeeplinkRequest) -> dict:
    origin = (
        None
        if req.origin is None
        else (req.origin.name, req.origin.lon, req.origin.lat)
    )
    try:
        return compose_deeplink(
            req.mode,
            req.destination.name,
            req.destination.lon,
            req.destination.lat,
            origin=origin,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_destination") from None


@router.post("/transport-reminders")
async def transport_reminders(req: TransportLeg) -> dict:
    try:
        reminders = build_departure_reminders(req.model_dump(), now=datetime.now())
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_leg") from None
    return {"reminders": reminders}


@router.post("/missed-connection")
async def missed_connection(
    req: TransportLeg,
    settings: Settings = Depends(get_settings),
) -> dict:
    def _taxi(station_name: str, lon: float, lat: float) -> dict:
        return compose_deeplink("taxi", station_name, lon, lat)

    try:
        return await missed_connection_fallback(
            req.model_dump(),
            train_service=get_train_service(settings),
            taxi_deeplink_builder=_taxi,
            now=datetime.now(),
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_leg") from None
