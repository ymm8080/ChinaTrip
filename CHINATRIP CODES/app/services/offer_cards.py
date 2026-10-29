# -*- coding: utf-8 -*-
"""转链交易中心·候选卡片组组装（设计 v2.3 §6.11 新增子节）。

App 内不下单：候选卡片组=同一商品 2–4 张渠道卡（平台名+实时报价+退改摘要），
用户选卡跳转渠道页成交（铁律 22 只 handoff 不代客交易）。
生成逻辑=确定性五步 workflow（查询→去重比价→排序→生成深链→展示），非 agent 循环。

- 不显示佣金；排序佣金权重为零（写死）：排序键=价格+稳定性，
  本模块（含卡片结构）不存在佣金字段。
- 卡片组顶部固定 disclaimer「*价格以跳转后页面为准*」；12306 标「全国统一价」；
  不足 2 渠道只显示 1 张（不硬凑）；默认形态=单个主推+可展开全部。
- 国外场景（region=overseas）隐藏美团卡。
- MVP 报价=确定性 mock：规范化参数串 sha256 作种子推导渠道偏移（±12%），
  同请求恒同价、跨进程可复现；禁 random 模块（随机必须可复现）。
- 深链复用 bookings.py 的渠道 URL 组装；追踪参数（allianceId/sid）仅服务端
  注入，前端只拿成品 URL；全部链接无 key。零网络、零第三方依赖。
"""

import hashlib
from urllib.parse import quote

from app.config import Settings
from app.services.bookings import (
    _refund_channel_page,
    flight_booking,
    hotel_booking,
    train_booking,
)
from app.services.lang_ctx import L
from app.services.trains import get_train_service

__all__ = ["flight_offer_cards", "hotel_offer_cards", "train_offer_cards"]

# 稳定性序（同价时的次序）：携程 > 去哪儿 > 美团
_STABILITY_ORDER = ("ctrip", "qunar", "meituan")

# MVP 确定性 mock 基价（元）；接入真实联盟 API 后替换 _mock_price_yuan 即可
_BASE_PRICE_YUAN: dict[str, float] = {"hotel": 350.0, "flight": 760.0}
_PRICE_BAND = 0.12  # 各渠道在基价 ±12% 内偏移
_SAME_PRICE_EPS = 0.005  # |a-b| < eps 视为同价

_DISCLAIMER = "*价格以跳转后页面为准*"  # zh 原文（EN 见 _disclaimer）
_LAYOUT = "primary_plus_expand"  # 默认形态：单个主推 + 可展开全部

_UNIFIED_TAG = "全国统一价"  # zh 原文（EN 见 _unified_tag）
_SAME_PRICE_TAG = "同价"  # zh 原文（EN 见 _same_price_tag）


def _disclaimer() -> str:
    return L(_DISCLAIMER, "*Final price as shown on the destination page*")


def _unified_tag() -> str:
    # EN wording must stay identical to i18n.js bk.unified: the H5 card
    # renderer suppresses the badge by exact string match.
    return L(_UNIFIED_TAG, "Nationwide flat price")


def _same_price_tag() -> str:
    return L(_SAME_PRICE_TAG, "Same price")


# meituan 不在 bookings.py 的退改摘要表内（那里携程文案已连带美团）；
# 卡片按渠道单列时给美团自己的铁律 23 兜底文案
_MEITUAN_REFUND_SUMMARY = "退改政策以美团下单页展示为准；建议选「免费取消」房型"


def _meituan_refund_summary() -> str:
    return L(
        _MEITUAN_REFUND_SUMMARY,
        "Refund policy per the Meituan checkout page; pick a 'free "
        "cancellation' room when possible",
    )


def _norm_query(kind: str, parts: dict[str, object]) -> str:
    """规范化参数串（价格种子的输入）：坐标定宽格式化，键排序后拼接。"""
    flat = {
        key: f"{value:.6f}" if key in ("lon", "lat") else str(value)
        for key, value in parts.items()
    }
    return kind + "|" + "|".join(f"{k}={flat[k]}" for k in sorted(flat))


def _mock_price_yuan(kind: str, channel: str, norm: str) -> float:
    """确定性 mock 报价：sha256(kind|channel|规范化参数) 前 8 字节映射为
    基价 ±12% 的偏移，四舍五入到元（因此允许两渠道撞出同价）。
    同一请求恒同价，跨进程可复现（纯哈希推导，不用 random）。
    """
    base = _BASE_PRICE_YUAN[kind]
    digest = hashlib.sha256(f"{kind}|{channel}|{norm}".encode("utf-8")).digest()
    ratio = int.from_bytes(digest[:8], "big") / float(1 << 64)
    offset = (ratio * 2.0 - 1.0) * _PRICE_BAND
    lo = base * (1.0 - _PRICE_BAND)
    hi = base * (1.0 + _PRICE_BAND)
    return float(round(min(max(base * (1.0 + offset), lo), hi)))


def _same_price_group(prices: dict[str, float]) -> list[str] | None:
    """同价组（比价结果）：与其他渠道价差 < eps 的渠道，按稳定性序；无则 None。"""
    group = [
        channel
        for channel in _STABILITY_ORDER
        if channel in prices
        and any(
            other != channel and abs(prices[other] - prices[channel]) < _SAME_PRICE_EPS
            for other in prices
        )
    ]
    return group or None


