"""Trip-center item API (design v2.4 §5/§4) — thin shell over
TripItemService.

Every write path (manual form / chat / paste / agent recommendation) lands
in the same table (iron rule 0), and the timeline page reads that one
source: Bookings pinned on top + Wishlist stream + Scheduled third key.
The router is NOT registered in app/main.py — the orchestrator wires it.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from app.api.itineraries import _account_from_auth, get_store
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


def _city_from_library(name: str) -> str | None:
    """建行即定城（2026-11-13 用户拍板「心愿单的城市必须在插入的时候就
    标注城市」）：POIS 底库同名行的城市唯一 → 采用；多城/无行 → 留空，
    交给规划回合追问。Best-effort——库不可用不影响建行（留痕）。"""
    probe = (name or "").strip()
    if not probe:
        return None
    try:
        from app.services.poi_details import get_poi_detail_store

        hits = get_poi_detail_store().search_keyword(None, [probe], limit=20)
    except Exception:
        logger.warning("trip-items: city resolve failed for %s", probe, exc_info=True)
        return None
    cities = {
        (h.get("city") or "").strip().removesuffix("市")
        for h in hits or []
        if isinstance(h, dict)
        and (h.get("name") or "").strip() == probe
        and (h.get("city") or "").strip()
    }
    cities.discard("")
    return cities.pop() if len(cities) == 1 else None


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
    # 用户原话（2026-11-13 心愿单数据库 raw_command）
    raw_command: str | None = Field(default=None, max_length=1000)
    kind: str | None = Field(default=None, max_length=20)


class PatchTripItemRequest(BaseModel):
    status: str | None = Field(default=None, max_length=16)  # state machine checks
    day: int | None = Field(default=None, ge=1)
    position: float | None = None
    note: str | None = Field(default=None, max_length=2000)
    city: str | None = Field(default=None, max_length=64)
    booking_id: str | None = Field(default=None, max_length=128)


def _ensure_owned(service: TripItemService, item_id: str, device: str | None) -> None:
    """看板行归属闸（2026-11-13 数据库事实化）：行有归属设备且与请求
    设备不符 → 404（防枚举口径）；无归属（历史行）放行。"""
    if not device:
        return
    row = service.get(item_id)
    owner = (row or {}).get("owner_device_id")
    if owner and owner != device:
        raise HTTPException(status_code=404, detail="not_found")


@router.post("", status_code=201)
async def create_trip_item(
    request: CreateTripItemRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    city = request.city
    if not (city or "").strip():
        # 2026-11-13（用户拍板「心愿单的城市必须在插入的时候就标注城市」）：
        # 建行当口能定城就定，不定就留空等追问——绝不把没城的行塞进
        # 任何行程（跨城串行程的根）。
        city = _city_from_library(request.name)
        if not city:
            logger.warning("trip-items: create without city name=%s", request.name)
    # POIS 建行带属性（2026-11-13 用户拍板）：类别/时长/档位/坐标/rain_ok
    from app.services.wish_seed import seed_from_pois

    seed = seed_from_pois(request.name, city)
    try:
        return service.create(
            request.name,
            source=request.source,
            itinerary_id=request.itinerary_id,
            # 2026-11-13：建行即落设备归属（看板按设备读，别的会话改不到）
            owner_device_id=x_device_id,
            # 心愿单数据库 CREATED BY（2026-11-13 用户拍板）
            created_by=x_device_id,
            # 2026-11-14（用户拍板「心愿单按 USER ID 出内容」）：登录账号随行
            owner_account_id=account,
            city=city,
            note=request.note,
            poi_id=request.poi_id,
            address=request.address,
            opening_hours=request.opening_hours,
            raw_command=request.raw_command or request.note,
            kind=request.kind or seed.get("kind"),
            duration_minutes=seed.get("duration_minutes"),
            tier=seed.get("tier"),
            site_rank=seed.get("site_rank"),
            latitude=seed.get("latitude"),
            longitude=seed.get("longitude"),
            rain_ok=seed.get("rain_ok"),
        )
    except InvalidSourceError:
        raise HTTPException(status_code=422, detail="invalid_source") from None


@router.get("")
async def list_trip_items(
    itinerary_id: str | None = None,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
    store: ItineraryStore = Depends(get_store),
    response: Response = None,
    account: str | None = Depends(_account_from_auth),
) -> dict:
    # 2026-11-13（用户拍板「看板就是数据库的数据」）：按设备读自己的行。
    # 2026-11-14（用户拍板「没保存行程，心愿单不该保存」）：会话草稿行
    # 只在规划引擎内部可见——看板一律不返回，保存行程后才出现。
    # 2026-11-14（用户拍板「行程中心显示数据库信息，不吃缓存」）：看板
    # 读口永不缓存——浏览器/SW 任何一层缓存都会让删掉的心愿闪回。
    if response is not None:
        response.headers["Cache-Control"] = "no-store"
    # 2026-11-14（用户拍板「打开行程中心按 USER ID 出内容」）：本设备 +
    # 本登录账号的行都算「我的」；登录后换设备也看得到。
    body = service.list_groups(
        itinerary_id or None,
        x_device_id or None,
        account,
        include_drafts=False,
    )
    # 2026-11-13 拍板「已排期只放已排的心愿单」：source=plan 是旧版自动
    # 补源/翻牌残渣，不是用户心愿——看板读口兜底清除（scheduled +
    # wishlist），历史库/旁路写入/其他进程旧码产生的引擎行即时消失。
    # booked 真实订单保留（订单栏自有真相）。与 plan._sync_planned_rows
    # 同口径，双保险。
    for group_name in ("scheduled", "wishlist"):
        for item in list(body.get(group_name) or []):
            if item.get("source") != "plan":
                continue
            try:
                service.delete(item["id"])
            except Exception:
                logger.warning(
                    "trip-items: engine planned row delete failed id=%s group=%s",
                    item.get("id"),
                    group_name,
                    exc_info=True,
                )
                continue
            body[group_name].remove(item)
    # 2026-11-12 死行程闸判活（「排上了还在心愿单」振荡根因）：聊天重排换
    # 新 itinerary_id 且按 10-20 拍板未入库，store.get miss ≠ 行程已删——
    # 以本设备在册会话的工作行程 id 豁免回翻。会话存储单例与 plan 端点
    # 共享（函数体内延迟导入防模块环）；查不动就退化为旧行为（保守回翻）。
    live: set[str] = set()
    # 2026-11-13（熊猫/环球中心被打回心愿单案）：判活不可得时不得判死。
    # 无 X-Device-ID（看板轮询/其他端）或活表查不动 → live_known=False，
    # 本趟不做「行程已删」回翻；否则一次缺参请求就能把已排期的行打回
    # 心愿单（scheduled↔wishlist 振荡）。
    live_known = False
    if x_device_id:
        try:
            from app.api.plan import get_plan_sessions

            live = get_plan_sessions().live_itinerary_ids(x_device_id)
            live_known = True
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
                if record is None and live_known and trip_id not in live:
                    dead_trips.add(trip_id)
            item["itinerary_name"] = names[trip_id]
    # 2026-10-31（看熊猫案）：scheduled 行挂的行程已删（释放机制上线前
    # 的存量孤儿/旁路删除）——已排期栏必须真实。用户来源行
    # （chat/manual/paste/agent_recommend）就地回心愿单（note 剥「已安排」
    # 尾段，service.update 写穿 PG），本次响应即按新分组返回。
    # source=plan 引擎行已在上方统一清除（2026-11-13 已排期只放心愿单）。
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
    if item is None or item.get("draft_session_id"):
        # 草稿行（未保存行程）对外不存在——与看板读口同口径
        raise HTTPException(status_code=404, detail="not_found")
    return item


@router.patch("/{item_id}")
async def patch_trip_item(
    item_id: str,
    request: PatchTripItemRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
) -> dict:
    _ensure_owned(service, item_id, x_device_id)
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
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
) -> None:
    _ensure_owned(service, item_id, x_device_id)
    try:
        # 软删（DELETION FLAG + 日期/时间/人）：行留在库里可审计，看板不显示
        service.delete(item_id, actor=x_device_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="not_found") from None
    except InvalidTransitionError:
        # Booked items must be un-booked first (§5 timeline integrity).
        raise HTTPException(status_code=422, detail="invalid_transition") from None
