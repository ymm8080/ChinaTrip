"""预约自动化三档栈（L1 提醒直达 / L2 库存感知 / L3 下单闭环，2026-10-25）。

用户拍板：L1/L2/L3 全建、档位自选；**非 ACP 闭环为主案**（用户定调
2026-10-25：ACP 不可用就走非 ACP 解——发起埋点→渠道支付→粘贴回填
确认→联盟对账，三段全通即产品完整形态）。ACP/UCP 降为观察项（不
依赖）：协议被 OTA 接入后换 channel 实现不动架构（OrderChannel
扩展位保留）。

铁律 22 边界不变：L3 支付动作永远由用户在渠道侧完成。

  L1 remind+deeplink  放票任务（提前 N 天 · release 时刻）+ 带参直达
  L2 availability      库存状态（ok/low/sold_out/unknown）——
                       Klook/Trip.com 联盟 key 未配时 honest unknown
  L3 order-intent      预填下单链接 + requires_user_confirmation=True
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import Enum
from typing import Protocol

from pydantic import BaseModel

from app.config import get_settings
from app.services.reservation_seeds import RESERVATION_V0


class BookingTier(str, Enum):
    L1 = "L1"  # 提醒 + 带参直达
    L2 = "L2"  # + 库存感知
    L3 = "L3"  # + 下单意图（用户确认支付）


_TIER_RANK = {"L1": 1, "L2": 2, "L3": 3}


class ReservationTask(BaseModel):
    """L1：一条放票抢票任务（行前清单项）。"""

    name: str
    city: str | None = None
    visit_date: str | None = None  # ISO
    advance_days: int
    release_time: str  # "HH:MM"
    open_date: str | None = None  # = visit_date - advance_days（开抢日）


class Availability(str, Enum):
    """L2 语义=「渠道可订性」而非「现场余量」（2026-10-25 用户纠偏）：

    预约制场馆（故宫/国博类免费票）的真实配额在官方微信小程序里，
    **任何联盟 API 都查不到**——Klook/Trip.com 卖的是代抢服务商品而
    非官方库存。对这批馆诚实返回 official_quota（不可查，走 L1 放票
    提醒/代抢）；商业付费 SKU（门票/演出/一日游）才有渠道库存可查。
    """

    ok = "ok"
    low = "low"
    sold_out = "sold_out"
    unknown = "unknown"
    #: 官方配额制（预约名单命中）：无渠道库存，永远不可查
    official_quota = "official_quota"


class OrderIntent(BaseModel):
    """L3：下单闭环（非 ACP 主案）——预填链接 + handoff 埋点 +
    粘贴回填收尾；支付动作永远留给用户（铁律 22）。"""

    name: str
    tier_used: BookingTier
    channel: str  # manual_confirm | acp（扩展位）
    authorization_url: str
    requires_user_confirmation: bool = True
    note: str | None = None


# --- 档位解析与降级 ----------------------------------------------------------


def resolve_tier(requested: str | BookingTier) -> tuple[BookingTier, str | None]:
    """请求档位 → 实际档位 + 降级注记（L2 无 key → L1；L3 无 ACP → L2/L1）。

    永不返回比 L1 低的档——L1 零依赖恒可用。
    """
    req = BookingTier(requested)
    settings = get_settings()
    # 国内库存主力=携程联盟/同程/美团（B 档个人可申请，库存最深）；
    # Klook/Trip.com 仅外国人下单面（2026-10-25 用户纠偏：中国票务
    # 库存不依赖 Klook/Trip.com）。任一 provider key 配好 L2 即活。
    if _TIER_RANK[req.value] >= 2 and not any(
        (
            settings.ctrip_union_api_key,
            settings.tongcheng_api_key,
            settings.meituan_api_key,
            settings.klook_api_key,
            settings.tripcom_api_key,
        )
    ):
        return (
            BookingTier.L1,
            "L2 降级 L1：库存 provider key 未配置"
            "（携程联盟/同程/美团为主力，任一配好即活）",
        )
    if req == BookingTier.L3:
        # 非 ACP 主案（2026-10-25 定调）：预填下单→渠道支付→粘贴回填，
        # 三段闭环即完整形态——不是等待 ACP 的过渡态
        return (
            BookingTier.L3,
            "L3 标准闭环：预填下单 → 渠道支付 → 回「订单」粘贴确认自动记录",
        )
    return req, None


def available_tiers() -> list[dict]:
    """档位目录（客户端选择器数据源）。"""
    out = []
    for tier in BookingTier:
        effective, fallback = resolve_tier(tier)
        out.append(
            {
                "tier": tier.value,
                "effective": effective.value,
                "available": effective == tier,
                "fallback_note": fallback,
            }
        )
    return out


#: 端点层别名（booking_auto 路由用）
availability_tiers_safe = available_tiers


# --- L1：放票任务 ------------------------------------------------------------


def _match_meta(name: str) -> dict | None:
    for seed_name, meta in RESERVATION_V0.items():
        if seed_name == (name or "").strip() or seed_name in (name or ""):
            return meta
    return None


def build_reservation_tasks(
    visits: list[dict],
    *,
    start_date: str | None,
) -> list[ReservationTask]:
    """visits = [{name, city, day}]（day 1 基）；命中名单的生成放票任务。

    start_date 缺失时 open_date 留空（提醒任务仍在，日期待补）。
    """
    tasks: list[ReservationTask] = []
    base = None
    if start_date:
        try:
            base = date.fromisoformat(start_date)
        except ValueError:
            base = None
    for v in visits:
        meta = _match_meta(v.get("name") or "")
        if meta is None:
            continue
        visit_date = None
        open_date = None
        if base is not None and v.get("day"):
            visit_date = (base + timedelta(days=int(v["day"]) - 1)).isoformat()
            open_date = (
                base + timedelta(days=int(v["day"]) - 1 - meta["days"])
            ).isoformat()
        tasks.append(
            ReservationTask(
                name=v.get("name") or "",
                city=v.get("city"),
                visit_date=visit_date,
                advance_days=meta["days"],
                release_time=meta.get("release") or "00:00",
                open_date=open_date,
            )
        )
    return tasks


# --- L1/L3：带参直达链接 -----------------------------------------------------


def booking_link_for(name: str, city: str | None = None) -> str:
    """直达链接：poi.booking_url 优先（调用方传入），缺省联盟搜索模板。

    联盟参数（alliance_id/sid，settings）双非空才附加——转链交易中心
    同款纪律：参数服务端注入，前端只拿成品 URL。
    """
    settings = get_settings()
    from urllib.parse import quote

    url = settings.booking_search_template.format(
        keyword=quote(f"{city or ''}{name}".strip() or name)
    )
    if settings.alliance_id and settings.alliance_sid:
        sep = "&" if "?" in url else "?"
        url += f"{sep}allianceid={settings.alliance_id}&sid={settings.alliance_sid}"
    return url


# --- L2：库存 Provider（协议 + 注册表；key 未配 → unknown） -------------------


class AvailabilityProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    async def check(
        self, name: str, city: str | None, visit_date: str
    ) -> Availability: ...


class NullAvailability:
    """无联盟 key 时的诚实缺省：unknown（不编造库存）。"""

    name = "null"

    def available(self) -> bool:
        return False

    async def check(self, name, city, visit_date) -> Availability:
        return Availability.unknown


_PROVIDERS: dict[str, AvailabilityProvider] = {"null": NullAvailability()}


def register_provider(provider: AvailabilityProvider) -> None:
    """联盟签约后注册（Klook/Trip.com adapter 就位即插）。"""
    _PROVIDERS[provider.name] = provider


async def check_availability(
    name: str, city: str | None, visit_date: str, *, provider: str = "klook"
) -> Availability:
    """按场馆类型分流（2026-10-25 用户纠偏）：

    预约名单命中 → official_quota（官方小程序配额，联盟 API 不覆盖，
    不查 provider、不编造）；商业 SKU → provider 渠道可订性。
    自产信号飞轮（远期）：poi_reviews「抢到/没抢到」标签聚合可给
    official_quota 场馆补经验性售罄规律——独家数据，渠道拿不到。
    """
    if _match_meta(name) is not None:
        return Availability.official_quota
    p = _PROVIDERS.get(provider) or _PROVIDERS["null"]
    if not p.available():
        return Availability.unknown
    return await p.check(name, city, visit_date)


# --- L3：下单意图 -------------------------------------------------------------


def build_order_intent(
    name: str,
    city: str | None = None,
    *,
    requested: str | BookingTier = BookingTier.L3,
    booking_url: str | None = None,
) -> OrderIntent:
    tier, note = resolve_tier(requested)
    url = booking_url or booking_link_for(name, city)
    return OrderIntent(
        name=name,
        tier_used=tier,
        channel="manual_confirm",
        authorization_url=url,
        requires_user_confirmation=True,
        note=note,
    )
