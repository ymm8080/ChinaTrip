"""Trip-center item API (design v2.4 §5/§4) — thin shell over
TripItemService.

Every write path (manual form / chat / paste / agent recommendation) lands
in the same table (iron rule 0), and the timeline page reads that one
source: Bookings pinned on top + Wishlist stream + Scheduled third key.
The router is NOT registered in app/main.py — the orchestrator wires it.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.itineraries import get_store
from app.db import get_session_factory
from app.services.itinerary_store import ItineraryStore
from app.services.pg_state import PgTripItemService
from app.services.trip_items import (
    InvalidSourceError,
    InvalidTransitionError,
    NotFoundError,
    TripItemService,
)

router = APIRouter(prefix="/api/v1/trip-items", tags=["trip-items"])

# --- dependency factory (process-level lazy singleton, translate.py pattern) ---

_service_singleton: TripItemService | None = None


def get_trip_item_service() -> TripItemService:
    """Process-wide singleton: trip items must survive across requests —
    and across uvicorn restarts（2026-10-25 起写穿 PG，pg_state.PgTripItemService
    混合列 + payload；PG 不可达时自动降级纯内存）."""
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = PgTripItemService(get_session_factory())
    return _service_singleton


class CreateTripItemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=32)  # service whitelists values
    itinerary_id: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=2000)
    poi_id: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=200)
    opening_hours: str | None = Field(default=None, max_length=200)


class PatchTripItemRequest(BaseModel):
    status: str | None = Field(default=None, max_length=16)  # state machine checks
    day: int | None = Field(default=None, ge=1)
    position: float | None = None
    note: str | None = Field(default=None, max_length=2000)
    city: str | None = Field(default=None, max_length=64)
    booking_id: str | None = Field(default=None, max_length=128)


@router.post("", status_code=201)
async def create_trip_item(
    request: CreateTripItemRequest,
    service: TripItemService = Depends(get_trip_item_service),
) -> dict:
    try:
        return service.create(
            request.name,
            source=request.source,
            itinerary_id=request.itinerary_id,
            city=request.city,
            note=request.note,
            poi_id=request.poi_id,
            address=request.address,
            opening_hours=request.opening_hours,
        )
    except InvalidSourceError:
        raise HTTPException(status_code=422, detail="invalid_source") from None


@router.get("")
async def list_trip_items(
    itinerary_id: str | None = None,
    service: TripItemService = Depends(get_trip_item_service),
    store: ItineraryStore = Depends(get_store),
) -> dict:
    body = service.list_groups(itinerary_id or None)
    # 2026-10-30 看板卡标注所属行程（行程ID + 行程名）：行程名 = 城市链
    # （H5 行程页同款展示），行程已删/查无记录 → None（前端只显示 ID）；
    # 同一行程只查一次 store。
    names: dict[str, str | None] = {}
    for group in body.values():
        for item in group:
            trip_id = item.get("itinerary_id")
            if not trip_id:
                continue
            if trip_id not in names:
                record = store.get(trip_id)
                names[trip_id] = " → ".join(record.plan.cities) if record else None
            item["itinerary_name"] = names[trip_id]
    return body


@router.get("/{item_id}")
async def get_trip_item(
    item_id: str,
    service: TripItemService = Depends(get_trip_item_service),
) -> dict:
    item = service.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not_found")
    return item


@router.patch("/{item_id}")
async def patch_trip_item(
    item_id: str,
    request: PatchTripItemRequest,
    service: TripItemService = Depends(get_trip_item_service),
) -> dict:
    try:
        return service.update(
            item_id,
            status=request.status,
            day=request.day,
            position=request.position,
            note=request.note,
            city=request.city,
            booking_id=request.booking_id,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="not_found") from None
    except InvalidTransitionError:
        raise HTTPException(status_code=422, detail="invalid_transition") from None


@router.delete("/{item_id}", status_code=204)
async def delete_trip_item(
    item_id: str,
    service: TripItemService = Depends(get_trip_item_service),
) -> None:
    try:
        service.delete(item_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="not_found") from None
    except InvalidTransitionError:
        # Booked items must be un-booked first (§5 timeline integrity).
        raise HTTPException(status_code=422, detail="invalid_transition") from None
