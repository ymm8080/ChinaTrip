"""F-31 meal cards anchored at solution locations.

Remote-day lunch anchors at the remote site (or post-visit); city meals
anchor at their model host; only hostless meals fall back to the legacy
previous-stop anchor. Addresses come from the POI record (candidate),
never "previous city item".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...itinerary.models import VisitItem

if TYPE_CHECKING:  # pragma: no cover
    from ...itinerary.models import ItineraryPlan
    from ..types import FactSnapshot, Solution

PLACEHOLDER = {
    "lunch": {"zh": "午餐", "en": "Lunch"},
    "dinner": {"zh": "晚饭", "en": "Dinner"},
}


def _hhmm(minutes: int):
    from datetime import time

    return time(minutes // 60 % 24, minutes % 60)


def _meal_card(
    slot: str,
    day: int,
    start_min: int,
    end_min: int,
    host,
    city: str,
    item_id: str,
) -> VisitItem:
    host_loc = None
    if host is not None and host.lon is not None and host.lat is not None:
        from ...itinerary.models import GeoPoint

        host_loc = GeoPoint(lon=float(host.lon), lat=float(host.lat))
    named = host is not None and (host.category == "food" or host.meal_slot == slot)
    # R28（2026-11-23 虹鳟鱼案）：命名餐卡必须带店名地址——候选行
    # 的 address 此前在 CandidateItem 转换处被丢，卡面 📍 行判空
    # 整行不画，用户只看到怪名/无址餐卡。占位卡维持无地址规则。
    from app.services.poi_names import clean_meal_slot_suffix

    # R8-S2b：命名卡（真餐厅）携带 POI 坐标；占位卡维持无 POI 规则
    named_loc = host_loc if named else None
    return VisitItem(
        item_id=item_id,
        # R28 止污：库行污名（带槽位后缀的展示名）不再外露到卡面。
        name=(clean_meal_slot_suffix(host.name) if named else PLACEHOLDER[slot]["zh"]),
        name_en=(None if named else PLACEHOLDER[slot]["en"]),
        poi_id=(host.poi_id if named else None),
        category="food",
        city=city,
        location=named_loc,  # 占位卡无 POI；命名卡（真餐厅）带坐标
        anchor_from_prev=False,
        anchor_location=host_loc,  # F-31: anchor from the host record
        opening_hours=(host.opening_hours if named else None),
        # R28：命名卡带候选行地址；占位卡无地址（自由安排语义）。
        address=(host.address if named else None),
        address_en=(getattr(host, "address_en", None) if named else None),
        day=day,
        start_time=_hhmm(start_min),
        end_time=_hhmm(end_min),
        duration_minutes=end_min - start_min,
    )


def attach_meal_cards(
    plan: "ItineraryPlan", solution: "Solution", snapshot: "FactSnapshot"
) -> "ItineraryPlan":
    cand_by_cid = {c.cid: c for c in snapshot.candidates}
    for meal in solution.meal_anchors:
        day = int(meal.get("day") or 0)
        slot = str(meal.get("slot") or "")
        if not day or slot not in PLACEHOLDER:
            continue
        host = cand_by_cid.get(meal.get("host_cid"))
        bound = cand_by_cid.get(meal.get("bound_cid"))
        if bound is not None:
            # R8-S2b 餐类必去顶餐卡：真餐厅即餐卡本体（时刻/时长=解锁定）
            host = bound
        day_plan = next((d for d in plan.days if d.day == day), None)
        if day_plan is None:
            continue
        city = day_plan.base_city
        card = _meal_card(
            slot,
            day,
            int(meal.get("start_min") or 0),
            int(meal.get("end_min") or 0),
            host,
            city,
            "meal-%s-%d" % (slot, day),
        )
        if host is None:
            # hostless city meal: legacy previous-stop anchor
            card.anchor_from_prev = True
            card.anchor_location = None
        day_plan.items.append(card)
        day_plan.items.sort(
            key=lambda it: (
                (it.start_time.hour * 60 + it.start_time.minute)
                if it.start_time is not None
                else 24 * 60,
                it.item_id,
            )
        )
    return plan
