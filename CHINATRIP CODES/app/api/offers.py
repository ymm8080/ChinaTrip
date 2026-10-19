"""Offer-card endpoints — 转链交易中心候选卡片组 (design v2.3 §6.11).

Iron rule 22: the App never places orders — the offer center is a candidate
link picker; the user picks a channel card and completes the purchase on the
channel page. Generation is a deterministic five-step workflow
(query -> dedupe/compare -> sort -> deeplink -> present), not an agent loop.
Sorting carries zero commission weight: the sort key is price + channel
stability only, and no commission field exists anywhere in this module.
Every card ships a refund summary (iron rule 23) and the card group always
carries the fixed disclaimer; all links are key-free.
"""

import logging
from typing import Annotated, Literal, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.offer_cards import (
    flight_offer_cards,
    hotel_offer_cards,
    train_offer_cards,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/offers", tags=["offers"])

_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class HotelOfferRequest(BaseModel):
    kind: Literal["hotel"]
    city: str = Field(min_length=1, max_length=32)
    near_poi_name: str = Field(min_length=1, max_length=128)
    lon: float
    lat: float
    checkin: str = Field(pattern=_DATE_PATTERN)
    checkout: str = Field(pattern=_DATE_PATTERN)
    region: Literal["cn", "overseas"] = "cn"


class FlightOfferRequest(BaseModel):
    kind: Literal["flight"]
    from_city: str = Field(min_length=1, max_length=32)
    to_city: str = Field(min_length=1, max_length=32)
    date: str = Field(pattern=_DATE_PATTERN)
    region: Literal["cn", "overseas"] = "cn"


class TrainOfferRequest(BaseModel):
    kind: Literal["train"]
    from_city: str = Field(min_length=1, max_length=32)
    to_city: str = Field(min_length=1, max_length=32)
    date: str = Field(pattern=_DATE_PATTERN)


OfferQuery = Annotated[
    Union[HotelOfferRequest, FlightOfferRequest, TrainOfferRequest],
    Field(discriminator="kind"),
]


@router.post("/cards")
async def offer_cards(
    req: OfferQuery, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        if isinstance(req, HotelOfferRequest):
            return hotel_offer_cards(
                req.city,
                req.near_poi_name,
                lon=req.lon,
                lat=req.lat,
                checkin=req.checkin,
                checkout=req.checkout,
                region=req.region,
                settings=settings,
            )
        if isinstance(req, FlightOfferRequest):
            return flight_offer_cards(
                req.from_city,
                req.to_city,
                req.date,
                region=req.region,
                settings=settings,
            )
        return await train_offer_cards(
            req.from_city, req.to_city, req.date, settings=settings
        )
    except ValueError as exc:
        logger.warning("offer cards rejected: %s", exc)
        raise HTTPException(status_code=422, detail="invalid_booking") from exc
