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


# 每晚酒店卡（2026-11-07 用户指令「CREATE NEW SLOT FOR HOTEL IN THE LAST
# OF THE DAY. SAME EITHER PICK UP FROM 飞猪，携程，美团。OR INPUT MANUALLY
# BY USER」）：每天末尾系统插「回酒店·夜间休息」卡——订酒店走渠道卡
# （携程/美团/飞猪，铁律 22/23 退改闸），手输酒店名走 set-hotel 验证写回。
HOTEL_NIGHT_ID_PREFIX = "hotel-night"
HOTEL_NIGHT_MINUTES = 60  # 夜卡默认时长（回店休整到就寝）
HOTEL_NIGHT_GAP_MINUTES = 30  # 末件结束 → 回到酒店的默认衔接（铁律 4 同源）


def is_hotel_night(item: object) -> bool:
    """系统每晚酒店卡识别（item_id 前缀，与 is_hotel_checkin 同构）。"""
    return isinstance(item, VisitItem) and item.item_id.startswith(
        HOTEL_NIGHT_ID_PREFIX
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


def _minutes_of(t: time) -> int:
    return t.hour * 60 + t.minute


def _last_timed_end_minutes(dp: DayPlan) -> int | None:
    """当天最晚收尾（分钟），与条目列表顺序无关；夜卡自身不计。"""
    last_end: int | None = None
    for item in dp.items:
        if is_hotel_night(item):
            continue
        end: int | None = None
        if isinstance(item, VisitItem):
            if item.end_time is not None:
                end = _minutes_of(item.end_time)
            elif item.start_time is not None and item.duration_minutes is not None:
                total = _minutes_of(item.start_time) + item.duration_minutes
                if total < 24 * 60:
                    end = total
        elif isinstance(item, TransferItem):
            end = _transfer_end_minutes(item)
        if end is not None:
            last_end = end if last_end is None else max(last_end, end)
    return last_end


def _night_window(last_end: int | None) -> tuple[int, int]:
    """夜卡 [start, end)（分钟）：末件结束 +30 分钟起、60 分钟时长；
    空天 21:00 起；越过 23:00 贴 23:00 开卡（末件本身晚于 23:00 则贴
    末件），收尾封顶 23:59（与入住卡 _card_window 同款兜底口径）。"""
    if last_end is None:
        start = 21 * 60
    else:
        start = min(last_end + HOTEL_NIGHT_GAP_MINUTES, 23 * 60)
        if start < last_end:  # 末件晚于 23:00：贴末件，不回拨
            start = last_end
    return start, min(start + HOTEL_NIGHT_MINUTES, 23 * 60 + 59)


def attach_hotel_nights(day_plans: list[DayPlan]) -> list[str]:
    """初次排程时给每一天末尾插「回酒店·夜间休息」卡（2026-11-07 用户
    指令「CREATE NEW SLOT FOR HOTEL IN THE LAST OF THE DAY」）。

    调用时点=v0 排程收口之后（solver/兜底/清算全部完成）——末件时刻
    已定，窗口按最终时链推；绝不挂排程期插（早插的夜卡被当固定窗，
    当天下午 sequencing 全堵死——西湖 day1 排不上实录）。每天一张
    （末件为离程 transfer 的回家日不插，同入住卡「末段回家不插」口径）；
    幂等：已有夜卡的天不重复插。卡不带 poi/坐标/地址——回填与小时链按
    is_hotel_night 跳过（同入住卡口径，防「搜『回酒店』烧配额」）；手输
    酒店名经 set-hotel 端点验证后写回名称+地址+坐标。城取当天最后一个
    观光件的城（晚间换城日夜宿新城），夕发朝至末件取到达城，无观光件
    回落醒来城。仅初次排程插入；编辑/修复路径不复活已删卡。
    """
    inserted_days: list[int] = []
    for dp in day_plans:
        if any(is_hotel_night(i) for i in dp.items):
            continue
        # 末件=离程 transfer（到达城不再是任何更晚日子的宿城）：当晚在途/
        # 到家，不插夜卡（同入住卡「末段回家不插」口径）；反之夕发朝至
        # 落在宿城，则夜宿到达城（city 覆写为 to_city）。
        arr_city: str | None = None
        last = dp.items[-1] if dp.items else None
        if isinstance(last, TransferItem):
            to_key = _city_key(last.to_city)
            arrives_stay = bool(to_key) and any(
                later.day > dp.day and _city_key(later.base_city) == to_key
                for later in day_plans
            )
            if not arrives_stay:
                continue
            arr_city = (last.to_city or "").strip()
        city = dp.base_city
        for item in dp.items:
            if isinstance(item, VisitItem) and item.city:
                city = item.city
        last_end = _last_timed_end_minutes(dp)
        if arr_city:
            city = arr_city
        s, e = _night_window(last_end)
        dp.items.append(
            VisitItem(
                item_id=f"{HOTEL_NIGHT_ID_PREFIX}-d{dp.day}",
                name=L("🏨 回酒店·夜间休息", "🏨 Return to hotel · night rest"),
                category="hotel",
                city=city,
                day=dp.day,
                start_time=time(s // 60, s % 60),
                end_time=time(e // 60, e % 60),
                duration_minutes=e - s,
                pinned=False,
                soft_pin=True,
            )
        )
        inserted_days.append(dp.day)
    if not inserted_days:
        return []
    return [
        L(
            "每天末尾默认加「回酒店·夜间休息」卡（末件结束约半小时后到店）；"
            "可拖动/改时/删除，点 ✏️ 可验证并填入真实酒店名，点 🏨 订酒店 "
            "走携程/美团/飞猪渠道卡",
            "A 'return to hotel · night rest' card is added at the end of "
            "every day (~30 min after the last stop); drag/retime/delete "
            "freely, tap ✏️ to verify and set a real hotel name, or tap 🏨 "
            "to book via Ctrip/Meituan/Fliggy channel cards",
        )
    ]


def reanchor_hotel_nights(
    day_plans: list[DayPlan], *, keep_ids: set[str] | None = None
) -> None:
    """编辑/修复路径上的夜卡顺延（2026-11-08 西湖 retime 16:00 撞 16:45
    夜卡 → selfrepair 修复链被二次硬冲突耗尽事故）。

    夜卡语义=「当天末件收尾后回酒店休息」，初始排程按末件推窗（见
    attach_hotel_nights）。编辑/修复改动末件时刻后，若末件收尾已越过
    卡面起点，卡须顺延到「末件+30 起 60 分钟」口径——只顺延不回拨
    （用户手拖更早的卡不动），keep_ids 内的卡（本回合被用户拖/改的
    目标）完全不动；不复活已删卡（同 attach 口径）。"""
    keep = keep_ids or set()
    for dp in day_plans:
        card = next((i for i in dp.items if is_hotel_night(i)), None)
        if card is None or card.item_id in keep:
            continue
        s, e = _night_window(_last_timed_end_minutes(dp))
        cur = _minutes_of(card.start_time) if card.start_time else None
        if cur is None or s > cur:
            card.start_time = time(s // 60, s % 60)
            card.end_time = time(e // 60, e % 60)
            card.duration_minutes = e - s
