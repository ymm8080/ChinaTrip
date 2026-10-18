"""Booking handoff endpoints — post-itinerary train/flight/hotel (design v2.2 §6.11).

Iron rule 22: handoff only — every response is a parameterized deeplink into
the official channel (12306 / qunar→ctrip / ctrip→meituan); no orders, no
funds, no credentials. Iron rule 23: every handoff ships with a refund_policy
summary; without channel-side structured data it explicitly defers to the
channel order page. All endpoints are fast-lane: no LLM involved.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.bookings import flight_booking, hotel_booking, train_booking
from app.services.trains import get_train_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bookings", tags=["bookings"])


class TrainRequest(BaseModel):
    from_city: str = Field(min_length=1, max_length=32)
    to_city: str = Field(min_length=1, max_length=32)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class FlightRequest(TrainRequest):
    """Same shape as TrainRequest."""


class HotelRequest(BaseModel):
    city: str = Field(min_length=1, max_length=32)
    near_poi_name: str = Field(min_length=1, max_length=128)
    lon: float
    lat: float
    checkin: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    checkout: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/train")
async def train(
    req: TrainRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return await train_booking(
            req.from_city, req.to_city, req.date,
            train_service=get_train_service(settings),
        )
    except ValueError as exc:
        logger.warning("train booking handoff rejected: %s", exc)
        raise HTTPException(status_code=422, detail="invalid_booking") from exc


@router.post("/flight")
async def flight(req: FlightRequest) -> dict:
    try:
        return flight_booking(req.from_city, req.to_city, req.date)
    except ValueError as exc:
        logger.warning("flight booking handoff rejected: %s", exc)
        raise HTTPException(status_code=422, detail="invalid_booking") from exc


@router.post("/hotel")
async def hotel(req: HotelRequest) -> dict:
    try:
        return hotel_booking(
            req.city,
            req.near_poi_name,
            lon=req.lon,
            lat=req.lat,
            checkin=req.checkin,
            checkout=req.checkout,
        )
    except ValueError as exc:
        logger.warning("hotel booking handoff rejected: %s", exc)
        raise HTTPException(status_code=422, detail="invalid_booking") from exc
