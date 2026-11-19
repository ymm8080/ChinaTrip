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
    FixedPin,
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
    from .inputs.cuisine import cuisine_key  # R12-D 菜系键

    return CandidateItem(
        cid=cid,
        name=str(row.get("name") or ""),
        # R13（#4 修复）：真库 PoiDetailStore 行的 id 键=source_poi_id
        # （SnapshotStore 假库才叫 id）——两个键都认，ts- 会话卡片自 R8
        # 起无 poi_id 的根因（pin/换点/详情对餐馆卡受限一并解除）
        poi_id=(
            str(row["id"])
            if row.get("id")
            else (str(row["source_poi_id"]) if row.get("source_poi_id") else None)
        ),
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
        # R12-D 菜系键（同菜系不重样罚项的信号；识别不出=None）
        cuisine=(cuisine_key(row) if (row.get("category") or "") == "food" else None),
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
        # R13c（2026-11-19）：真库 PoiDetailStore 行的 id 键=source_poi_id
        # （同 R13 #4 根因的另一处）——此前 live 全链接驳档案恒空（C-08
        # 班次约束空转、引擎去程/回城卡永不渲染，live 回城卡全靠响应层）。
        if target is None or not (target.get("id") or target.get("source_poi_id")):
            continue

        def _hhmm(v):
            # R13c2（2026-11-19）：AccessServiceStore 真库行班次是 '07:30'
            # 字符串（此前只认 int 分钟——live 档案恒空=C-08 空转的另一半
            # 根因）；两种形态都归一成 HH:MM。
            if isinstance(v, int):
                return "%02d:%02d" % (v // 60, v % 60)
            s = str(v or "").strip()
            return s if ":" in s else None

        try:
            departures = [
                d for d in (_hhmm(m) for m in (row.get("outbound_times") or [])) if d
            ]
            returns = [
                d for d in (_hhmm(m) for m in (row.get("return_times") or [])) if d
            ]
            ride = int(row.get("ride_minutes") or 0)
            if ride <= 0 or not departures:
                continue
            fare = row.get("fare_cny")
            out.append(
                AccessProfile(
                    gateway=str(row.get("boarding_stop") or "乘车点"),
                    to_poi=str(target.get("id") or target["source_poi_id"]),
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
    city_days: Optional[dict] = None,
    day1_start: Optional[str] = None,
    arrival_day: Optional[int] = None,
    departure_day: Optional[int] = None,
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
            bound_cand = _row_to_candidate("c%d" % i, row, kind="requested", rid=rid)
            if bound_cand.category == "food":
                # R8-S2b 餐类必去：真餐厅 any-槽（模型自选午/晚、顶餐卡）
                bound_cand = replace(bound_cand, meal_slot="any")
            candidates.append(bound_cand)
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
            from app.services.trip_orchestrator.nlu import (
                _preference_tokens as _ptoks,
            )

            pref_tokens, pref_show = _ptoks(preferences)
        except Exception:
            pref_tokens = ()
    pool: list[dict] = []
    seen_names = set(must_names_bound)
    # R8-S4 池按行程形状配额（修多城 all-fill 空排）：总量 ≈ days×7，
    # 按城市窗天数（有 city_days：C-17 同口径，出发城/闭合尾城不取
    # 数——C-17 已灭活，纯模型负重）或城市均分分配；单城下限 6、
    # 上限 pool_limit。此前 3 城×30=90 候选的模型在 tier② 0.4
    # dtime 下 UNKNOWN，阶梯保 tier① 空前缀=空计划（live 实锤）。
    from .model.c17_city_days import _norm as _city_norm
    from .model.c17_city_days import city_day_windows

    city_list = [c for c in cities if c]
    total_target = max(12, int(days or 1) * 7)
    if city_days:
        windows = city_day_windows(city_list, days, dict(city_days))
        share = {
            c: windows[_city_norm(c)][1] - windows[_city_norm(c)][0] + 1
            for c in city_list
            if _city_norm(c) in windows
        }
    else:
        n_cities = max(1, len(city_list))
        share = {c: (int(days or 1) / n_cities) for c in city_list}
    total_w = sum(share.values()) or 1.0
    limits = {
        c: min(int(pool_limit), max(6, int(round(total_target * w / total_w))))
        for c, w in share.items()
    }
    for city, limit_city in limits.items():
        rows = list(
            store.top_pois_in_city(
                city, limit=limit_city * 2 if pref_tokens else limit_city
            )
        )
        if pref_tokens and rows:
            try:
                from app.services.trip_orchestrator.nlu import (
                    _pref_category_hit as _phit,
                )

                rows.sort(key=lambda r: 0 if _phit(r, pref_tokens, pref_show) else 1)
            except Exception:
                pass
        for row in rows[:limit_city]:
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
        pool_cand = _row_to_candidate(
            "f%d" % j, row, remote=bool(poi_id and poi_id in profiled_ids)
        )
        if pool_cand.category == "food":
            # R12-M 餐厅进餐卡（2026-11-19 用户拍板「烤鸭店进餐卡」重修）：
            # top_pois 荐点豁免入池的知名餐厅（2026-11-07 指令）此前无
            # meal_slot——模型当普通观光排 + 照贴午/晚占位卡（live 实锤
            # 北京四季民福 19:02/提督 09:00：观光卡与占位餐卡并列）。
            # 与餐类必去（R8-S2b）同口径 any-槽：被选中即顶替占位卡成
            # 命名餐卡（C-09 绑定/meals.py 命名卡/materialize.py 访视
            # 去重全链已备），另一槽照常出占位。
            pool_cand = replace(pool_cand, meal_slot="any")
        candidates.append(pool_cand)

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
            city_days=tuple(
                sorted((str(k), int(v)) for k, v in dict(city_days or {}).items())
            ),
            day1_start=day1_start,
            arrival_day=arrival_day,
            departure_day=departure_day,
        ),
        candidates=tuple(candidates),
        access_profiles=tuple(profiles),
        weather=tuple(weather),
        library_version="live",
        source="live-request",
    )


def _degenerate_plan(plan) -> bool:
    """退化计划判定（R8b-2，2026-11-18 成都空天事故）：任何一天的卡片
    全空、或全程观光卡为零 = 引擎在本请求上不可信（瞬态坏池/求解退化）
    ——按 F-35 语义回落 legacy + 披露，绝不交付空行程。

    归因背景：bisect 实证非代码回归——并行会话批写库期间池行字段瞬态
    损坏（同代码同请求 [0,6]/[6,6]/[4,6] 翻覆）；此闸是交付前最后一道
    兜底，与写入侧修复互不替代。"""
    if plan is None:
        return True
    days = list(getattr(plan, "days", None) or [])
    if not days:
        return True
    if any(not list(getattr(day, "items", None) or []) for day in days):
        return True
    from app.services.itinerary.models import VisitItem

    sights = sum(
        1
        for day in days
        for item in day.items
        if isinstance(item, VisitItem)
        and (item.category or "") not in ("food", "hotel", "transport", "transfer")
    )
    return sights == 0


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
    city_days: Optional[dict] = None,
    preferences: str = "",
    arrival_time: Optional[str] = None,
    departure_time: Optional[str] = None,
    lang: Optional[str] = None,
    arrival_day: Optional[int] = None,
    departure_day: Optional[int] = None,
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
    if flag != ENGINE_CPSAT:
        return None, None  # legacy 模式：agent.start 是正常路径，无需披露
    if not serving_ready()[0]:
        return None, _disclosed_fallback()

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

        # R13e：真会话工厂（store._factory，同 plan.py 显式注入口径）——
        # 此前传 None：access_services 里 self._factory() 直接 TypeError
        # 被吞成 0 行，live 引擎接驳档案恒空（C-08 空转、去程卡不渲染的
        # 最后一洞；键名/班次形态修复 R13c/c2 之上）。
        services = AccessServiceStore(getattr(store, "_factory", None)).access_services(
            list(cities)
        )
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
        city_days=city_days,
        avoid=[],
        weather_lookup=_weather,
        service_rows=service_rows,
        preferences=preferences or "",
        arrival_day=arrival_day,
        departure_day=departure_day,
    )
    errors = validate_snapshot(snapshot)
    if errors:
        return None, _disclosed_fallback()

    outcome = solve_trip(snapshot, flag=ENGINE_CPSAT, budget_s=budget_s)
    if (
        outcome.engine != ENGINE_CPSAT
        or getattr(outcome, "plan", None) is None
        # R8b-2 退化闸：空天/零观光绝不交付（瞬态坏池兜底）
        or _degenerate_plan(getattr(outcome, "plan", None))
    ):
        # F-35 生产语义：cpsat 无可服务计划（INFEASIBLE/UNKNOWN/装配失败
        # /退化空行程）= 回退形状——legacy 服务且必须披露，绝不静默
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
    if flag != ENGINE_CPSAT:
        return None  # legacy 模式：legacy 管线是正常路径
    if not serving_ready()[0]:
        return _disclosed_fallback()

    snapshot = _session_snapshot(session, store)
    if snapshot is None:
        return _disclosed_fallback()

    # R8b 钉位保全（铁律 19 全保位）：用户钉住的卡按 C-04 FixedPin 钉死
    # 日+时刻（NEVER_RELAX——钉冲突只会 INFEASIBLE 回落 legacy 原生保钉，
    # 绝不静默挪位）；绑定链=精确名→包含匹配；钉名同时留在 musts 里保证
    # 候选行存在（must+pin 双表示自洽：must 保存在，pin 保槽位）。
    pinned_cards = _pinned_cards(session)
    if pinned_cards:
        pins = list(getattr(snapshot.request, "pins", ()) or [])
        for card in pinned_cards:
            cand = next(
                (c for c in snapshot.candidates if c.name == card["name"]),
                None,
            )
            if cand is None:
                cand = next(
                    (
                        c
                        for c in snapshot.candidates
                        if _name_hits(card["name"], c.name)
                    ),
                    None,
                )
            if cand is not None:
                pins.append(
                    FixedPin(
                        rid="",
                        day=card["day"],
                        start_min=card["start_min"],
                        cid=cand.cid,
                    )
                )
        if pins:
            snapshot = replace(
                snapshot,
                request=replace(snapshot.request, pins=tuple(pins)),
            )

    if validate_snapshot(snapshot):
        return None

    outcome = solve_trip(snapshot, flag=ENGINE_CPSAT, budget_s=budget_s)
    if (
        outcome.engine != ENGINE_CPSAT
        or getattr(outcome, "plan", None) is None
        # R8b-2 退化闸：重排同样不出空行程（回落 legacy 原生保钉）
        or _degenerate_plan(getattr(outcome, "plan", None))
    ):
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
    """用户钉住的卡折进必去（在场保证；槽位由 _pinned_cards→C-04 钉死）。"""
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


def _pinned_cards(session) -> list:
    """带时刻的钉卡 → [{name, day, start_min}]（C-04 全保位素材）。

    无时刻的钉卡不进 pin（只靠 musts 在场保证）——C-04 的钉是时刻级
    硬钉，无时刻可钉。"""
    from app.services.itinerary.models import VisitItem

    plan = getattr(session, "plan", None)
    if plan is None:
        return []
    out = []
    for day in plan.days:
        for item in day.items:
            if (
                isinstance(item, VisitItem)
                and getattr(item, "pinned", False)
                and item.start_time is not None
                and item.day
            ):
                name = str(item.name or "").strip()
                if name:
                    out.append(
                        {
                            "name": name,
                            "day": int(item.day),
                            "start_min": item.start_time.hour * 60
                            + item.start_time.minute,
                        }
                    )
    return out


def _intake_day_no(date_iso, start_date, days: int, default_day: int) -> Optional[int]:
    """行前日期 → 行程天序（legacy _intake_target_day 同口径）：读不出/
    越界回默认（1=首日/末日）；端点日返回 None（=引擎默认形状，不显式
    传日号，快照 hash 与旧形状兼容）。"""
    import datetime as _dt

    total = max(1, int(days or 1))
    is_arrival = int(default_day) == 1

    def _role_endpoint(d: int) -> Optional[int]:
        # 端点=角色特定（R9-2 修正）：到达的默认端点=首日（末日到达=中途
        # 形状）；离开的默认端点=末日（首日离开=中途形状）。此前
        # day in (1, total) 把「2 天行程 D2 到达」误判端点归 None（live
        # 实锤：day2 地板蒸发）。
        if is_arrival:
            return None if d == 1 else d
        return None if d == total else d

    if not date_iso or not start_date:
        return _role_endpoint(max(1, min(int(default_day), total)))
    try:
        target = _dt.date.fromisoformat(str(date_iso)[:10])
        base = _dt.date.fromisoformat(str(start_date)[:10])
    except ValueError:
        return _role_endpoint(max(1, min(int(default_day), total)))
    day = (target - base).days + 1
    day = max(1, min(day, total))
    return _role_endpoint(day)


def _session_snapshot(session, store, extra_musts=None):
    """R10：会话 → 快照重建（replan/edit 共用）——musts=必去+钉卡+自造点，
    班次/分城/中途日/偏好/首日出发全参数随缝；None=引擎不可载。
    R13-#2：extra_musts=编辑 add 注入的新必去名（尾插去重——重复名会
    造同名多候选，毒 by_name 的保形/映射），绑定链自然兜底。"""
    from .types import validate_snapshot

    musts = list(
        dict.fromkeys(
            [
                *(getattr(session, "must_visits", None) or []),
                *_pinned_names(session),
                *(getattr(session, "created_sites", None) or []),
            ]
        )
    )
    for _extra in extra_musts or []:
        _name = str(_extra or "").strip()
        if _name and _name not in musts:
            musts.append(_name)
    service_rows: list = []
    try:
        from app.services.access_service_store import AccessServiceStore

        services = AccessServiceStore(getattr(store, "_factory", None)).access_services(
            list(session.cities or [])
        )
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
        city_days=dict(getattr(session, "city_days", None) or {}),
        service_rows=service_rows,
        day1_start=getattr(session, "comment_day_start", None),
        arrival_day=_intake_day_no(
            getattr(session, "arrival_date", None),
            getattr(session, "start_date", None),
            int(getattr(session, "days", 1) or 1),
            1,
        ),
        departure_day=_intake_day_no(
            getattr(session, "departure_date", None),
            getattr(session, "start_date", None),
            int(getattr(session, "days", 1) or 1),
            int(getattr(session, "days", 1) or 1),
        ),
    )
    if validate_snapshot(snapshot):
        return None
    return snapshot