def _order_by_price_then_stability(cards: list[dict]) -> list[dict]:
    """排序：价格升序，同价按稳定性（携程>去哪儿>美团）。

    佣金权重为零（写死）：排序键只有价格+稳定性，不存在佣金字段。
    """

    def sort_key(card: dict) -> tuple[float, int]:
        channel = str(card["channel"])
        rank = (
            _STABILITY_ORDER.index(channel)
            if channel in _STABILITY_ORDER
            else len(_STABILITY_ORDER)
        )
        return (float(card["price_yuan"]), rank)

    return sorted(cards, key=sort_key)


def _inject_tracking(url: str, settings: Settings) -> str:
    """追踪参数服务端注入：alliance_id 与 alliance_sid 皆非空才追加，否则原样。"""
    if not (settings.alliance_id and settings.alliance_sid):
        return url
    sep = "&" if "?" in url else "?"
    return (
        f"{url}{sep}allianceId={quote(settings.alliance_id, safe='')}"
        f"&sid={quote(settings.alliance_sid, safe='')}"
    )


def _refund_summary(channel: str) -> str:
    """铁律 23：每张卡必带退改摘要；复用 bookings.py 的渠道文案。"""
    if channel == "meituan":
        return _meituan_refund_summary()
    return _refund_channel_page(channel)["summary"]


def _present(kind: str, cards: list[dict], group: list[str] | None) -> dict:
    """步骤5 展示：主推=排序后第一张；cards 含全部（≥1，不足 2 渠道=1 张）。"""
    return {
        "kind": kind,
        "disclaimer": _disclaimer(),
        "layout": _LAYOUT,
        "primary": cards[0],
        "cards": cards,
        "same_price_group": group,
    }


def _assemble(
    kind: str, channel_urls: dict[str, str], *, norm: str, settings: Settings
) -> dict:
    """五步 workflow 第 2–5 步：去重比价 → 排序 → 生成深链 → 展示。"""
    # 步骤2 去重比价：渠道以 dict 键收纳（同渠道天然去重）+ 确定性报价 + 同价组
    prices = {ch: _mock_price_yuan(kind, ch, norm) for ch in channel_urls}
    group = _same_price_group(prices)
    cards = [
        {
            "channel": channel,
            "price_yuan": price,
            "unified_price": False,
            "tag": _same_price_tag() if group and channel in group else None,
            "refund_summary": _refund_summary(channel),
            "url": channel_urls[channel],
        }
        for channel, price in prices.items()
    ]
    # 步骤3 排序：佣金权重为零（价格升序 + 稳定性序）
    cards = _order_by_price_then_stability(cards)
    # 步骤4 生成深链：成品 URL 出厂前服务端注入追踪参数
    for card in cards:
        card["url"] = _inject_tracking(card["url"], settings)
    return _present(kind, cards, group)


def hotel_offer_cards(
    city: str,
    near_poi_name: str,
    *,
    lon: float,
    lat: float,
    checkin: str,
    checkout: str,
    region: str = "cn",
    settings: Settings,
) -> dict:
    """酒店候选卡（步骤1 查询）：cn=携程+美团；overseas 隐藏美团卡（只剩 1 张）。

    坐标/日期校验沿用 bookings.hotel_booking 既有口径，不合法抛 ValueError。
    """
    handoff = hotel_booking(
        city, near_poi_name, lon=lon, lat=lat, checkin=checkin, checkout=checkout
    )["handoff"]
    channel_urls = {"ctrip": handoff["url"], "meituan": handoff["fallback"]["url"]}
    if region == "overseas":
        channel_urls.pop("meituan")
    norm = _norm_query(
        "hotel",
        {
            "city": city,
            "poi": near_poi_name,
            "lon": lon,
            "lat": lat,
            "checkin": checkin,
            "checkout": checkout,
            "region": region,
        },
    )
    return _assemble("hotel", channel_urls, norm=norm, settings=settings)


def flight_offer_cards(
    from_city: str,
    to_city: str,
    date: str,
    *,
    region: str = "cn",
    settings: Settings,
) -> dict:
    """机票候选卡（步骤1 查询）：携程主渠道+去哪儿兜底（机票无美团卡）。"""
    handoff = flight_booking(from_city, to_city, date)["handoff"]
    channel_urls = {
        handoff["channel"]: handoff["url"],
        handoff["fallback"]["channel"]: handoff["fallback"]["url"],
    }
    norm = _norm_query(
        "flight",
        {"from": from_city, "to": to_city, "date": date, "region": region},
    )
    return _assemble("flight", channel_urls, norm=norm, settings=settings)


async def train_offer_cards(
    from_city: str, to_city: str, date: str, *, settings: Settings
) -> dict:
    """火车票候选卡：恰 1 张 12306「全国统一价」卡（无可比渠道，恒首位单卡）。

    URL 复用 bookings.train_booking 的 12306 拼法（电报码缺失时城市双写槽位）。
    """
    handoff = (
        await train_booking(
            from_city, to_city, date, train_service=get_train_service(settings)
        )
    )["handoff"]
    card = {
        "channel": handoff["channel"],
        "price_yuan": None,
        "unified_price": True,
        "tag": _unified_tag(),
        "refund_summary": _refund_summary(handoff["channel"]),
        "url": _inject_tracking(handoff["url"], settings),
    }
    return _present("train", [card], None)
