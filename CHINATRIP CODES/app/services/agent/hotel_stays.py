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

到达后每天出发点是 HOTEL（2026-11-13 用户拍板「到达后每天出发点是
HOTEL. 加酒店卡」）：前一晚住店（当天有 hotel-night 卡）的次日开头
插「🏨 从酒店出发」晨卡——卡占 30 分钟（早餐/退房），卡尾到当天首个
行程预留 30 分钟起程；酒店身份随夜卡 set-hotel 双向同步（夜卡 ↔
次日晨卡），点 ✏️ 同样可验证酒店名。首日=落地日不插（另有入住卡）。
"""

from datetime import time

from app.services.itinerary.models import (
    HOTEL_SETTLE_MINUTES,
    INTERCITY_BUFFER_MINUTES,
    DayPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.rules import travel_gap_needed
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
    """当天最晚收尾（分钟），与条目列表顺序无关；夜卡/晨卡自身不计。"""
    last_end: int | None = None
    for item in dp.items:
        if is_hotel_night(item) or is_hotel_morning(item):
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


# 到达后每天从酒店出发（2026-11-13 用户拍板「到达后每天出发点是 HOTEL.
# 加酒店卡」）：前一晚住店 → 次日开头一张「🏨 从酒店出发」软锚卡。卡占
# 30 分钟（早餐/退房），卡尾到当天首个非酒店件开场预留 30 分钟起程
# （首件提前/酒店坐标写入后由 reanchor_hotel_mornings 回拨）；空天
# 08:30–09:00（日始 9 点前离店）。酒店身份与夜卡双向同步（set-hotel）。
HOTEL_MORNING_ID_PREFIX = "hotel-morning"
HOTEL_MORNING_MINUTES = 30  # 出发卡默认时长（早餐/退房/整理）
HOTEL_MORNING_GAP_MINUTES = 30  # 离店 → 当天首站的路程预留（铁律 7 地板）


def is_hotel_morning(item: object) -> bool:
    """系统每日出发酒店卡识别（item_id 前缀，与 is_hotel_night 同构）。"""
    return isinstance(item, VisitItem) and item.item_id.startswith(
        HOTEL_MORNING_ID_PREFIX
    )


def hotel_morning_label(hotel_name: str | None) -> str:
    """晨卡名：有已验证酒店名时带上店名，否则「今日起点」占位。"""
    hotel = (hotel_name or "").strip()
    if hotel and not hotel.startswith("🏨"):
        return L(f"🏨 从酒店出发（{hotel}）", f"🏨 Depart from hotel ({hotel})")
    return L("🏨 从酒店出发（今日起点）", "🏨 Depart from hotel (today's start)")


def _copy_hotel_identity(src: VisitItem, dst: VisitItem) -> None:
    """酒店身份五件套（poi/地址/营业时间/坐标）整段复制。"""
    dst.poi_id = src.poi_id
    dst.address = src.address
    dst.address_en = src.address_en
    dst.opening_hours = src.opening_hours
    dst.opening_hours_en = src.opening_hours_en
    dst.location = src.location.model_copy() if src.location is not None else None


def _first_timed_item(dp: DayPlan) -> VisitItem | TransferItem | None:
    """当天首个有时刻的行程件（夜卡/晨卡自身不计；无时刻件跳过）。"""
    best: VisitItem | TransferItem | None = None
    best_min: int | None = None
    for item in dp.items:
        if is_hotel_morning(item) or is_hotel_night(item):
            continue
        if item.start_time is None:
            continue
        m = _minutes_of(item.start_time)
        if best_min is None or m < best_min:
            best, best_min = item, m
    return best


def _morning_window(
    first_start: int | None, *, transfer: bool = False
) -> tuple[int, int] | None:
    """晨卡 [start, end)（分钟）：首件开场前预留起程时间，卡占前
    _MINUTES 分钟；空天 08:30–09:00。首件是跨城交通时按铁律 4 的
    90 分钟衔接缓冲预留（否则晨卡贴 17:00 航班会被缓冲闸判硬违规），
    普通行程件按 30 分钟路程预留。放不下（首件过早）None。"""
    gap = INTERCITY_BUFFER_MINUTES if transfer else HOTEL_MORNING_GAP_MINUTES
    end = first_start - gap if first_start is not None else 9 * 60
    start = end - HOTEL_MORNING_MINUTES
    if end <= 0 or start < 0:
        return None
    return start, end


def attach_hotel_mornings(day_plans: list[DayPlan]) -> list[str]:
    """到达后每天以酒店为出发点：给「前一晚住店」的次日开头插晨卡。

    判定=前一天有 hotel-night 卡（前一晚没住酒店/夜车/末段回家不插）；
    首日=落地日不插（当天另有酒店入住卡）。窗口=当天首个非酒店件开场
    前预留起程（跨城交通按铁律 4 的 90 分钟缓冲）、卡占 30 分钟；空天
    08:30–09:00。酒店名/地址/坐标从夜卡继承（set-hotel 后由
    sync_hotel_pair 双向续写）。幂等：已有晨卡的天不重复插；编辑/修复
    路径不复活已删卡（同夜卡口径）。
    """
    inserted: list[int] = []
    by_day = {dp.day: dp for dp in day_plans}
    for dp in day_plans:
        if dp.day <= 1 or any(is_hotel_morning(i) for i in dp.items):
            continue
        prev = by_day.get(dp.day - 1)
        if prev is None:
            continue
        night = next((i for i in prev.items if is_hotel_night(i)), None)
        if night is None:
            continue
        first = _first_timed_item(dp)
        window = _morning_window(
            _minutes_of(first.start_time) if first is not None else None,
            transfer=isinstance(first, TransferItem),
        )
        if window is None:
            continue
        s, e = window
        card = VisitItem(
            item_id=f"{HOTEL_MORNING_ID_PREFIX}-d{dp.day}",
            name=hotel_morning_label(night.name),
            category="hotel",
            city=(night.city or dp.base_city or "").strip(),
            day=dp.day,
            start_time=time(s // 60, s % 60),
            end_time=time(e // 60, e % 60),
            duration_minutes=e - s,
            pinned=False,
            soft_pin=True,
        )
        _copy_hotel_identity(night, card)
        dp.items.insert(0, card)
        inserted.append(dp.day)
    if not inserted:
        return []
    uniq = sorted(set(inserted))
    return [
        L(
            "到达后每天从酒店出发：第{}天开头默认加「🏨 从酒店出发」卡"
            "（前一晚住店→次日以酒店为起点，出发前预留约30分钟到首站；"
            "可拖动/改时/删除，点 ✏️ 可验证酒店名）".format(
                "、".join(str(d) for d in uniq)
            ),
            "From arrival onward every day starts at the hotel: a "
            "'🏨 Depart from hotel' card is added at the start of day(s) {} "
            "(the default departure point after a hotel night, with ~30 min "
            "reserved for the ride to the first stop; drag/retime/delete "
            "freely, tap ✏️ to verify the hotel name)".format(
                ", ".join(str(d) for d in uniq)
            ),
        )
    ]


def _day_with(day_plans: list[DayPlan], day: int) -> DayPlan | None:
    return next((dp for dp in day_plans if dp.day == day), None)


def paired_hotel_card(day_plans: list[DayPlan], item: object) -> VisitItem | None:
    """同段住宿的另一端：夜卡 d ↔ 次日晨卡 d+1。"""
    if not isinstance(item, VisitItem):
        return None
    if is_hotel_night(item):
        nxt = _day_with(day_plans, item.day + 1)
        if nxt is None:
            return None
        return next((i for i in nxt.items if is_hotel_morning(i)), None)
    if is_hotel_morning(item):
        prev = _day_with(day_plans, item.day - 1)
        if prev is None:
            return None
        return next((i for i in prev.items if is_hotel_night(i)), None)
    return None


def sync_hotel_pair(
    day_plans: list[DayPlan], item: object, *, hotel_name: str
) -> VisitItem | None:
    """set-hotel 写回后同步同段住宿的另一端（2026-11-13 每天出发点
    是 HOTEL）：夜卡写入 → 次日晨卡继承名称/地址/坐标；晨卡写入 →
    前一晚夜卡同步。晨卡名恒为「🏨 从酒店出发（酒店名）」，夜卡名=
    酒店名（两端一致，用户下次点 ✏️ 不会误把前缀当店名）。"""
    pair = paired_hotel_card(day_plans, item)
    if pair is None or not isinstance(item, VisitItem):
        return None
    _copy_hotel_identity(item, pair)
    pair.city = (item.city or pair.city or "").strip()
    if is_hotel_morning(item):
        pair.name = hotel_name.strip()
        item.name = hotel_morning_label(hotel_name)
    else:
        pair.name = hotel_morning_label(hotel_name)
    return pair


def reanchor_hotel_mornings(
    day_plans: list[DayPlan], *, keep_ids: set[str] | None = None
) -> None:
    """编辑/设置酒店后的晨卡回拨（2026-11-13「每天出发点是 HOTEL」）。

    晨卡语义=「离店去当天首站」：首件开场或酒店坐标变化后，卡尾须
    回到「首件 − max(30, 实际打车腿)」（首件是跨城交通则按铁律 4 的
    90 分钟衔接缓冲），卡占前 30 分钟。只回拨不后移（用户手拖更早的
    卡不动）；keep_ids 内的卡（本回合被用户拖/改的目标）完全不动；
    不复活已删卡（同夜卡 reanchor 口径）。
    """
    keep = keep_ids or set()
    for dp in day_plans:
        card = next((i for i in dp.items if is_hotel_morning(i)), None)
        if card is None or card.item_id in keep:
            continue
        first = _first_timed_item(dp)
        if first is None:
            continue
        need = (
            INTERCITY_BUFFER_MINUTES
            if isinstance(first, TransferItem)
            else HOTEL_MORNING_GAP_MINUTES
        )
        if (
            card.location is not None
            and isinstance(first, VisitItem)
            and first.location is not None
        ):
            gap = travel_gap_needed(card, first)
            if gap is not None:
                need = max(need, gap)
        first_start = _minutes_of(first.start_time)
        end = first_start - need
        start = end - HOTEL_MORNING_MINUTES
        if end <= 0 or start < 0:
            continue
        cur_end = _minutes_of(card.end_time) if card.end_time is not None else None
        if cur_end is not None and cur_end <= end:
            continue
        card.start_time = time(start // 60, start % 60)
        card.end_time = time(end // 60, end % 60)
        card.duration_minutes = HOTEL_MORNING_MINUTES
