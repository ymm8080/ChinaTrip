"""F-03/F-10 live snapshot (P3 seam): request fields + live stores →
FactSnapshot schema v2, plus the flag-gated session generator the api seam
calls via ``asyncio.to_thread`` (F-42).

The builder is READ-ONLY over the stores: musts bind through the POI store
exact-name → text-match fallback (an unbindable must keeps a skeleton
requested candidate — coverage surfaces honestly, never a silent drop);
the pool reuses ``top_pois_in_city`` (legacy hygiene: no food/hotel, active
status, coordinates first); remote rows get F-14 access profiles converted
from the AccessServiceStore timetable rows; weather rows are bilingualised
so both the legacy 雨 scan and F-13 ``rain`` matching work.
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from typing import Any, Callable, Optional

from .types import (
    AccessProfile,
    CandidateItem,
    FactSnapshot,
    RequestedItem,
    TripRequest,
)

POOL_LIMIT_PER_CITY = 30
WEATHER_MARKS_RAIN = "雨"
WEATHER_MARK_HEAVY = ("大", "暴")


def bilingual_weather(text: Optional[str]) -> Optional[str]:
    """legacy zh weather text → bilingual so F-13 ``rain`` also matches."""
    if not text:
        return None
    if WEATHER_MARKS_RAIN not in text and "rain" not in text.lower():
        return text
    heavy = any(mark in text for mark in WEATHER_MARK_HEAVY) or "heavy" in text.lower()
    tag = " (heavy rain)" if heavy else " (rain)"
    return text + tag


def _row_location(row: dict[str, Any]):
    loc = row.get("location")
    if isinstance(loc, (tuple, list)) and len(loc) == 2:
        try:
            return float(loc[0]), float(loc[1])
        except (TypeError, ValueError):
            return None, None
    return None, None


def _row_to_candidate(
    cid: str,
    row: dict[str, Any],
    *,
    kind: str = "fill",
    rid: Optional[str] = None,
    remote: bool = False,
) -> CandidateItem:
    lon, lat = _row_location(row)
    return CandidateItem(
        cid=cid,
        name=str(row.get("name") or ""),
        poi_id=(str(row["id"]) if row.get("id") else None),
        kind=kind,  # type: ignore[arg-type]
        rid=rid,
        category=row.get("category"),
        tier=row.get("_tier") or row.get("tier"),
        lon=lon,
        lat=lat,
        opening_hours=row.get("opening_hours"),
        best_visit_time=row.get("best_visit_time"),
        indoor=row.get("indoor"),
        rain_ok=row.get("rain_ok"),
        suggested_duration_min=row.get("suggested_duration_min"),
        remote=remote,
        city=row.get("city"),
    )


def _name_hits(name: str, other: str) -> bool:
    """Exact or containment both ways (the legacy _name_dup family spirit)."""
    if not name or not other:
        return False
    return name == other or name in other or other in name


def _access_profiles_for(
    pool: list[dict], service_rows: list[dict]
) -> list[AccessProfile]:
    """F-14: AccessServiceStore rows → AccessProfile bound to pool poi ids."""
    by_name = {str(r.get("name") or ""): r for r in pool}
    out: list[AccessProfile] = []
    for row in service_rows:
        poi_name = str(row.get("poi_name") or "")
        target = next(
            (r for n, r in by_name.items() if n and _name_hits(poi_name, n)), None
        )
        if target is None or not target.get("id"):
            continue
        try:
            departures = [
                "%02d:%02d" % (m // 60, m % 60)
                for m in (row.get("outbound_times") or [])
                if isinstance(m, int)
            ]
            returns = [
                "%02d:%02d" % (m // 60, m % 60)
                for m in (row.get("return_times") or [])
                if isinstance(m, int)
            ]
            ride = int(row.get("ride_minutes") or 0)
            if ride <= 0 or not departures:
                continue
            fare = row.get("fare_cny")
            out.append(
                AccessProfile(
                    gateway=str(row.get("boarding_stop") or "乘车点"),
                    to_poi=str(target["id"]),
                    ride_minutes=ride,
                    wait_minutes=int(row.get("outbound_frequency_minutes") or 0),
                    last_mile_minutes=int(row.get("last_mile_minutes") or 0),
                    departures=tuple(departures),
                    returns=tuple(returns),
                    fare_text=(
                        ("¥%s" % fare)
                        if fare not in (None, "")
                        else row.get("fare_note")
                    ),
                    operator=row.get("operator"),
                )
            )
        except (TypeError, ValueError):
            continue  # malformed timetable row: skip, never crash the seam
    return out


def _mode_from_no(no: Optional[str]) -> Optional[str]:
    """车次/航班号 → 交通模式（G/D/C/K/T/Z+数字=火车；航司码+数字=飞机）。"""
    import re

    text = (no or "").strip().upper()
    if not text:
        return None
    if re.match(r"^[GDKTCZYL]\d", text):
        return "train"
    if re.match(r"^[A-Z]{2}\d{3,4}$", text) or re.match(r"^\d{4,5}$", text):
        return "flight"
    return None


def _explicit_mode(intercity_mode):
    """用户指定城际方式（train/flight）→ 全程模式口径；auto/None=legacy
    距离闸语义，引擎侧不强制（缺省）。班次号推出的模式更具体，优先于
    全程口径（同 legacy：特定班次胜过笼统方式）。"""
    return intercity_mode if intercity_mode in ("train", "flight") else None


def snapshot_from_request(
    *,
    cities: list[str],
    days: int,
    start_date: Optional[str],
    musts: list[str],
    store,
    arrival_time: Optional[str] = None,
    departure_time: Optional[str] = None,
    arrival_no: Optional[str] = None,
    departure_no: Optional[str] = None,
    intercity_mode: Optional[str] = None,
    avoid: Optional[list[str]] = None,
    weather_lookup: Optional[Callable[[str, str], Any]] = None,
    service_rows: Optional[list[dict]] = None,
    preferences: str = "",
    pool_limit: int = POOL_LIMIT_PER_CITY,
) -> FactSnapshot:
    """Build a schema-v2 FactSnapshot from request fields + live stores."""
    avoid = [a for a in (avoid or []) if a]
    request_musts: list[RequestedItem] = []
    candidates: list[CandidateItem] = []
    must_names_bound: set[str] = set()
    must_rows: list[dict] = []

    for i, name in enumerate(musts, start=1):
        rid = "r%d" % i
        row = None
        for city in cities:
            row = store.candidate_by_name(city, name)
            if row:
                break
        if row is None:
            # text-match fallback (exact-name miss: 别名/简称)
            for city in cities:
                hits = store.match_text_names(city, name, limit=1)
                if hits:
                    row = hits[0]
                    break
        if row is not None:
            request_musts.append(
                RequestedItem(
                    rid=rid,
                    name=str(row.get("name") or name),
                    poi_id=str(row["id"]) if row.get("id") else None,
                    kind="must",
                    importance=3,
                )
            )
            must_rows.append(row)
            candidates.append(
                _row_to_candidate("c%d" % i, row, kind="requested", rid=rid)
            )
            must_names_bound.add(str(row.get("name") or ""))
        else:
            # unbindable must: skeleton requested candidate — the coverage
            # tier surfaces it honestly (timed anywhere legal or unplaced),
            # never a silent drop (B-01).
            request_musts.append(
                RequestedItem(rid=rid, name=name, kind="must", importance=3)
            )
            candidates.append(
                CandidateItem(cid="c%d" % i, name=name, kind="requested", rid=rid)
            )
            must_names_bound.add(name)

    # R8 偏好池 boost（同源 _preference_tokens/_pref_category_hit）：偏好
    # 非空时取 2×池再按「偏好命中在前、组内保库序（tier 梯子）」稳定
    # 重排后截回 pool_limit——legacy「偏好位在 tier 之前」的池侧同款；
    # 偏好为空时行为与旧版完全一致（单倍取数、不重排）。
    pref_tokens: tuple = ()
    pref_show = False
    if (preferences or "").strip():
        try:
            from app.services.agent.plan import (
                _preference_tokens as _ptoks,
            )

            pref_tokens, pref_show = _ptoks(preferences)
        except Exception:
            pref_tokens = ()
    pool: list[dict] = []
    seen_names = set(must_names_bound)
    for city in cities:
        rows = list(
            store.top_pois_in_city(
                city, limit=pool_limit * 2 if pref_tokens else pool_limit
            )
        )
        if pref_tokens and rows:
            try:
                from app.services.agent.plan import (
                    _pref_category_hit as _phit,
                )

                rows.sort(key=lambda r: 0 if _phit(r, pref_tokens, pref_show) else 1)
            except Exception:
                pass
        for row in rows[:pool_limit]:
            name = str(row.get("name") or "")
            if not name or name in seen_names:
                continue
            if any(_name_hits(name, a) for a in avoid):
                continue
            if any(_name_hits(name, m) for m in must_names_bound):
                continue
            seen_names.add(name)
            pool.append(row)

    profiles = _access_profiles_for(must_rows + pool, service_rows or [])
    profiled_ids = {p.to_poi for p in profiles}
    for k, cand in enumerate(candidates):
        if cand.kind == "requested" and cand.poi_id in profiled_ids:
            candidates[k] = replace(cand, remote=True)
    for j, row in enumerate(pool, start=1):
        poi_id = str(row["id"]) if row.get("id") else None
        candidates.append(
            _row_to_candidate(
                "f%d" % j, row, remote=bool(poi_id and poi_id in profiled_ids)
            )
        )

    weather: list[tuple] = []
    if weather_lookup is not None and start_date:
        base = datetime.date.fromisoformat(start_date)
        poi_city = {c.poi_id: c.city for c in candidates if c.poi_id and c.city}
        for day in range(1, max(1, days) + 1):
            iso = (base + datetime.timedelta(days=day - 1)).isoformat()
            for city in cities:
                try:
                    windows = weather_lookup(city, iso)
                except Exception:
                    windows = None
                text = bilingual_weather(
                    windows[0] if isinstance(windows, tuple) else windows
                )
                if not text:
                    continue
                for poi_id, pc in poi_city.items():
                    if pc == city:
                        weather.append((poi_id, iso, text))

    return FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=max(1, days),
            cities=tuple(cities),
            start_date=start_date,
            musts=tuple(request_musts),
            arrival_time=arrival_time,
            departure_time=departure_time,
            arrival_mode=_mode_from_no(arrival_no) or _explicit_mode(intercity_mode),
            departure_mode=_mode_from_no(departure_no)
            or _explicit_mode(intercity_mode),
            preferences=preferences or "",
        ),
        candidates=tuple(candidates),
        access_profiles=tuple(profiles),
        weather=tuple(weather),
        library_version="live",
        source="live-request",
    )


def generate_session_via_trip_solver(
    *,
    device_id: str,
    cities: list[str],
    days: int,
    start_date: Optional[str],
    musts: list[str],
    store,
    arrival_no: Optional[str] = None,
    departure_no: Optional[str] = None,
    intercity_mode: Optional[str] = None,
    preferences: str = "",
    arrival_time: Optional[str] = None,
    departure_time: Optional[str] = None,
    lang: Optional[str] = None,
    weather_lookup: Optional[Callable[[str, str], Any]] = None,
    budget_s: float = 3.0,
) -> tuple:
    """Flag-gated seam core (sync — the api wraps in ``asyncio.to_thread``).

    Returns ``(PlanSession | None, SolveOutcome)``: a ready session when the
    model engine served; ``(None, outcome)`` means the caller must run the
    legacy cascade — appending ``outcome.disclosures`` when it fell back.
    """
    from app.services.agent.plan import PlanSession

    from .entry import ENGINE_CPSAT, engine_flag, serving_ready, solve_trip
    from .types import validate_snapshot

    flag = engine_flag()
    if flag != ENGINE_CPSAT or not serving_ready()[0]:
        return None, None

    def _weather(city: str, iso: str):
        if weather_lookup is None:
            return None
        try:
            return weather_lookup(city, iso)
        except Exception:
            return None

    service_rows: list[dict] = []
    try:
        from app.services.access_service_store import AccessServiceStore

        services = AccessServiceStore(None).access_services(list(cities))
        service_rows = list(services or [])
    except Exception:
        service_rows = []

    snapshot = snapshot_from_request(
        cities=cities,
        days=days,
        start_date=start_date,
        musts=musts,
        store=store,
        arrival_time=arrival_time,
        departure_time=departure_time,
        arrival_no=arrival_no,
        departure_no=departure_no,
        intercity_mode=intercity_mode,
        avoid=[],
        weather_lookup=_weather,
        service_rows=service_rows,
        preferences=preferences or "",
    )
    errors = validate_snapshot(snapshot)
    if errors:
        return None, None

    outcome = solve_trip(snapshot, flag=ENGINE_CPSAT, budget_s=budget_s)
    if outcome.engine != ENGINE_CPSAT or getattr(outcome, "plan", None) is None:
        # F-35 生产语义：cpsat 无可服务计划（INFEASIBLE/UNKNOWN/装配失败）
        # = 回退形状——legacy 服务且必须披露，绝不静默
        from .entry import FALLBACK_DISCLOSURE

        outcome.fallback = True
        outcome.disclosures = [dict(FALLBACK_DISCLOSURE)]
        return None, outcome

    session = PlanSession(
        session_id="ts-%s" % datetime.datetime.now().strftime("%Y%m%d%H%M%S%f"),
        device_id=device_id,
        cities=list(cities),
        days=max(1, days),
        start_date=start_date,
        must_visits=list(musts),
        arrival_time=arrival_time,
        departure_time=departure_time,
        preferences=preferences or "",
        lang=lang,
    )
    session.plan = outcome.plan
    session.assumptions = list(getattr(outcome.plan, "assumptions", []) or [])
    session.state = "ready"
    return session, outcome


def replan_session_via_trip_solver(
    session,
    *,
    store,
    extra_assumptions=None,
    budget_s: float = 3.0,
):
    """F-35 二期会话级重解（2026-11-18 拍板「偏好重排也要换 CP-SAT」）。

    就地换引擎：session_id/history/会话状态全保留（引擎连续性），plan
    换成模型引擎产物；用户钉住的卡折进必去（在场保证，槽位重解——
    F-50 FixedPin 全保位是后续升级位）。返回 SolveOutcome：
    - engine=cpsat 且 plan 落位 → 调用方直接收工；
    - fallback=True → 调用方走 legacy 并附 disclosures[0]；
    - None（旗未开/快照不可验证）→ 调用方走 legacy，行为零变化。
    """
    from .entry import (
        ENGINE_CPSAT,
        FALLBACK_DISCLOSURE,
        engine_flag,
        serving_ready,
        solve_trip,
    )
    from .types import validate_snapshot

    flag = engine_flag()
    if flag != ENGINE_CPSAT or not serving_ready()[0]:
        return None

    musts = list(
        dict.fromkeys(
            [
                *(getattr(session, "must_visits", None) or []),
                *_pinned_names(session),
            ]
        )
    )
    service_rows: list[dict] = []
    try:
        from app.services.access_service_store import AccessServiceStore

        services = AccessServiceStore(None).access_services(list(session.cities or []))
        service_rows = list(services or [])
    except Exception:
        service_rows = []

    snapshot = snapshot_from_request(
        cities=list(session.cities or []),
        days=max(1, int(getattr(session, "days", 1) or 1)),
        start_date=getattr(session, "start_date", None),
        musts=musts,
        store=store,
        arrival_time=getattr(session, "arrival_time", None),
        departure_time=getattr(session, "departure_time", None),
        arrival_no=getattr(session, "arrival_no", None),
        departure_no=getattr(session, "departure_no", None),
        avoid=list(getattr(session, "avoid_sites", None) or []),
        preferences=(getattr(session, "preferences", "") or ""),
        service_rows=service_rows,
    )
    if validate_snapshot(snapshot):
        return None

    outcome = solve_trip(snapshot, flag=ENGINE_CPSAT, budget_s=budget_s)
    if outcome.engine != ENGINE_CPSAT or getattr(outcome, "plan", None) is None:
        outcome.fallback = True
        outcome.disclosures = [dict(FALLBACK_DISCLOSURE)]
        return outcome

    session.plan = outcome.plan
    session.assumptions = list(getattr(outcome.plan, "assumptions", []) or []) + list(
        extra_assumptions or []
    )
    session.state = "ready"
    session.brief_notes = []
    return outcome


def _pinned_names(session) -> list:
    """用户钉住的卡折进必去（F-51 v1：在场保证；槽位保位是 F-50 升级位）。"""
    from app.services.itinerary.models import VisitItem

    plan = getattr(session, "plan", None)
    if plan is None:
        return []
    out = []
    for day in plan.days:
        for item in day.items:
            if isinstance(item, VisitItem) and getattr(item, "pinned", False):
                name = str(item.name or "").strip()
                if name:
                    out.append(name)
    return out
