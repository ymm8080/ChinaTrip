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

from app.api.itineraries import _account_from_auth
from app.models import Poi
from app.services.booking_auto import (
    availability_tiers_safe,
    build_order_intent,
    build_reservation_tasks,
    check_availability,
    restaurant_booking_link,
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
    # 营业时间/场次串（poi.opening_hours 透传；演出行多为「仅夜场约
    # 20:10/21:35两场」类场次文本——2026-11-04 用户反馈目录页无场次补）
    opening_hours: str | None = None
    opening_hours_en: str | None = None
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
                        Poi.opening_hours,
                        Poi.opening_hours_en,
                    )
                )
                .filter(
                    or_(Poi.category == "entertainment", Poi.best_visit_time == "show")
                    if kind == "show"
                    else Poi.category.in_(_SITE_CATEGORIES)
                )
                # 退役闸：考古遗址退役(11-04)后带 booking_url 的 retired 行
                # 不得再出现在订票页——与主池 poi_details 同口径
                .filter((Poi.status.is_(None)) | (Poi.status == "active"))
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
            opening_hours=r.opening_hours,
            opening_hours_en=r.opening_hours_en,
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


class RestaurantIntentRequest(BaseModel):
    """🍴 餐位/餐厅美团预订意图请求（2026-11-07 用户拍板）。

    traveler_id 缺省取登记列表第一条（个人主页「出行人资料」顺序）；
    未登记 → contact=None 诚实缺省（不编造资料）。
    """

    name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=50)
    traveler_id: str | None = Field(default=None, max_length=64)


@router.post("/restaurant-intent")
async def restaurant_intent(
    request: RestaurantIntentRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    """🍴 餐位/餐厅美团预订意图（2026-11-07 用户拍板：行程卡餐位旁按钮直达）。

    跳美团美食频道搜店（restaurant_booking_link，商户页=订座/点单菜单）。
    出行人资料以**脱敏形态**挂响应与跳转埋点（travelers 层隐私纪律：
    证件号/手机号明文永不出服务层）——美团侧表单由用户本人账号登录
    自动带入，平台不提供第三方预填，诚实口径不编造。跳转即落
    action_handoffs（action_type=restaurant），H5 起每 2 分钟轮询
    GET /backfill/handoffs/{id} 直到离开 opened（粘贴回填/手动标记），
    即「scheduler every 2 minutes till complete」。铁律 22：下单与
    支付动作永远在渠道侧，本端点只留痕与跟踪。
    """
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    url = restaurant_booking_link(request.name, request.city)
    intent = build_order_intent(
        request.name,
        request.city,
        requested="L3",
        booking_url=url,
    )
    contact = _registered_contact(x_device_id, account, request.traveler_id)
    handoff_id: str | None = None
    try:
        from app.api.backfill import get_handoff_store

        record = get_handoff_store().create(
            action_type="restaurant",
            channel=_channel_of(url),
            url=url,
            refund_summary=L(
                "人工渠道预订，退改以下单页为准（铁律 23 C 级）",
                "Manual-channel booking; changes and refunds follow the checkout page",
            ),
        )
        handoff_id = record.id
    except Exception:  # 失败留日志，不阻塞跳转（回填仍可手动建单）
        logger.warning(
            "restaurant_intent: handoff create failed, name=%s city=%s url=%s",
            request.name,
            request.city,
            url,
            exc_info=True,
        )
    return {
        **intent.model_dump(),
        "handoff_id": handoff_id,
        "contact": contact,
    }


def _registered_contact(
    x_device_id: str,
    account: str | None,
    traveler_id: str | None,
) -> dict | None:
    """出行人资料脱敏投影（travelers 层同 owner 口径：登录账号/匿名设备）。

    travelers 层不可用（库缺席等）→ None + 留日志，不阻塞跳转。
    """
    try:
        from app.api.travelers import get_travelers_service

        owner = account if account else f"device:{x_device_id}"
        rows = get_travelers_service().list_for_owner(owner)
        pick = None
        if traveler_id:
            pick = next((t for t in rows if t.get("id") == traveler_id), None)
        if pick is None and rows:
            pick = rows[0]
        if pick is None:
            return None
        return {
            "traveler_id": pick.get("id"),
            "label": pick.get("label") or None,
            "name": (pick.get("full_name_zh") or pick.get("full_name_en") or "")
            or None,
            "name_en": pick.get("full_name_en") or None,
            "phone_masked": pick.get("phone_masked") or None,
        }
    except Exception:
        logger.warning("restaurant_intent: traveler contact unavailable", exc_info=True)
        return None


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