def edit_session_via_trip_solver(
    session,
    *,
    store,
    ops,
    extra_assumptions=None,
    budget_s: float = 3.0,
):
    """R10（2026-11-19 拍板「anywhere legacy exists, switch to cp-sat」）：
    消息 diff 道的引擎编辑重解——F-50 edit_resolve；ops=agent 侧 dict op
    （{kind,name,poi_id,day}，move/delete）。保形=keep 钉（未被动到的
    已排观光卡钉住所在日、时刻自由）。返回 (plan|None, outcome|None)。
    R13-#2：add 类 op（{kind:"add", name, poi_id}，day 不传）走 musts
    注入道——名字尾插快照必去（绑定链兜底、覆盖层保放置），引擎自由
    择位；add 永远可映射（骨架兜底），move/delete 不可映射照旧回落。"""
    from .edit import DiffOp as _EditOp
    from .edit import edit_resolve
    from .entry import ENGINE_CPSAT, engine_flag, serving_ready

    flag = engine_flag()
    if flag != ENGINE_CPSAT or not serving_ready()[0]:
        return None, None
    # R13-#2：add 类 op（{kind:"add", name, poi_id}）不走 DiffOp——名字
    # 注入快照 musts（引擎绑定链精确名→文本匹配→骨架兜底自然处理，
    # 覆盖层保证放置或留痕不吞点）；move/delete 照旧走引擎 DiffOp。
    # 名字缺失的 add=不可映射，整批回落 legacy 原道（绝不静默丢改动）。
    ops = list(ops or [])
    if not ops:
        return None, None
    add_ops = [op for op in ops if (op.get("kind") or "") == "add"]
    edit_ops = [op for op in ops if (op.get("kind") or "") != "add"]
    add_names = []
    for op in add_ops:
        _name = str(op.get("name") or "").strip()
        if not _name:
            return None, None
        add_names.append(_name)
    snapshot = _session_snapshot(session, store, extra_musts=add_names or None)
    if snapshot is None:
        return None, None
    engine_ops = _dict_ops_to_diffops(snapshot, edit_ops) if edit_ops else []
    if engine_ops is None:
        return None, None

    # keep 钉（day 不动、时刻自由）：未被动到的已排观光卡——比
    # FixedPin（时刻也钉）弱一档，不与晨闸/餐锚/贴锚打架（live 实锤：
    # 时刻硬钉对 C-12c must 豁免面与 C-09 贴锚组合 INFEASIBLE）；
    # 餐/酒店/接驳系统卡不钉（C-09/C-13 模型自管）。
    by_poi = {c.poi_id: c.cid for c in snapshot.candidates if c.poi_id}
    by_name = {c.name: c.cid for c in snapshot.candidates if c.name}
    keep_ops = []
    for card in _seated_cards(session):
        cid = by_poi.get(card["poi_id"]) or by_name.get(card["name"])
        if not cid or cid in {op.cid for op in engine_ops}:
            continue
        keep_ops.append(_EditOp(kind="keep", cid=cid, day=card["day"]))

    # R10b keep 去重守卫：同一 cid 可命中多张已排卡（重名卡分布在不同
    # 天、或 poi/name 两道指到同池行）——day 不同的多个 keep 会让
    # presence 在两天同时为 1，模型矛盾 INFEASIBLE → 编辑道静默回落
    # legacy（用户无感知换引擎）。歧义=不钉：该 cid 的 keep 整组丢弃
    # （让引擎自由放）；同 day 重复只留一个。
    keep_days: dict = {}
    for op in keep_ops:
        keep_days.setdefault(op.cid, []).append(op.day)
    keep_ops = [
        _EditOp(kind="keep", cid=cid, day=day_list[0])
        for cid, day_list in keep_days.items()
        if len(set(day_list)) == 1
    ]

    # R10 修复（P4 遗留）：tier① fill-free 假设投影与「钉 fill presence」
    # 直接矛盾 → 编辑必 INFEASIBLE。被 move/delete/keep 点到的 fill
    # 候选全部升格 requested（用户点名语义，投影纯净）。
    # R13-#2：add 点名的 cid 也进升格面——add 名撞上池内存量 fill 行
    # （poi/名两道解析得到）时升格 requested，同用户点名语义；musts
    # 注入生出的候选本就是 requested，解析不到则此处自然空转。
    add_cids = set()
    for op in add_ops:
        _cid = by_poi.get(op.get("poi_id")) or by_name.get(op.get("name"))
        if _cid:
            add_cids.add(_cid)
    touched = {op.cid for op in engine_ops} | {op.cid for op in keep_ops} | add_cids
    if any(c.kind == "fill" for c in snapshot.candidates if c.cid in touched):
        snapshot = replace(
            snapshot,
            candidates=tuple(
                (
                    replace(
                        c,
                        kind="requested",
                        rid=(c.rid or "edit-%s" % c.cid),
                    )
                    if (c.cid in touched and c.kind == "fill")
                    else c
                )
                for c in snapshot.candidates
            ),
        )

    try:
        outcome = edit_resolve(
            snapshot, None, [*engine_ops, *keep_ops], budget_s=budget_s
        )
    except Exception:
        return None, None
    solution = getattr(outcome, "solution", None)
    if solution is None or not getattr(outcome, "ops_applied", None):
        return None, None
    from .assembly.materialize import materialize_plan

    plan = materialize_plan(solution, snapshot)
    if _degenerate_plan(plan):
        return None, None
    if extra_assumptions:
        plan.assumptions = list(getattr(plan, "assumptions", []) or []) + list(
            extra_assumptions
        )
    return plan, outcome


