# -*- coding: utf-8 -*-
"""行程变更日志与明细落库（2026-11-13 用户拍板）。

「TRIP 还需要有详情数据库，WHICH STORED EACH DATE AND TIME AND SITES,
ALTERNATIVE INFORMATION. WE ALSO NEED A CHANGE LOG DATASET WHICH STORED
USER, USER NAME, CHANGES AFTER CLICK SAVE BUTTON.」

职责：
  * diff_plans(old, new) → 逐条变更（add / remove / move / retime / city）
  * summarize(changes) → 人读摘要
  * record_trip_change(...) → 一次保存 = 头更新 + 明细重建 + 日志一行
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy import text

from app.models import Itinerary, ItineraryChangeLog, ItineraryDay, ItineraryItem

logger = logging.getLogger(__name__)


def _t(value) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M") if hasattr(value, "strftime") else str(value)


def rewrite_trip_detail(session, uid, plan) -> None:
    """重建行程明细（snapshot_id IS NULL 的那份）：天 + 点位（含备选 1-3）。

    保存时与回填脚本共用——一处口径，避免两份实现漂移。"""
    session.execute(
        text(
            "DELETE FROM itinerary_items"
            " WHERE itinerary_id = :uid AND snapshot_id IS NULL"
        ),
        {"uid": uid},
    )
    session.execute(
        text(
            "DELETE FROM itinerary_days"
            " WHERE itinerary_id = :uid AND snapshot_id IS NULL"
        ),
        {"uid": uid},
    )
    start_date = _start_date(plan)
    for day in getattr(plan, "days", None) or []:
        session.add(
            ItineraryDay(
                id=uuid.uuid4(),
                itinerary_id=uid,
                snapshot_id=None,
                day=day.day,
                base_city=getattr(day, "base_city", None),
            )
        )
        for pos, item in enumerate(getattr(day, "items", None) or []):
            alts = getattr(item, "alternatives", None) or None
            from_city = getattr(item, "from_city", None)
            transport_no = (
                getattr(item, "train_no", None) or getattr(item, "flight_no", None)
            )
            kind = (
                "transfer"
                if from_city
                else (getattr(item, "category", None) or "visit")
            )
            alt_names = [
                (getattr(a, "name", None) or "")[:200] for a in (alts or [])
            ]
            session.add(
                ItineraryItem(
                    id=uuid.uuid4(),
                    itinerary_id=uid,
                    snapshot_id=None,
                    day=day.day,
                    poi_id=None,
                    position=float(pos),
                    start_time=getattr(item, "start_time", None),
                    end_time=getattr(item, "end_time", None),
                    draft=False,
                    name=(getattr(item, "name", None) or None),
                    item_ref=(getattr(item, "item_id", None) or None),
                    poi_ref=(getattr(item, "poi_id", None) or None),
                    kind=kind,
                    from_city=(from_city or None),
                    to_city=(getattr(item, "to_city", None) or None),
                    transport_no=(transport_no or None),
                    city=(getattr(item, "city", None) or None),
                    category=(getattr(item, "category", None) or None),
                    address=(getattr(item, "address", None) or None),
                    alternatives=(
                        [a.model_dump(mode="json") for a in alts]
                        if alts
                        else None
                    ),
                    duration_minutes=getattr(
                        item, "duration_minutes", None
                    ),
                    schedule_date=(
                        start_date + timedelta(days=day.day - 1)
                        if start_date is not None
                        else None
                    ),
                    alt1=(alt_names[0] if len(alt_names) > 0 else None),
                    alt2=(alt_names[1] if len(alt_names) > 1 else None),
                    alt3=(alt_names[2] if len(alt_names) > 2 else None),
                )
            )


def _start_date(plan) -> date | None:
    raw = getattr(plan, "start_date", None)
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def trip_header_fields(plan) -> dict:
    """TRIP HEADER 派生列（2026-11-13 用户拍板）：

    起始城市 / 结束城市 / 旅行城市一+天数 / 旅行城市二+天数 / 旅行开始日期。
    目的地城市取逐日「活动城」（条目城优先，某天全空回退 base_city）按首次
    出现排序——上海→西安→上海 这类去/回程端点不算旅行城市。
    """
    cities = [c for c in (getattr(plan, "cities", None) or []) if (c or "").strip()]
    days = getattr(plan, "days", None) or []
    per_day: list[str | None] = []
    for day in days:
        day_cities = [
            (getattr(i, "city", None) or "").strip()
            for i in (getattr(day, "items", None) or [])
            if (getattr(i, "city", None) or "").strip()
        ]
        per_day.append(day_cities[0] if day_cities else (getattr(day, "base_city", None) or None))
    dests: list[str] = []
    for city in per_day:
        if city and city not in dests:
            dests.append(city)
    counts = {city: per_day.count(city) for city in dests}
    return {
        "start_city": cities[0] if cities else None,
        "end_city": (cities[-1] if cities else None),
        "travel_start_date": _start_date(plan),
        "dest_city_1": dests[0] if dests else None,
        "dest_days_1": counts.get(dests[0]) if dests else None,
        "dest_city_2": dests[1] if len(dests) > 1 else None,
        "dest_days_2": counts.get(dests[1]) if len(dests) > 1 else None,
    }


def _items_by_key(plan) -> dict[str, object]:
    out: dict[str, object] = {}
    for day in getattr(plan, "days", None) or []:
        for item in getattr(day, "items", None) or []:
            name = (getattr(item, "name", None) or "").strip()
            if not name:
                continue
            key = f"{getattr(item, 'poi_id', None) or ''}|{name}"
            out[key] = item
    return out


def diff_plans(old_plan, new_plan) -> list[dict]:
    """行程差异（保存那一刻的 before/after）：够用、可读、可回放。"""
    old_items = _items_by_key(old_plan) if old_plan is not None else {}
    new_items = _items_by_key(new_plan) if new_plan is not None else {}
    changes: list[dict] = []
    for key, item in new_items.items():
        prev = old_items.get(key)
        day = getattr(item, "day", None)
        if prev is None:
            changes.append(
                {
                    "op": "add",
                    "name": getattr(item, "name", None),
                    "day": day,
                    "start": _t(getattr(item, "start_time", None)),
                }
            )
            continue
        if getattr(prev, "day", None) != day:
            changes.append(
                {
                    "op": "move",
                    "name": getattr(item, "name", None),
                    "from_day": getattr(prev, "day", None),
                    "to_day": day,
                }
            )
            continue
        if _t(getattr(prev, "start_time", None)) != _t(getattr(item, "start_time", None)):
            changes.append(
                {
                    "op": "retime",
                    "name": getattr(item, "name", None),
                    "day": day,
                    "from": _t(getattr(prev, "start_time", None)),
                    "to": _t(getattr(item, "start_time", None)),
                }
            )
    for key, item in old_items.items():
        if key not in new_items:
            changes.append(
                {
                    "op": "remove",
                    "name": getattr(item, "name", None),
                    "day": getattr(item, "day", None),
                }
            )
    return changes


_LABEL = {"add": "新增", "remove": "删除", "move": "换天", "retime": "改时"}


def summarize(changes: list[dict], *, limit: int = 6) -> str:
    if not changes:
        return "保存（无行程内容变化）"
    counts: dict[str, int] = {}
    for c in changes:
        counts[c["op"]] = counts.get(c["op"], 0) + 1
    head = "、".join(f"{_LABEL.get(k, k)} {v}" for k, v in sorted(counts.items()))
    names = "；".join(str(c.get("name") or "") for c in changes[:limit])
    more = "" if len(changes) <= limit else f" 等 {len(changes)} 处"
    return f"{head}：{names}{more}"


def record_trip_change(
    session_factory,
    record,
    *,
    old_plan,
    new_plan,
    actor_name: str | None = None,
    snapshot_id: str | None = None,
) -> list[dict]:
    """一次保存的完整落库：头（改名/时间/创建人）+ 明细（天/时段/点位/备选）+ 日志。"""
    itinerary_id = getattr(record, "itinerary_id", None)
    if not itinerary_id:
        return []
    uid = uuid.uuid5(uuid.NAMESPACE_URL, f"chinatrip:{itinerary_id}")
    changes = diff_plans(old_plan, new_plan)
    summary = summarize(changes)
    now = datetime.now(timezone.utc)
    try:
        with session_factory() as session, session.begin():
            row = session.get(Itinerary, uid)
            if row is not None:
                row.title = getattr(new_plan, "cities", None) and " → ".join(
                    new_plan.cities
                )[:200]
                row.cities = list(getattr(new_plan, "cities", []) or [])
                row.last_changed_at = now
                row.updated_at = now
                row.is_deleted = False
                # 2026-11-13：头派生列随行程内容更新（始/终城、目的地
                # 城市+天数、旅行开始日期）
                for _key, _value in trip_header_fields(new_plan).items():
                    setattr(row, _key, _value)
                if actor_name and not row.creator_name:
                    row.creator_name = actor_name[:100]
            rewrite_trip_detail(session, uid, new_plan)
            session.add(
                ItineraryChangeLog(
                    id=uuid.uuid4(),
                    itinerary_id=uid,
                    itinerary_ref=itinerary_id,
                    owner_device_id=getattr(record, "owner_device_id", None),
                    owner_account_id=getattr(record, "owner_account_id", None),
                    actor_name=(actor_name or getattr(record, "owner_device_id", None)),
                    changed_at=now,
                    sync_version=getattr(record, "working_sync_version", None),
                    summary=summary,
                    changes=changes,
                    snapshot_id=snapshot_id,
                )
            )
    except Exception:
        logger.warning("trip_changes: 保存变更日志失败 ref=%s", itinerary_id, exc_info=True)
    return changes
