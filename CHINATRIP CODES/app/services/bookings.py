# -*- coding: utf-8 -*-
"""预订 handoff 组装（设计 v2.2 §6.11 行动编排 MVP：行程后订火车票/机票/酒店）。

铁律 22：只 handoff 不代客交易——产物仅为带参跳转链接，不代下单、不碰资金、零凭据。
铁律 23：无退改签摘要=禁止跳转——每个 handoff 必带 refund_policy；
渠道无结构化退改数据时明示「以渠道下单页为准」（source="channel_page"）。
全部链接无 key：渠道 URL 永不含密钥参数。
纯组装模块：零网络、零第三方依赖（train_service 由调用方注入）。
"""

import math
import re
from urllib.parse import quote

__all__ = ["flight_booking", "hotel_booking", "train_booking"]

# 中国范围（境外坐标交给渠道没有意义；同 deeplinks.py 口径）
_LON_MIN, _LON_MAX = 73.0, 136.0
_LAT_MIN, _LAT_MAX = 3.0, 54.0

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 铁律 23 兜底文案：渠道无结构化退改数据 ⇒ 明示以渠道下单页为准
_REFUND_SUMMARIES = {
    "12306": (
        "退改签以 12306 下单页展示为准"
        "（开车前8天以上退票免费，48小时~8天5%，24~48小时10%，<24小时20%——以页面实收为准）"
    ),
    "qunar": (
        "机票退改签以去哪儿/携程下单页展示为准（各航班舱位规则不同，以页面实收为准）"
    ),
    "ctrip": "退改政策以携程/美团下单页展示为准；建议选「免费取消」房型",
}


def _enc(name: str) -> str:
    """URL 里的中文名必须整体 URL 编码。"""
    return quote(name, safe="")


def _refund_channel_page(channel: str) -> dict:
    """退改签摘要（铁律 23）：渠道无结构化数据时明示以渠道下单页为准。"""
    return {"summary": _REFUND_SUMMARIES[channel], "source": "channel_page"}


def _validate_hotel(lon: float, lat: float, checkin: str, checkout: str) -> None:
    if not isinstance(lon, (int, float)) or not math.isfinite(lon):
        raise ValueError(f"lon must be a finite number, got {lon!r}")
    if not isinstance(lat, (int, float)) or not math.isfinite(lat):
        raise ValueError(f"lat must be a finite number, got {lat!r}")
    if not (_LON_MIN <= lon <= _LON_MAX):
        raise ValueError(f"lon {lon} out of China range [{_LON_MIN}, {_LON_MAX}]")
    if not (_LAT_MIN <= lat <= _LAT_MAX):
        raise ValueError(f"lat {lat} out of China range [{_LAT_MIN}, {_LAT_MAX}]")
    if not (_DATE_RE.match(checkin) and _DATE_RE.match(checkout)):
        raise ValueError(f"dates must be YYYY-MM-DD, got {checkin!r}/{checkout!r}")
    if checkin >= checkout:
        raise ValueError(f"checkin {checkin} must be earlier than checkout {checkout}")


async def train_booking(
    from_city: str, to_city: str, date: str, *, train_service
) -> dict:
    """火车票 handoff：静态时刻表透传 + 12306 余票页带参跳转。

    12306 电报码 MVP 拿不到，fs/ts 第二槽位重复城市名（页面能打开，
    日期参数透传）。班次为空（城市对未覆盖）时照样返回 handoff——渠道兜底。
    """
    trains = await train_service.search(from_city, to_city, date)
    fs = f"{_enc(from_city)},{from_city}"
    ts = f"{_enc(to_city)},{to_city}"
    return {
        "trains": [option.model_dump() for option in trains],
        "handoff": {
            "channel": "12306",
            "kind": "train",
            "url": (
                "https://kyfw.12306.cn/otn/leftTicket/init"
                f"?linktypeid=dc&fs={fs}&ts={ts}&date={date}"
            ),
            "app_scheme": "railway12326://",
        },
        "refund_policy": _refund_channel_page("12306"),
    }


def flight_booking(from_city: str, to_city: str, date: str) -> dict:
    """机票 handoff：MVP 无航班静态库，恒空列表 + 航程兜底。

    去哪儿 onewayList.htm 已软 404（1018 抓包+无头复核）→ 携程主渠道/去哪儿兜底。
    """
    return {
        "flights": [],
        "handoff": {
            "channel": "ctrip",
            "kind": "flight",
            "url": (
                "https://flights.ctrip.com/online/list/oneway-"
                f"{_enc(from_city)}-{_enc(to_city)}?depdate={date}"
            ),
            "fallback": {
                "channel": "qunar",
                "url": (
                    "https://flight.qunar.com/site/onewayList.htm"
                    f"?fromCity={_enc(from_city)}&toCity={_enc(to_city)}&fromDate={date}"
                ),
            },
        },
        "refund_policy": _refund_channel_page("ctrip"),
    }


def hotel_booking(
    city: str,
    near_poi_name: str,
    *,
    lon: float,
    lat: float,
    checkin: str,
    checkout: str,
) -> dict:
    """酒店 handoff：携程酒店列表带关键词+日期，美团兜底。"""
    _validate_hotel(lon, lat, checkin, checkout)
    return {
        "handoff": {
            "channel": "ctrip",
            "kind": "hotel",
            "url": (
                "https://hotels.ctrip.com/hotels/list"
                f"?city={_enc(city)}&checkin={checkin}"
                f"&checkout={checkout}&keyword={_enc(near_poi_name)}"
            ),
            "fallback": {"channel": "meituan", "url": "https://hotel.meituan.com/"},
        },
        "near_poi": {"name": near_poi_name, "lon": lon, "lat": lat},
        "refund_policy": _refund_channel_page("ctrip"),
    }