def _dict_ops_to_diffops(snapshot, ops):
    """R10：agent 侧 dict op（{kind,name,poi_id,day}）→ 引擎 DiffOp——
    cid 按 poi/name 匹配；同名多行=歧义不进 by_name（只信 poi_id；两道
    都无 → None 让调用方回落 legacy，绝不按「第一个同名」错钉别的卡）。"""
    from .edit import DiffOp as _Op

    name_cids: dict = {}
    for c in snapshot.candidates:
        if c.name:
            name_cids.setdefault(c.name, set()).add(c.cid)
    by_name = {
        name: next(iter(cids)) for name, cids in name_cids.items() if len(cids) == 1
    }
    by_poi = {}
    for c in snapshot.candidates:
        if c.poi_id:
            by_poi.setdefault(c.poi_id, c.cid)
    out = []
    for op in ops or []:
        cid = by_poi.get(op.get("poi_id")) or by_name.get(op.get("name"))
        if not cid:
            return None
        kind = op.get("kind")
        if kind == "move":
            day = op.get("day")
            if not day:
                return None
            out.append(_Op(kind="move", cid=cid, day=int(day)))
        elif kind == "delete":
            out.append(_Op(kind="delete", cid=cid))
        else:
            return None
    return out or None


def _seated_cards(session) -> list:
    """R10：已排卡的 (name, poi_id, day, start_min)——编辑保形素材
    （全部有时刻的观光/餐卡，不只 pinned）。"""
    from app.services.itinerary.models import VisitItem

    plan = getattr(session, "plan", None)
    if plan is None:
        return []
    out = []
    for day in plan.days:
        for item in day.items:
            if (
                isinstance(item, VisitItem)
                and item.start_time is not None
                # R10：只钉观光卡——餐/酒店/接驳是系统合成卡（C-09/C-13
                # 模型侧自管），钉它们会与餐槽/酒店锚约束冲突（live 实锤）
                and (item.category or "")
                not in ("food", "hotel", "transport", "transfer")
            ):
                name = str(item.name or "").strip()
                if name:
                    out.append(
                        {
                            "name": name,
                            "poi_id": getattr(item, "poi_id", None),
                            "day": int(getattr(item, "day", day.day) or day.day),
                            "start_min": item.start_time.hour * 60
                            + item.start_time.minute,
                        }
                    )
    return out


def _disclosed_fallback():
    """R13（#1 修复）：cpsat 旗下引擎不可服务（快照验证失败/未就绪）→
    返回披露型 fallback outcome——绝不裸 (None, None) 静默落 legacy
    （旧行为绕过了 api 缝的披露 append=违反「绝不静默」原则）。"""
    from .entry import (
        ENGINE_CPSAT,
        ENGINE_LEGACY,
        FALLBACK_DISCLOSURE,
        SolveOutcome,
    )

    return SolveOutcome(
        engine=ENGINE_LEGACY,
        requested=ENGINE_CPSAT,
        fallback=True,
        disclosures=[dict(FALLBACK_DISCLOSURE)],
    )
