"""预约自动化三档端点（L1/L2/L3，2026-10-25 用户拍板：全建+可选档）。

GET  /booking-auto/tiers           档位目录（选择器数据源，含降级注记）
POST /booking-auto/tasks           L1：行程放票任务清单（行前抢票日历）
POST /booking-auto/check           L2：库存状态（无联盟 key → unknown）
POST /booking-auto/order-intent    L3：预填下单链接（支付动作永远归用户）
POST /booking-auto/select          档位选择（设备级记忆，客户自选）
"""

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, load_only, sessionmaker

from app.models import Poi
from app.services.booking_auto import (
    availability_tiers_safe,
    build_order_intent,
    build_reservation_tasks,
    check_availability,
)
from app.services.lang_ctx import L

logger = logging.getLogger(__name__)

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


def get_show_session_factory() -> sessionmaker[Session]:
    """Indirection over db.get_session_factory so tests can override
    (dependency_overrides) without touching the lru_cache'd engine."""
    from app.db import get_session_factory

    return get_session_factory()


class ShowCard(BaseModel):
    """预订页 🎭 分区单条演出（04 CSV 底库投影）。"""

    name: str
    name_en: str | None = None
    city: str | None = None
    booking_url: str | None = None
    note: str | None = None
    has_direct: bool = False


@router.get("/shows")
async def shows(
    city: str | None = Query(default=None, max_length=50),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=30, ge=1, le=100),
    factory: Callable[[], Session] = Depends(get_show_session_factory),
) -> dict:
    """演出票务目录：H5 预订页「🎭 演出」分区数据源（show_booking §2）。"""
    return await _catalog("show", city, q, limit, factory)


@router.get("/sites")
async def sites(
    city: str | None = Query(default=None, max_length=50),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=30, ge=1, le=100),
    factory: Callable[[], Session] = Depends(get_show_session_factory),
) -> dict:
    """景点门票目录：H5 预订页「🎫 景点」分区数据源（/shows 同构）。"""
    return await _catalog("site", city, q, limit, factory)


# 「🎫 景点」候选集：可售门票的旅游品类（entertainment 归 🎭 演出分区）
_SITE_CATEGORIES = ("attraction", "museum", "theme_park", "park", "nature", "viewpoint")


async def _catalog(
    kind: str,
    city: str | None,
    q: str | None,
    limit: int,
    factory: Callable[[], Session],
) -> dict:
    """kind=show：category=entertainment 或 bvt=show；kind=site：旅游品类全量。

    带 booking_url（渠道直达 SKU）的排前；site 再按 rating 热度。DB
    不可用 → 503 诚实失败（铁律：失败必须留日志，不静默编造空列表）。
    """
    from app.api.pois import _city_variants
    from app.services.agent.plan import CITY_ALIASES

    # 双语输入：英文城市名（beijing / xi'an）先归一中文再匹配
    city = CITY_ALIASES.get((city or "").strip().lower(), city)

    try:
        with factory() as session:
            query = (
                session.query(Poi)
                .options(
                    load_only(
                        Poi.name_zh,
                        Poi.name_en,
                        Poi.city,
                        Poi.booking_url,
                        Poi.rating,
                        Poi.intro,
                        Poi.intro_en,
                    )
                )
                .filter(
                    or_(Poi.category == "entertainment", Poi.best_visit_time == "show")
                    if kind == "show"
                    else Poi.category.in_(_SITE_CATEGORIES)
                )
            )
            variants = _city_variants(city or "")
            if variants:
                # 04 CSV 库的 city 多为复合形态（酒泉（敦煌）/郑州（中牟）），
                # 精确 in_ 会漏；补 contains 让「敦煌」命中「酒泉（敦煌）」。
                bare = variants[0]
                query = query.filter(
                    or_(Poi.city.in_(variants), Poi.city.ilike(f"%{bare}%"))
                )
            if q and q.strip():
                like = f"%{q.strip()}%"
                query = query.filter(
                    or_(Poi.name_zh.ilike(like), Poi.name_en.ilike(like))
                )
            order = (
                [Poi.booking_url.is_(None), Poi.name_zh]
                if kind == "show"
                else [
                    Poi.booking_url.is_(None),
                    Poi.rating.desc().nullslast(),
                    Poi.name_zh,
                ]
            )
            rows = query.order_by(*order).limit(limit).all()
    except Exception:
        logger.error("%s: poi store unavailable", kind, exc_info=True)
        raise HTTPException(status_code=503, detail="poi store unavailable") from None
    cards = [
        ShowCard(
            name=r.name_zh or "",
            name_en=r.name_en,
            city=r.city,
            booking_url=r.booking_url,
            note=(r.intro or r.intro_en or "")[:120] or None,
            has_direct=bool(r.booking_url),
        ).model_dump()
        for r in rows
    ]
    return {"shows": cards}


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
            refund_summary=L(
                "人工渠道预订，退改以下单页为准（铁律 23 C 级）",
                "Manual-channel booking; changes and refunds follow the checkout page",
            ),
        )
        handoff_id = record.id
    except Exception:  # 失败留日志，不阻塞跳转（回填仍可手动建单）
        logger.warning(
            "order_intent: handoff create failed, name=%s city=%s url=%s",
            request.name,
            request.city,
            intent.authorization_url,
            exc_info=True,
        )
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
