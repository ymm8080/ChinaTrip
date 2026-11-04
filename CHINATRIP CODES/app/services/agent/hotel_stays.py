# -*- coding: utf-8 -*-
"""落地首停·酒店入住模块（2026-11-01 用户拍板「行程里应该有 HOTEL」）。

规则（用户原话口径）：从火车或飞机落地到目的地，下一站默认是酒店——
① 行程含酒店（默认插入住卡）：卡摆在落地 +90 分钟（铁律 4 衔接缓冲
   =出站+去酒店，即「到达酒店」的默认估计），休整 1 小时后出发去当天
   首个行程（= 落地 +150）；
② 没有酒店卡（用户删除/深夜放不下）：当天首个观光同样 ≥ 落地 +150
   （2.5 小时）——solver CP/插入两条主路与 plan 兜底三处同口径。

入住卡=系统软锚件（pinned=False + soft_pin=True，与午餐占位同构）：
solver 锚定落位、用户可拖/可改时/可删（删后即走 ② 口径）。仅初次排程
插入；编辑/修复路径不复活已删卡。卡无 poi/坐标——地址/营业时间回填
与走行链自动跳过。回程末段（落地即回家，无过夜）不插。
"""

from datetime import time

from app.services.itinerary.models import (
    HOTEL_SETTLE_MINUTES,
    INTERCITY_BUFFER_MINUTES,
    DayPlan,
    TransferItem,
    VisitItem,
)
from app.services.lang_ctx import L

HOTEL_CHECKIN_ID_PREFIX = "hotel-checkin"


def is_hotel_checkin(item: object) -> bool:
    """系统酒店入住卡识别（item_id 前缀，与 is_lunch_placeholder 同构）。"""
    return isinstance(item, VisitItem) and item.item_id.startswith(
        HOTEL_CHECKIN_ID_PREFIX
    )


def _city_key(city: str | None) -> str:
    return (city or "").strip().removesuffix("市")


def _transfer_end_minutes(t: TransferItem) -> int | None:
    if t.start_time is None:
        return None
    end = t.end_time
    if end is None and t.duration_minutes is not None:
        total = t.start_time.hour * 60 + t.start_time.minute + t.duration_minutes
        if total < 24 * 60:
            end = time(total // 60, total % 60)
    if end is None:
        return None
    return end.hour * 60 + end.minute


def _card_window(land: int) -> tuple[int, int] | None:
    """入住卡 [start, end)（分钟）。常规=落地+90 起 60 分钟；深夜落地
    缓冲越日时贴落地压缩时长（保底 30）；放不下（>23:29 落地）None。"""
    start = land + INTERCITY_BUFFER_MINUTES
    if start + HOTEL_SETTLE_MINUTES <= 23 * 60 + 59:
        return start, start + HOTEL_SETTLE_MINUTES
    if land + 30 > 23 * 60 + 59:
        return None
    return land, min(land + HOTEL_SETTLE_MINUTES, 23 * 60 + 59)


def attach_hotel_stays(day_plans: list[DayPlan]) -> list[str]:
    """初次排程时给「火车/飞机落地过夜城」的日子插酒店入住卡。

    过夜城判定：到达城必须是某个更晚日子的 base_city（末段回家不算
    ——落地即旅程结束）。幂等：已有入住卡的天不重复插。返回假设区
    备注（双语）。
    """
    inserted_days: list[int] = []
    for dp in day_plans:
        if any(is_hotel_checkin(i) for i in dp.items):
            continue
        done_cities: set[str] = set()
        for t in sorted(
            (i for i in dp.items if isinstance(i, TransferItem)),
            key=lambda x: x.seq,
        ):
            if t.mode not in ("train", "flight"):
                continue
            to_key = _city_key(t.to_city)
            if not to_key or to_key in done_cities:
                continue
            arrives_stay = any(
                later.day > dp.day and _city_key(later.base_city) == to_key
                for later in day_plans
            )
            if not arrives_stay:
                continue
            land = _transfer_end_minutes(t)
            if land is None:
                continue
            window = _card_window(land)
            if window is None:
                continue
            s, e = window
            card = VisitItem(
                item_id=f"{HOTEL_CHECKIN_ID_PREFIX}-d{dp.day}",
                name=L(
                    "🏨 酒店入住（放行李·休整）",
                    "🏨 Hotel check-in (drop bags & settle in)",
                ),
                category="hotel",
                city=(t.to_city or "").strip(),
                day=dp.day,
                start_time=time(s // 60, s % 60),
                end_time=time(e // 60, e % 60),
                duration_minutes=e - s,
                pinned=False,
                soft_pin=True,
            )
            dp.items.insert(dp.items.index(t) + 1, card)
            done_cities.add(to_key)
            inserted_days.append(dp.day)
    if not inserted_days:
        return []
    uniq = sorted(set(inserted_days))
    return [
        L(
            "第{}天落地后默认先到酒店安顿（落地约1.5小时到店、休整1小时），"
            "当天首个行程不早于落地2.5小时；无需酒店可删除该卡".format(
                "、".join(str(d) for d in uniq)
            ),
            "Day(s) {} default to hotel check-in after landing "
            "(~1.5h to the hotel, 1h to settle in); the first visit starts "
            "no earlier than 2.5h after landing — delete the card if you "
            "don't need a hotel".format(", ".join(str(d) for d in uniq)),
        )
    ]
