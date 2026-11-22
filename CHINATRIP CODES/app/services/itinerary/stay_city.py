# -*- coding: utf-8 -*-
"""晚宿城 / 晨起城口径（2026-11-22 用户实录 FIX）。

用户原话：「第四天从西安到北京，酒店应该住北京，测试显示西安。第五天早上
也是从北京酒店出发，测试结果是从西安酒店出发。」

根因（两条口径各自漏城）：
① `trip_solver.assembly.materialize` 的夜卡/晨卡城市取 `_day_label`——「当天
   在排的卡多数城」，跨城日到达城的卡还没落（城际腿卡是后面的相位才插）时
   counts 为空，退化成「城市序索引」= 出发城（西安），于是 D4 夜卡写西安；
② `agent.hotel_stays.attach_hotel_nights` 的夜卡城取「列表顺序里最后一个带
   城的观光件」——列表序 ≠ 时链（排程相位会把卡前后挪），跨城日同样能取到
   出发城。夜卡城错了，次日晨卡继承夜卡，于是「第五天从西安酒店出发」。

本模块给两条路径一套唯一口径（纯函数，不依赖 agent / solver 任何一侧）：

- 晚宿城 = 当天**时刻最晚**的非酒店落脚点所在城；该落脚点是城际腿（出发城
  ≠ 到达城）且到达城属于「更晚日子的基准城」时，取到达城——即「末段到达城
  优先」，回家/离开行程城的腿不算落脚（回退到上一个落脚点）。
- 晨起城 = 前一晚夜卡城；首日（<=1）取当晚夜卡城，都没有才回落到基准城。

`apply_stay_cities` 是交付边界的保险闸：占位酒店卡（无 poi/地址/坐标）城市
不合口径就改写；已手输验证过的酒店卡（用户明确了住处）一律不动。
"""

from datetime import time

from app.services.itinerary.models import (
    DayPlan,
    TransferItem,
    VisitItem,
)

HOTEL_NIGHT_ID_PREFIX = "hotel-night"
HOTEL_MORNING_ID_PREFIX = "hotel-morning"
HOTEL_CATEGORY = "hotel"


def _city_key(city: object) -> str:
    return str(city or "").strip().removesuffix("市")


def is_night_card(item: object) -> bool:
    return isinstance(item, VisitItem) and str(item.item_id or "").startswith(
        HOTEL_NIGHT_ID_PREFIX
    )


def is_morning_card(item: object) -> bool:
    return isinstance(item, VisitItem) and str(item.item_id or "").startswith(
        HOTEL_MORNING_ID_PREFIX
    )


def is_hotel_card(item: object) -> bool:
    """酒店语义卡（夜卡/晨卡/入住卡）：不参与「落脚点」判定。"""
    if not isinstance(item, VisitItem):
        return False
    if is_night_card(item) or is_morning_card(item):
        return True
    return str(item.category or "").strip().lower() == HOTEL_CATEGORY


def hotel_verified(card: VisitItem) -> bool:
    """用户已明确的真实酒店（有 poi/地址/坐标）：城市不许被系统改写。"""
    return bool(
        getattr(card, "poi_id", None)
        or getattr(card, "address", None)
        or getattr(card, "location", None) is not None
    )


def _minutes(value: object) -> int | None:
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    return None


def item_end_minutes(item: object) -> int | None:
    end = _minutes(getattr(item, "end_time", None))
    if end is not None:
        return end
    start = _minutes(getattr(item, "start_time", None))
    dur = getattr(item, "duration_minutes", None)
    if start is not None and dur:
        total = start + int(dur)
        if total < 24 * 60:
            return total
    return None


def is_intercity_transfer(item: object) -> bool:
    """城际腿（两端城市不同）：同城接驳/回城打车卡不算跨城。"""
    if not isinstance(item, TransferItem):
        return False
    frm = _city_key(item.from_city)
    to = _city_key(item.to_city)
    return bool(frm and to and frm != to)


def _stops_desc(items: list[object]) -> list[tuple[int, object]]:
    """当天非酒店落脚点，按「结束时刻」倒序（同时刻按原始顺序倒序）。"""
    rows: list[tuple[int, int, object]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, (VisitItem, TransferItem)):
            continue
        if is_hotel_card(item):
            continue
        end = item_end_minutes(item)
        if end is None:
            continue
        rows.append((end, idx, item))
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [(end, item) for end, _idx, item in rows]


def last_stop(items: list[object]) -> object | None:
    """当天时刻最晚的非酒店落脚点（列表顺序无关）。"""
    stops = _stops_desc(items)
    return stops[0][1] if stops else None


def stay_city(
    items: list[object],
    base_city: str | None = None,
    *,
    stay_cities: set[str] | None = None,
) -> str:
    """当天晚宿城（口径见模块 docstring）。

    stay_cities = 更晚日子的基准城集合；给定时，城际腿的到达城不在其中按
    「离程腿」处理（回家日不把夜宿城写成返程地），继续往前找落脚点。
    """
    for _end, item in _stops_desc(items):
        if isinstance(item, TransferItem):
            to_city = str(item.to_city or "").strip()
            to_key = _city_key(to_city)
            if not to_key:
                continue
            same_city = _city_key(item.from_city) == to_key
            if stay_cities is not None and not same_city and to_key not in stay_cities:
                continue
            return to_city
        city = str(getattr(item, "city", "") or "").strip()
        if city:
            return city
    return str(base_city or "").strip()


def _later_base_cities(day_plans: list[DayPlan], day: int) -> set[str]:
    return {
        _city_key(other.base_city)
        for other in day_plans
        if other.day > day and _city_key(other.base_city)
    }


def apply_stay_cities(day_plans: list[DayPlan]) -> int:
    """交付边界收口：把占位夜卡/晨卡的城市拨回「实际住哪儿」。返回改写的卡数。

    夜卡先收（晨卡要读的前一晚夜卡城可能刚被拨回），晨卡后收。幂等：干净盘面
    零改动；已验证酒店卡（用户手输的真实酒店）不动。
    """
    fixed = 0
    by_day = {dp.day: dp for dp in day_plans}
    for dp in day_plans:
        night = next((i for i in dp.items if is_night_card(i)), None)
        if night is None or hotel_verified(night):
            continue
        want = stay_city(
            dp.items,
            dp.base_city,
            stay_cities=_later_base_cities(day_plans, dp.day) or None,
        )
        if want and _city_key(want) != _city_key(night.city):
            night.city = want
            fixed += 1
    for dp in day_plans:
        morning = next((i for i in dp.items if is_morning_card(i)), None)
        if morning is None or hotel_verified(morning):
            continue
        src_day = dp.day if dp.day <= 1 else dp.day - 1
        src_day_plan = by_day.get(src_day)
        src = (
            next((i for i in src_day_plan.items if is_night_card(i)), None)
            if src_day_plan is not None
            else None
        )
        want = (src.city if src is not None and src.city else dp.base_city) or ""
        want = str(want).strip()
        if want and _city_key(want) != _city_key(morning.city):
            morning.city = want
            # 城市改了，旧城心锚必须作废（否则「距下一站」按上一城的坐标算）
            morning.anchor_location = None
            fixed += 1
    return fixed
