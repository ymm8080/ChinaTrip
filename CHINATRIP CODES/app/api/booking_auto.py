"""预约自动化三档端点（L1/L2/L3，2026-10-25 用户拍板：全建+可选档）。

GET  /booking-auto/tiers           档位目录（选择器数据源，含降级注记）
POST /booking-auto/tasks           L1：行程放票任务清单（行前抢票日历）
POST /booking-auto/check           L2：库存状态（无联盟 key → unknown）
POST /booking-auto/order-intent    L3：预填下单链接（支付动作永远归用户）
POST /booking-auto/select          档位选择（设备级记忆，客户自选）
"""

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.booking_auto import (
    availability_tiers_safe,
    build_order_intent,
    build_reservation_tasks,
    check_availability,
)

router = APIRouter(prefix="/api/v1/booking-auto", tags=["booking-auto"])

# 设备级档位选择（MVP 内存态；登录态接入后随账号走）
_tier_choice: dict[str, str] = {}


def _device(x_device_id: str | None) -> str:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    return x_device_id


@router.get("/tiers")
async def tiers() -> dict:
    return {"tiers": availability_tiers_safe()}


class TasksRequest(BaseModel):
    visits: list[dict] = Field(min_length=1, max_length=100)
    start_date: str | None = None


@router.post("/tasks")
async def tasks(request: TasksRequest) -> dict:
    return {
        "tasks": [
            t.model_dump()
            for t in build_reservation_tasks(
                request.visits, start_date=request.start_date
            )
        ]
    }


class CheckRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=50)
    visit_date: str = Field(min_length=5, max_length=10)
    provider: str = "klook"


@router.post("/check")
async def check(request: CheckRequest) -> dict:
    status = await check_availability(
        request.name, request.city, request.visit_date, provider=request.provider
    )
    return {"name": request.name, "availability": status.value}


class OrderIntentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=50)
    tier: str = Field(default="L3", pattern="^L[123]$")
    booking_url: str | None = Field(default=None, max_length=500)


def _channel_of(url: str) -> str:
    """链接域名 → 回填渠道口径（Trip.com=携程国际品牌归 ctrip）。"""
    host = url.lower()
    if "trip.com" in host:
        return "ctrip"
    if "klook" in host:
        return "klook"
    if "meituan" in host:
        return "meituan"
    if "ctrip" in host:
        return "ctrip"
    return "other"


@router.post("/order-intent")
async def order_intent(
    request: OrderIntentRequest,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    *,
    tpl_request: Request,
) -> dict:
    """L3 伪闭环（2026-10-25，ACP 就绪前的等价体验）：发起即落
    action_handoffs 留痕（opened）——用户渠道付款后回来「订单 → 粘贴
    回填」走 apply_paste_return → user_confirmed，联盟同步后
    alliance_verified。三段全在既有管道，本端点只补发起埋点。"""
    from app.services.geo_split import (
        booking_channel_for_ip,
        booking_search_url,
        client_ip,
    )

    ip = client_ip(
        x_forwarded_for,
        tpl_request.client.host if tpl_request and tpl_request.client else None,
    )
    channel_geo = booking_channel_for_ip(ip)  # 境内=meituan / 境外=tripcom
    auto_url = booking_search_url(channel_geo, request.name, request.city)
    intent = build_order_intent(
        request.name,
        request.city,
        requested=request.tier,
        booking_url=request.booking_url or auto_url,
    )
    handoff_id: str | None = None
    try:
        from app.api.backfill import get_handoff_store

        record = get_handoff_store().create(
            action_type="site_ticket",
            channel=_channel_of(intent.authorization_url),
            url=intent.authorization_url,
            refund_summary="人工渠道预订，退改以下单页为准（铁律 23 C 级）",
        )
        handoff_id = record.id
    except Exception:  # 留痕失败不阻塞跳转（回填仍可手动建单）
        pass
    return {
        **intent.model_dump(),
        "handoff_id": handoff_id,
        "geo_channel": channel_geo,
        "client_ip": ip,
    }


class TierSelectRequest(BaseModel):
    tier: str = Field(pattern="^L[123]$")


@router.post("/select")
async def select_tier(
    request: TierSelectRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> dict:
    device = _device(x_device_id)
    _tier_choice[device] = request.tier
    return {"device": device, "tier": request.tier}


@router.get("/selected")
async def selected_tier(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> dict:
    device = _device(x_device_id)
    return {"device": device, "tier": _tier_choice.get(device, "L1")}
