"""R12 gap bridges: visible transit cards for same-day dead air (>=45 min).

2026-11-19 用户拍板「天安门广场之后应该在去下一个景点的路上，而不是
空着等到午餐卡」：求解侧由绑定真餐馆流式直排（c09 餐窗解钳 + 池内荐点
餐馆 any-槽绑定）收掉成档空档；剩余由通勤/等位构成的空档必须可见——本
pass 在 ``annotate_legs`` 之后按已算好的腿（next_leg_mode /
next_leg_minutes）为每个 ``>= BRIDGE_GAP_MIN`` 的同日真空档插入
synthetic transfer 桥卡（跨距=整个空档），时间线不再有死空气。
桥卡名不内嵌目的地名——名字检索（测试、消息 diff 的 LLM 卡单）
绝不能把交通卡误认成景点/餐馆卡；目的地由时间线上紧邻的下一张
卡自明。

口径保守：远程接驳/access 链（prev.next_leg_detail 非空——去程详情链
自管）、无 POI 的占位餐卡（meal-* 无 poi_id——占位无目的地可去）、酒店
/换程系统卡前后（晨出、夜归、回城另有语义）、嵌套重叠段一律不桥。桥卡
category=transfer + synthetic=True：审计/打分器的观光口径全部豁免（与
access-return 回城卡同族），hotfix 的让位/远郊清场 pass 也不把它当
填充活动（见 hotfix_1117._is_filler 的 leg-bridge- 豁免）。
"""

from __future__ import annotations

from datetime import time as _time
from typing import TYPE_CHECKING

from ...itinerary.models import VisitItem

if TYPE_CHECKING:  # pragma: no cover
    from ...itinerary.models import ItineraryPlan

BRIDGE_GAP_MIN = 45  # C-03 地板 max(30, taxi) 之上的死空气才桥
_MODE_VERB = {"walk": "步行", "taxi": "乘车", "access": "接驳"}
_MODE_ICON = {"walk": "🚶", "taxi": "🚕", "access": "🚌"}
BRIDGE_ID_PREFIX = "leg-bridge-"


def _mins(t) -> int | None:
    if t is None:
        return None
    return t.hour * 60 + t.minute


def _bridgeable(item: VisitItem) -> bool:
    """酒店/换程系统卡不做桥的起点或目的地；无 POI 的占位餐卡（无目的
    地可去）同样不桥。命名餐卡（真餐厅顶卡，带 poi_id）照常可桥。"""
    if (item.category or "") in ("hotel", "transfer", "transport"):
        return False
    if (item.item_id or "").startswith("meal-") and not item.poi_id:
        return False
    return True


def attach_gap_bridges(plan: "ItineraryPlan") -> "ItineraryPlan":
    """每段 >=BRIDGE_GAP_MIN 的同日真空档插一张「前往下一站」交通桥卡。"""
    seq = 0
    for day in plan.days:
        timed = [
            i
            for i in day.items
            if isinstance(i, VisitItem) and i.start_time is not None
        ]
        if len(timed) < 2:
            continue
        timed.sort(key=lambda i: (_mins(i.start_time), str(i.item_id)))
        spans = [
            (_mins(i.start_time), _mins(i.end_time) or _mins(i.start_time), i)
            for i in timed
        ]
        merged: list[list[int]] = []
        for s, e, _i in spans:
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        added: list[VisitItem] = []
        for k in range(len(merged) - 1):
            g0, g1 = merged[k][1], merged[k + 1][0]
            if g1 - g0 < BRIDGE_GAP_MIN:
                continue
            # 嵌套同时刻多卡（宿主+嵌餐同起点）：起点取可桥卡中最晚者、
            # 终点取可桥卡中最早者——占位餐卡/系统卡不进桥的两端。
            prev = max(
                (
                    i
                    for i in timed
                    if (_mins(i.end_time) or _mins(i.start_time)) == g0
                    and _bridgeable(i)
                ),
                key=lambda i: _mins(i.start_time),
                default=None,
            )
            nxt = next(
                (
                    i
                    for i in sorted(
                        timed, key=lambda t: (_mins(t.start_time), str(t.item_id))
                    )
                    if _mins(i.start_time) == g1 and _bridgeable(i)
                ),
                None,
            )
            if prev is None or nxt is None:
                continue
            if getattr(prev, "next_leg_detail", None):
                continue  # access/换程详情链自管该空档
            seq += 1
            gap = g1 - g0
            mode = str(getattr(prev, "next_leg_mode", None) or "")
            minutes = getattr(prev, "next_leg_minutes", None)
            verb = _MODE_VERB.get(mode)
            icon = _MODE_ICON.get(mode, "🧭")
            if verb and isinstance(minutes, int):
                name = "%s %s前往下一站·约%d分钟" % (icon, verb, minutes)
                if gap - minutes > 10:
                    name += "（含自由等候）"
            else:
                name = "🧭 前往下一站（自由安排）"
            nxt_en = "the next stop"
            added.append(
                VisitItem(
                    item_id="%sd%d-%d" % (BRIDGE_ID_PREFIX, day.day, seq),
                    name=name,
                    name_en="Transfer to %s" % nxt_en,
                    category="transfer",
                    city=nxt.city,
                    day=day.day,
                    start_time=_time(g0 // 60 % 24, g0 % 60),
                    end_time=_time(g1 // 60 % 24, g1 % 60),
                    duration_minutes=gap,
                    synthetic=True,
                )
            )
        if added:
            day.items.extend(added)
            day.items.sort(
                key=lambda i: (
                    (_mins(i.start_time) if i.start_time is not None else 24 * 60),
                    str(i.item_id),
                )
            )
    return plan
