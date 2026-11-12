"""Trip-center item API (design v2.4 §5/§4) — thin shell over
TripItemService.

Every write path (manual form / chat / paste / agent recommendation) lands
in the same table (iron rule 0), and the timeline page reads that one
source: Bookings pinned on top + Wishlist stream + Scheduled third key.
The router is NOT registered in app/main.py — the orchestrator wires it.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.itineraries import get_store
from app.db import get_session_factory
from app.services.itinerary_store import ItineraryStore
from app.services.pg_state import PgTripItemService
from app.services.trip_items import (
    STATUS_WISHLIST,
    InvalidSourceError,
    InvalidTransitionError,
    NotFoundError,
    TripItemService,
    strip_scheduled_note,
)

logger = logging.getLogger(__name__)

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
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
    store: ItineraryStore = Depends(get_store),
) -> dict:
    body = service.list_groups(itinerary_id or None)
    # 2026-11-12 死行程闸判活（「排上了还在心愿单」振荡根因）：聊天重排换
    # 新 itinerary_id 且按 10-20 拍板未入库，store.get miss ≠ 行程已删——
    # 以本设备在册会话的工作行程 id 豁免回翻。会话存储单例与 plan 端点
    # 共享（函数体内延迟导入防模块环）；查不动就退化为旧行为（保守回翻）。
    live: set[str] = set()
    if x_device_id:
        try:
            from app.api.plan import get_plan_sessions

            live = get_plan_sessions().live_itinerary_ids(x_device_id)
        except Exception:
            logger.warning("trip-items: live-itin check failed", exc_info=True)
    # 2026-10-30 看板卡标注所属行程（行程ID + 行程名）：行程名 = 城市链
    # （H5 行程页同款展示），行程已删/查无记录 → None（前端只显示 ID）；
    # 同一行程只查一次 store。
    names: dict[str, str | None] = {}
    dead_trips: set[str] = set()
    for group in body.values():
        for item in group:
            trip_id = item.get("itinerary_id")
            if not trip_id:
                continue
            if trip_id not in names:
                record = store.get(trip_id)
                names[trip_id] = " → ".join(record.plan.cities) if record else None
                if record is None and trip_id not in live:
                    dead_trips.add(trip_id)
            item["itinerary_name"] = names[trip_id]
    # 2026-10-31（看熊猫案）：scheduled 行挂的行程已删（释放机制上线前
    # 的存量孤儿/旁路删除）——已排期栏必须真实：就地回心愿单（note 剥
    # 「已安排」尾段，service.update 写穿 PG），本次响应即按新分组返回。
    # booked 行保留真实订单；无归属（itinerary_id 空）的 scheduled 行留给
    # 状态机，不猜测。
    if dead_trips and body.get("scheduled"):
        for item in list(body["scheduled"]):
            trip_id = item.get("itinerary_id")
            if not trip_id or trip_id not in dead_trips:
                continue
            raw_note = str(item.get("note") or "")
            base = strip_scheduled_note(raw_note)
            kwargs: dict = {}
            if base != raw_note:
                kwargs["note"] = base
            try:
                healed = service.update(item["id"], status=STATUS_WISHLIST, **kwargs)
            except Exception:
                continue
            body["scheduled"].remove(item)
            healed["itinerary_name"] = names.get(trip_id)
            body["wishlist"].append(healed)
        body["wishlist"].sort(key=lambda i: i.get("created_at") or "", reverse=True)
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
