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

# R12-C2（2026-11-19 拍板「所有景点后就是下一个景点，不需要
# 45 分钟这个条件」）：每一段正时长转场都出桥——时间线全程
# 「在路上」，不再只兜大空档。
BRIDGE_GAP_MIN = 0
_MODE_VERB = {"walk": "步行", "taxi": "乘车", "access": "接驳"}
_MODE_ICON = {"walk": "🚶", "taxi": "🚕", "access": "🚌"}
BRIDGE_ID_PREFIX = "leg-bridge-"


def _haversine_km(a, b) -> float:
    import math

    if a is None or b is None:
        return 0.0
    lon1, lat1, lon2, lat2 = map(math.radians, (a.lon, a.lat, b.lon, b.lat))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _estimated_leg(a, b):
    """无 annotate 腿元数据时的兜底估算：直线距离→步行(≤2km)/打车。
    返回 (mode, minutes) 或 None（无坐标）。"""
    km = _haversine_km(a, b)
    if km <= 0:
        return None
    if km <= 2.0:
        return ("walk", max(1, round(km * 1000 / 75)))
    return ("taxi", round(min(180, km * 1.3 / 35 * 60)) + 30)


def _mins(t) -> int | None:
    if t is None:
        return None
    return t.hour * 60 + t.minute


def _bridgeable(item: VisitItem) -> bool:
    """酒店/换程系统卡不做桥的起点或目的地（晨出/夜归/回城卡自身
    就是转场语义）。其余一切卡（含占位/命名餐卡）都参与每段转场——
    2026-11-19 拍板「所有景点后就是下一个景点，不需要 45 分钟条件」。"""
    return (item.category or "") not in ("hotel", "transfer", "transport")


def attach_gap_bridges(plan: "ItineraryPlan") -> "ItineraryPlan":
    """每段 >=BRIDGE_GAP_MIN 的同日真空档插一张「前往下一站」交通桥卡。

    幂等：先清掉既有 leg-bridge-* 再按当前形状重挂——装配期挂过、
    读闸 heal（升旗锚/接驳对齐/餐卡顺延）挪卡后重挂，两次调用都安全。
    """
    for day in plan.days:
        day.items = [
            i
            for i in day.items
            if not str(getattr(i, "item_id", "") or "").startswith(BRIDGE_ID_PREFIX)
        ]
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
            if g1 - g0 <= BRIDGE_GAP_MIN:
                continue  # 仅零/负间隔（嵌套）不出桥
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
            # R12-C2：access/换程段也出桥（去程接驳此前无卡可见——
            # 「前往下一站·接驳约N分钟」补上；班次详情仍在 prev 卡
            # 的 next_leg_detail 元数据里）。
            seq += 1
            gap = g1 - g0
            mode = str(getattr(prev, "next_leg_mode", None) or "")
            minutes = getattr(prev, "next_leg_minutes", None)
            verb = _MODE_VERB.get(mode)
            icon = _MODE_ICON.get(mode, "🧭")
            if not (verb and isinstance(minutes, int)):
                est = _estimated_leg(
                    getattr(prev, "location", None),
                    getattr(nxt, "location", None),
                )
                if est is not None:
                    mode, minutes = est
                    verb = _MODE_VERB.get(mode)
                    icon = _MODE_ICON.get(mode, "🧭")
            wait = gap - minutes if isinstance(minutes, int) else gap
            if verb and isinstance(minutes, int):
                name = "%s %s前往下一站·约%d分钟" % (icon, verb, minutes)
                if wait > 60:
                    name = "🕒 自由活动，随后%s前往下一站·约%d分钟" % (
                        verb,
                        minutes,
                    )
                elif wait > 10:
                    name += "（含自由等候）"
            else:
                name = "🧭 前往下一站（自由安排）"
                if wait > 60:
                    name = "🕒 自由活动，随后前往下一站"
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


def resolve_bridge_prev(plan: "ItineraryPlan", bridge_id: str) -> VisitItem:
    """解析桥卡 id → 上一站卡（桥卡出发时刻的实体锚）。

    R20（2026-11-23 用户令「乘车去下一站的时间应该也可以编辑」）：桥卡
    只活在响应副本（幂等先清后挂、卡上无可编辑实体），桥卡的出发时刻
    =上一站的结束时刻（构造时 g0=prev.end）——用户改桥卡出发时刻就是
    改上一站的结束。解析须在「按响应形状挂好桥卡」的盘面上进行（api 层
    用 _plan_for_response 的产物探查，保证桥卡 id 与用户所见一致：晨卡
    收点/回城卡重投影都会挪动空档两端，裸会话盘面探查会对不上）。
    匹配口径与构造一致：同一时间线上、结束时刻==桥卡开始时刻的最近
    一张可桥卡。

    找不到桥卡 → item_not_found（盘面已变、id 过期，404 让前端刷新重试）；
    上一站缺失/无时刻 → bridge_prev_untimed。
    """
    for day in plan.days:
        for idx, it in enumerate(day.items):
            if not (isinstance(it, VisitItem) and it.item_id == bridge_id):
                continue
            target_min = _mins(it.start_time)
            cands = [
                p
                for p in day.items[:idx]
                if isinstance(p, VisitItem)
                and (_mins(p.end_time) or _mins(p.start_time)) == target_min
                and (p.category or "") not in ("hotel", "transfer", "transport")
            ]
            if not cands:
                raise ValueError("bridge_prev_untimed")
            # 嵌套占位餐卡常与宿主同尾（宿主 10:00-13:00、占位午饭 12:00-13:00，
            # R20 实测：refresh_legs 物化占位后桥卡的「结束==开始」候选有两张）
            # ——用户眼里的「上一站」是宿主卡：改桥卡出发=伸缩宿主停留，绝不
            # 抓占位餐卡。优先非占位卡取最晚开始（与构造 max-start 口径一致），
            # 全是占位才回落占位。
            real = [
                p
                for p in cands
                if not str(p.item_id or "").startswith(
                    ("meal-lunch-", "meal-dinner-", "food-lunch-ph", "food-dinner-ph")
                )
            ]
            pool = real or cands
            return max(pool, key=lambda p: _mins(p.start_time) or 0)
    raise ValueError("item_not_found")
