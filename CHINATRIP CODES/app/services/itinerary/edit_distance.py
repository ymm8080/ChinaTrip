"""条目级编辑距离：AI 原始行程 vs 用户最终保存行程（P6 质量北极星基建）。

口径（加权四类操作，op 之间互斥——一张卡只计最重的一类）：
- add    最终里有、原始里没有的站点卡（+1.0）
- remove 原始里有、最终被删掉的站点卡（+1.0）
- move   同一张卡改了天（day 变化）或同天内顺序变化（+0.5）
- retime 天与顺序都没动、只有开始时刻变化超过容差（+0.25）

匹配键：poi_id 双方非空且相等 → 同一卡；否则归一化名称相等 → 同一
卡（库卡/占位卡无 poi_id 时的兜底）。一对一匹配，先到先得。

纯函数模块：无 DB / LLM / I/O，先不接线线上（lane_metrics 是运行时
内存遥测，本指标是离线对比口径，落库接线留待 P6 后半）。

用法：
    from app.services.itinerary.edit_distance import edit_distance

    result = edit_distance(ai_plan, saved_plan)
    result.counts            # {"add": 0, "remove": 1, "move": 2, "retime": 0}
    result.weighted_total()  # 按权重加权的标量分（越低越好）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.itinerary.models import ItineraryPlan, VisitItem

# 权重拍板口径：删/加是用户对内容本身的不认可（最贵），挪天是结构性
# 调整（中），只改时刻是微调（最便宜）。
DEFAULT_WEIGHTS = {"add": 1.0, "remove": 1.0, "move": 0.5, "retime": 0.25}

# 开始时刻差 ≤ 该容差（分钟）视为没改（落位抖动不算用户编辑）。
DEFAULT_RETIME_TOLERANCE_MINUTES = 15


@dataclass
class EditOp:
    """一次编辑操作（可解释载荷，供报表逐条展开）。"""

    kind: str  # add | remove | move | retime
    item_key: str
    name: str
    day: int | None = None
    from_day: int | None = None
    to_day: int | None = None
    from_order: int | None = None
    to_order: int | None = None
    from_start_minutes: int | None = None
    to_start_minutes: int | None = None


@dataclass
class EditDistanceResult:
    adds: list[EditOp] = field(default_factory=list)
    removes: list[EditOp] = field(default_factory=list)
    moves: list[EditOp] = field(default_factory=list)
    retimes: list[EditOp] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "add": len(self.adds),
            "remove": len(self.removes),
            "move": len(self.moves),
            "retime": len(self.retimes),
        }

    def weighted_total(self, weights: dict[str, float] | None = None) -> float:
        w = weights or DEFAULT_WEIGHTS
        counts = self.counts
        return float(sum(w[k] * counts[k] for k in counts))

    def summarize(self, weights: dict[str, float] | None = None) -> dict:
        return {
            "counts": self.counts,
            "weighted_total": self.weighted_total(weights),
            "weights": dict(weights or DEFAULT_WEIGHTS),
            "ops": [
                op.__dict__
                for ops in (self.adds, self.removes, self.moves, self.retimes)
                for op in ops
            ],
        }


def _norm_name(name: str | None) -> str:
    return "".join((name or "").split())


def _item_key(item: VisitItem) -> str:
    if item.poi_id:
        return f"poi:{item.poi_id}"
    return f"name:{_norm_name(item.name)}"


def _start_minutes(item: VisitItem) -> int | None:
    if item.start_time is None:
        return None
    return item.start_time.hour * 60 + item.start_time.minute


def _day_orders(plan: ItineraryPlan) -> dict[int, tuple[int, int]]:
    """id(item) → (day, 当天 VisitItem 顺序位)；按对象身份，同键重复卡不串。"""
    orders: dict[int, tuple[int, int]] = {}
    for day in plan.days:
        idx = 0
        for item in day.items:
            if not isinstance(item, VisitItem):
                continue
            orders[id(item)] = (day.day, idx)
            idx += 1
    return orders


def edit_distance(
    original: ItineraryPlan,
    final: ItineraryPlan,
    *,
    weights: dict[str, float] | None = None,
    retime_tolerance_minutes: int = DEFAULT_RETIME_TOLERANCE_MINUTES,
) -> EditDistanceResult:
    """对比原始（AI 出）与最终（用户保存）两张行程的站点卡编辑量。

    TransferItem 不参与（城际交通段由票务事实决定，不算用户编辑）；
    餐卡/酒店卡作为 VisitItem 照常计数（category 区分权交给报表层）。
    """
    result = EditDistanceResult()
    orig_visits = [
        item
        for day in original.days
        for item in day.items
        if isinstance(item, VisitItem)
    ]
    final_visits = [
        item for day in final.days for item in day.items if isinstance(item, VisitItem)
    ]
    orig_orders = _day_orders(original)
    final_orders = _day_orders(final)

    orig_index: dict[str, list[VisitItem]] = {}
    for item in orig_visits:
        orig_index.setdefault(_item_key(item), []).append(item)

    matched_final: dict[str, VisitItem] = {}
    for item in final_visits:
        key = _item_key(item)
        if key in matched_final:
            # 同名重复卡（同街族 chip 展开等）：第二张起按 add 计，
            # 避免一对一匹配吃掉真实的新增卡。
            result.adds.append(
                EditOp(kind="add", item_key=key, name=item.name, day=item.day)
            )
            continue
        if not orig_index.get(key):
            result.adds.append(
                EditOp(kind="add", item_key=key, name=item.name, day=item.day)
            )
            continue
        matched_final[key] = item

    for key, f_item in matched_final.items():
        candidates = orig_index.get(key)
        if not candidates:  # pragma: no cover - 上一轮循环已判空，防御留痕
            result.adds.append(
                EditOp(kind="add", item_key=key, name=f_item.name, day=f_item.day)
            )
            continue
        o_item = candidates.pop(0)  # 一对一，先到先得
        o_day, o_order = orig_orders[id(o_item)]
        f_day, f_order = final_orders[id(f_item)]
        if (o_day, o_order) != (f_day, f_order):
            result.moves.append(
                EditOp(
                    kind="move",
                    item_key=key,
                    name=f_item.name,
                    from_day=o_day,
                    to_day=f_day,
                    from_order=o_order,
                    to_order=f_order,
                )
            )
            continue
        o_start = _start_minutes(o_item)
        f_start = _start_minutes(f_item)
        if (
            o_start is not None
            and f_start is not None
            and abs(o_start - f_start) > retime_tolerance_minutes
        ):
            result.retimes.append(
                EditOp(
                    kind="retime",
                    item_key=key,
                    name=f_item.name,
                    day=f_day,
                    from_start_minutes=o_start,
                    to_start_minutes=f_start,
                )
            )

    # 原始侧还有剩的（pop 没消费完的同键多张 + 完全没匹配上的）即删除。
    for key, remaining in orig_index.items():
        for item in remaining:
            result.removes.append(
                EditOp(kind="remove", item_key=key, name=item.name, day=item.day)
            )

    return result
