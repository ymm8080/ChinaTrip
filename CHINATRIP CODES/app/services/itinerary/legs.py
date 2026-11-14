"""Intraday leg annotation (v2.4.3 §5 行程时间轴, product rule 2026-10-19).

annotate_legs() fills each VisitItem's display-only leg fields:
distance_to_next_km = straight-line (haversine) distance to the NEXT visit
of the same day, next_walk_minutes = walk estimate for that leg (×1.3
detour factor at 80 m/min), leg_source = "estimate". An intercity
TransferItem breaks the chain — the transfer card already describes that
leg. Pure function: no I/O, no LLM; idempotent, so it can run after every
plan mutation (solver output and LLM reranks never carry the fields).

leg_pairs() exposes the same chain to the agent's amap enrichment
(/v3/direction/walking — the nav module's engine, with POI-id snapping —
replaces the estimate with measured walking legs; leg_source flips to
"amap").
"""

from app.services.itinerary.models import (
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.rules import haversine_km

DETOUR_FACTOR = 1.3  # straight-line -> walking-route correction
WALK_METERS_PER_MINUTE = 80.0  # ≈ 4.8 km/h sightseeing pace
MIN_LEG_KM = 0.05  # below this the two stops are effectively co-located


def _point(item: VisitItem) -> GeoPoint | None:
    """Leg math point: real POI coords, else a meal card's inherited anchor."""
    return item.location or item.anchor_location


def resolve_meal_anchors(plan: ItineraryPlan) -> ItineraryPlan:
    """Re-anchor blank meal cards (午饭/晚饭自由安排) on the previous stop.


    2026-11-13 用户指令「BLANK LUNCH CARD 默认取上一站地址」：占位餐卡没有
    POI，卡面地址与「距下一站」腿都从当天前一落脚点继承。每次调用按当前
    顺序重算（幂等）——占位卡被拖到别处/其前面插入新条目，锚自动跟到新的
    前一站；跨城交通卡之后或当天首件没有可继承的落脚点则一律清空，绝不把
    出发城地址带过换乘卡。
    """
    for day in plan.days:
        last: VisitItem | None = None
        for item in day.items:
            if isinstance(item, TransferItem):
                last = None
                continue
            if item.anchor_from_prev:
                if last is not None and last.location is not None:
                    item.address = last.address
                    item.address_en = last.address_en
                    item.anchor_location = last.location
                else:
                    item.address = None
                    item.address_en = None
                    item.anchor_location = None
            if item.location is not None:
                last = item
    return plan


def leg_pairs(plan: ItineraryPlan) -> list[tuple[VisitItem, VisitItem, float]]:
    """Adjacent same-day visit pairs worth measuring, with straight-line km.

    Untimed cards break the chain (2026-11-03 Day4 show→park case): a leg
    into an unscheduled item is meaningless and rendered as an absurd
    night travel (a 949-minute leg from a 19:30 show to a forest park)."""
    out: list[tuple[VisitItem, VisitItem, float]] = []
    for day in plan.days:
        last: VisitItem | None = None
        for item in day.items:
            if isinstance(item, TransferItem) or item.start_time is None:
                last = None
                continue
            last_pt = _point(last) if last is not None else None
            cur_pt = _point(item)
            if last_pt is not None and cur_pt is not None:
                km = haversine_km(last_pt, cur_pt)
                if km >= MIN_LEG_KM:
                    out.append((last, item, km))
            last = item
    return out


def annotate_legs(plan: ItineraryPlan) -> ItineraryPlan:
    """Fill/clear the leg fields of every day in ``plan`` (in place)."""
    # 空餐卡先贴前一站（地址 + 锚点），腿链才能算出「餐 → 下一站」
    resolve_meal_anchors(plan)
    for day in plan.days:
        for item in day.items:
            if not isinstance(item, TransferItem):
                _clear_leg(item)
    for a, _b, km in leg_pairs(plan):
        a.distance_to_next_km = round(km, 2)
        meters = km * 1000.0 * DETOUR_FACTOR
        a.next_walk_minutes = max(1, round(meters / WALK_METERS_PER_MINUTE))
        a.leg_source = "estimate"
    return plan


def _clear_leg(item: VisitItem) -> None:
    item.distance_to_next_km = None
    item.next_walk_minutes = None
    item.leg_source = None
