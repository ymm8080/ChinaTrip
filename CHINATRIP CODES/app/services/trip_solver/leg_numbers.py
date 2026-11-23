"""CP-SAT 城际腿真实班次回填（R13q / gap #2 挂账项）。

R13o 起引擎装配在转场日日始插结构 TransferItem（方式/占位时刻，
train_no/flight_no 恒空）；用户可经 `/plan/{sid}/transfers/{id}/number`
手工回填。本模块在**引擎服务成功之后**用注入的 train/flight service
按 (from_city, to_city, 乘车日) 自动选当日最优班次回填真实号码与时刻，
复用 legacy 同一 pick_best_* 口径（火车 08:00 发车地板、有窗取窗内最早）。

设计约束：
- async（service.search 是 async），由 api 缝在 to_thread 之后 await，
  绝不把 IO 塞进 sync 的 solve/assemble 线程；
- 只填**引擎自己造的结构卡**（无号码 + xfer- item_id）——用户经
  intake/手工端点填的班次（有号码）一律不动，用户权威优先；
- 回填后走 `_reconcile_transfer_days` + `_fallback_sequence_times` +
  `annotate_legs`（legacy `_apply_transfer_schedule` 同款尾），保证腿时刻
  变化不带歪当天排期；失败降级为原结构卡 + 披露，绝不静默造号。
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _leg_date_iso(start_date: Optional[str], day: int) -> str:
    if not start_date:
        return ""
    try:
        base = _dt.date.fromisoformat(str(start_date)[:10])
    except ValueError:
        return ""
    return (base + _dt.timedelta(days=max(day, 1) - 1)).isoformat()


async def fill_structural_leg_numbers(
    plan,
    *,
    start_date: Optional[str],
    trains=None,
    flights=None,
) -> list[str]:
    """回填引擎结构腿的真实班次；返回用户可见披露列表（空=无变更）。

    纯 IO + 确定性回填，LLM 零参与；任一腿查询失败只跳过该腿（保留
    占位卡，不编造号码），其余腿照常回填。
    """
    from app.services.agent.plan import (
        _fallback_sequence_times,
        _reconcile_transfer_days,
    )
    from app.services.flights import pick_best_flight
    from app.services.itinerary.legs import annotate_legs
    from app.services.itinerary.models import TransferItem, VisitItem
    from app.services.trains import pick_best_train

    if plan is None or (trains is None and flights is None):
        return []

    structural: list[tuple[Any, Any]] = []
    for dp in getattr(plan, "days", ()):
        for item in dp.items:
            if not isinstance(item, TransferItem):
                continue
            if item.train_no or item.flight_no:
                continue  # 用户权威（intake/手工端点）——引擎不覆盖
            if not str(item.item_id or "").startswith("xfer"):
                continue  # 只动引擎自造的结构卡
            structural.append((dp, item))

    if not structural:
        return []

    changed: list[str] = []
    for dp, item in structural:
        iso = _leg_date_iso(start_date, dp.day)
        if not iso:
            continue
        try:
            if item.mode == "train" and trains is not None:
                opt = await pick_best_train(
                    trains, item.from_city, item.to_city, iso
                )
                if opt is None:
                    continue
                item.train_no = opt.train_no
                item.flight_no = None
                item.start_time = opt.dep_time
                item.end_time = opt.arr_time
                item.duration_minutes = opt.duration_minutes
            elif item.mode == "flight" and flights is not None:
                opt = await pick_best_flight(
                    flights, item.from_city, item.to_city, iso
                )
                if opt is None:
                    continue
                item.flight_no = opt.flight_no
                item.train_no = None
                item.start_time = opt.dep_time
                item.end_time = opt.arr_time
                item.duration_minutes = opt.duration_minutes
            else:
                continue
            no = item.train_no or item.flight_no
            changed.append(
                f"第{dp.day}天 {item.from_city}→{item.to_city} "
                f"自动选定{item.mode} {no}（按当日时刻表）"
            )
        except Exception:
            logger.warning(
                "leg_numbers: %s→%s day %d lookup failed; keeping structural card",
                item.from_city, item.to_city, dp.day,
            )

    if not changed:
        return []

    # legacy `_apply_transfer_schedule` 同款尾（不查库、不 LLM）——
    # 时刻变化后清时重排受影响天、保 pinned、重标腿。必去卡按铁律
    # 「必须去不可被自动删」传 protect，绝不让班次回填反噬覆盖度。
    protected = frozenset(
        str(v.name)
        for dp in getattr(plan, "days", ())
        for v in dp.items
        if isinstance(v, VisitItem) and bool(getattr(v, "must", False))
    )
    notes = _reconcile_transfer_days(plan, protect=protected, user_edit=False)
    _fallback_sequence_times(plan, keep_list_order=False)
    annotate_legs(plan)
    return changed + list(notes or [])


async def enrich_measured_legs_if_enabled(agent, plan) -> None:
    """生成期实测腿回填（R13q 挂账「配额/时延决策」的可选落在）。

    默认关（config.plan_measured_legs_at_generation_enabled=False）——
    legacy 在生成期跑 `_enrich_parallel`（12-30s 冷启），CP-SAT 缝此前
    不跑、读侧 GET 的 `refresh_legs` 兜。开=生成期跑同一有界回填
    （LEG_ENRICH_MAX_PAIRS=24 / AMAP_CONCURRENCY=6，全用 legacy 常量），
    缓存同时暖好，读侧命中零重复外呼。失败静默保留直线估算。
    """
    from app.config import get_settings

    if not get_settings().plan_measured_legs_at_generation_enabled:
        return
    if agent is None or getattr(agent, "_amap", None) is None:
        return
    from app.services.agent.plan import LEG_ENRICH_MAX_PAIRS

    if LEG_ENRICH_MAX_PAIRS <= 0:
        return  # 显式 0 = 关闭配额（运维旋钮），零网络
    await agent._enrich_legs(plan)
