"""Iron-rule hard validators for the itinerary mutation pipeline (design §6.0/§6.4).

Server-checkable subset of iron rules 0-23. Every validator is a pure
function over the shared domain models — no I/O, no LLM, no DB.

铁律归属映射表（哪条在哪儿管）:

本模块（rules.py）校验:
    1 时间冲突（同日 VisitItem 区间重叠）→ validate_plan
    2 营业时间（超 poi_hours 窗口；无数据跳过）→ validate_plan
    3 地理自洽·简化（城市归属 / base_city 跳变）→ validate_plan
    4 跨城衔接缓冲（VisitItem↔TransferItem ≥90 分钟）→ validate_plan
    5 同日多段跨城（seq 递增唯一 + 互相缓冲）→ validate_plan
    6 节奏量化（日步行 ≤15km×人群系数；游览占比 ≥55%）→ validate_plan
    10 只动当天及之后 → validate_change_scope
    19 钉死点（pinned 不得被移动/改时间/删除）→ validate_pinned

不归本校验器管（服务端纯函数无法判定，归属如下）:
    0 一切变更走统一 diff 管线 → pipeline.mutate（本包）
    7 交通可达 → CP-SAT 求解器 solve_itinerary（§6.9）
    8 3 秒延迟预算 → API 网关 / 性能监控（非行程域）
    9 重排带 reasoning → Agent 输出层填 ChangeSummary.reasoning
    11 执行模式不动过去（生成端）→ 执行模式会话编排层
    12 同步端不覆盖过去 → 多端同步服务
    13 时区以行程城市为准 → 客户端时区服务（本模块时间为本地时间）
    14 解析期 LLM 零写权限 → 解析阶段工具白名单（无行程写入工具）
    15 不可信内容 quarantine → extraction.py::scan_injection
    16 快照不可变，恢复只写工作副本 → 快照服务（只读恢复）
    17 执行中切换执行版 = 受限重排 → 执行版管理（复用 from_day 语义）
    18 离线禁止切到未下载离线包的版本 → 客户端离线包管理
    20 餐饮插入不挤占核心游览 → recommend_restaurants 工具
    21 语音/图片数据本地闭环 → 独立语音服务（§6.10，禁云 API）
    22 行动只 handoff 不代客交易 → 行动编排层（仅出 deeplink）
    23 退改签透明前置（无摘要禁止跳转）→ handoff 确认卡片渲染层
"""

from datetime import time
from math import asin, cos, radians, sin, sqrt

from app.services.itinerary.models import (
    CROWD_COEF_MAX,
    CROWD_COEF_MIN,
    INTERCITY_BUFFER_MINUTES,
    VALID_TOUR_RATIO_MIN,
    WALK_KM_PER_DAY_MAX,
    CrowdProfile,
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    PoiHours,
    RuleSeverity,
    RuleViolation,
    TransferItem,
    ValidationReport,
    VisitItem,
)
from app.services.lang_ctx import L

# Iron rule 6 crowd coefficient band (models.py pins the 0.6-1.2 bounds).
CROWD_COEFFICIENTS: dict[CrowdProfile, float] = {
    CrowdProfile.slow: CROWD_COEF_MIN,
    CrowdProfile.normal: 1.0,
    CrowdProfile.fast: CROWD_COEF_MAX,
}

_EARTH_RADIUS_KM = 6371.0


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _fmt(t: time | None) -> str:
    return t.strftime("%H:%M") if t is not None else "?"


def _norm_city(name: str) -> str:
    # LLM 写 POI city 常带后缀（"杭州市"/"上海市"），用户输入行程城市不带——
    # 归一化后再比较，否则规则 3 对合法行程满屏假警告。
    name = name.strip()
    return name[:-1] if name.endswith("市") else name


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = radians(a.lat), radians(b.lat)
    dlat, dlon = lat2 - lat1, radians(b.lon) - radians(a.lon)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2.0 * _EARTH_RADIUS_KM * asin(sqrt(h))


def _eff_end_minutes(item: VisitItem | TransferItem) -> int | None:
    """end_time in minutes-of-day, or start+duration when end missing."""
    if item.end_time is not None:
        return _minutes(item.end_time)
    if item.start_time is not None and item.duration_minutes is not None:
        return _minutes(item.start_time) + item.duration_minutes
    return None


def _report(violations: list[RuleViolation]) -> ValidationReport:
    has_error = any(v.severity == RuleSeverity.error for v in violations)
    return ValidationReport(ok=not has_error, violations=violations)


# --- iron rule 1: same-day VisitItem time overlap -------------------------


def _check_time_conflicts(day_no: int, visits: list[VisitItem]) -> list[RuleViolation]:
    timed = sorted(
        (v for v in visits if v.start_time is not None and v.end_time is not None),
        key=lambda v: (v.start_time, v.end_time),
    )
    out = []
    for prev, cur in zip(timed, timed[1:]):
        if _minutes(prev.end_time) > _minutes(cur.start_time):
            out.append(
                RuleViolation(
                    rule_id=1,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 {prev.name}({_fmt(prev.start_time)}-"
                        f"{_fmt(prev.end_time)}) 与 {cur.name}({_fmt(cur.start_time)}-"
                        f"{_fmt(cur.end_time)}) 时间区间重叠",
                        f"Day {day_no}: {prev.name}({_fmt(prev.start_time)}-"
                        f"{_fmt(prev.end_time)}) and {cur.name}({_fmt(cur.start_time)}-"
                        f"{_fmt(cur.end_time)}) time ranges overlap",
                    ),
                    item_ids=[prev.item_id, cur.item_id],
                    day=day_no,
                )
            )
    return out


# --- iron rule 2: opening hours -------------------------------------------


def _check_opening_hours(
    day_no: int, visits: list[VisitItem], hours: dict[str, PoiHours]
) -> list[RuleViolation]:
    out = []
    for v in visits:
        h = hours.get(v.poi_id) if v.poi_id else None
        if h is None:
            continue  # 无营业时间数据，跳过（铁律 2 口径）
        bad_start = v.start_time is not None and v.start_time < h.opens
        bad_end = v.end_time is not None and v.end_time > h.closes
        if bad_start or bad_end:
            out.append(
                RuleViolation(
                    rule_id=2,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 {v.name}"
                        f"({_fmt(v.start_time)}-{_fmt(v.end_time)})"
                        f"超出营业时间 {_fmt(h.opens)}-{_fmt(h.closes)}",
                        f"Day {day_no}: {v.name}({_fmt(v.start_time)}-"
                        f"{_fmt(v.end_time)}) is outside opening hours "
                        f"{_fmt(h.opens)}-{_fmt(h.closes)}",
                    ),
                    item_ids=[v.item_id],
                    day=day_no,
                )
            )
    return out


# --- iron rule 4: visit <-> transfer connection buffer --------------------


def _check_transfer_buffer(
    day_no: int, visits: list[VisitItem], transfers: list[TransferItem]
) -> list[RuleViolation]:
    buf = INTERCITY_BUFFER_MINUTES
    out = []
    for tr in transfers:
        if tr.start_time is None:
            continue
        tr_start = _minutes(tr.start_time)
        tr_end = _eff_end_minutes(tr)
        tr_end_window = tr_end if tr_end is not None else tr_start
        for v in visits:
            if v.start_time is None or v.end_time is None:
                # Untimed visits are invisible to every downstream check, so
                # a "day 3 in Xiamen + 9am flight" layout ships silently.
                # Hard-fail it: the caller must time or relocate the visit.
                out.append(
                    RuleViolation(
                        rule_id=4,
                        severity=RuleSeverity.error,
                        message=L(
                            f"第{day_no}天 跨城交通 {tr.from_city}→{tr.to_city}"
                            f" 当天的景点「{v.name}」没有起止时间，无法校验衔接，"
                            "请安排时间或移动到其他天",
                            f'Day {day_no}: sight "{v.name}" on the day of the '
                            f"intercity transfer {tr.from_city}→{tr.to_city} has no "
                            "start/end time, so the connection cannot be checked. "
                            "Schedule a time or move it to another day",
                        ),
                        item_ids=[v.item_id],
                        day=day_no,
                    )
                )
                continue
            vs, ve = _minutes(v.start_time), _minutes(v.end_time)
            if vs < tr_end_window + buf and ve > tr_start - buf:
                out.append(
                    RuleViolation(
                        rule_id=4,
                        severity=RuleSeverity.error,
                        message=L(
                            f"第{day_no}天 {v.name} 与跨城交通"
                            f"{tr.from_city}→{tr.to_city}"
                            f"({_fmt(tr.start_time)}-{_fmt(tr.end_time)})"
                            f"衔接缓冲不足 {buf} 分钟",
                            f"Day {day_no}: {v.name} and intercity transfer "
                            f"{tr.from_city}→{tr.to_city}"
                            f"({_fmt(tr.start_time)}-{_fmt(tr.end_time)}) have "
                            f"less than {buf} minutes of connection buffer",
                        ),
                        item_ids=[v.item_id, tr.item_id],
                        day=day_no,
                    )
                )
    return out


# --- iron rule 5: same-day multi-transfer seq order + mutual buffer -------


def _check_transfer_sequence(
    day_no: int, transfers: list[TransferItem]
) -> list[RuleViolation]:
    out = []
    if len(transfers) < 2:
        return out
    seqs = [t.seq for t in transfers]
    if len(set(seqs)) != len(seqs):
        out.append(
            RuleViolation(
                rule_id=5,
                severity=RuleSeverity.error,
                message=L(
                    f"第{day_no}天 多段跨城交通 seq 必须递增且唯一，实际为 {seqs}",
                    f"Day {day_no}: multiple same-day intercity transfers must "
                    f"have strictly increasing unique seq, got {seqs}",
                ),
                item_ids=[t.item_id for t in transfers],
                day=day_no,
            )
        )
    ordered = sorted(transfers, key=lambda t: t.seq)
    for prev, cur in zip(ordered, ordered[1:]):
        prev_end = _eff_end_minutes(prev)
        cur_start = _minutes(cur.start_time) if cur.start_time is not None else None
        if prev_end is None or cur_start is None:
            continue
        gap = cur_start - prev_end
        if gap < INTERCITY_BUFFER_MINUTES:
            out.append(
                RuleViolation(
                    rule_id=5,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 跨城交通 {prev.from_city}→{prev.to_city} 与 "
                        f"{cur.from_city}→{cur.to_city} 衔接缓冲 {gap} 分钟 < "
                        f"{INTERCITY_BUFFER_MINUTES} 分钟（含时间重叠 / seq 顺序颠倒）",
                        f"Day {day_no}: intercity transfers {prev.from_city}→"
                        f"{prev.to_city} and {cur.from_city}→{cur.to_city} "
                        f"connection buffer {gap} min < {INTERCITY_BUFFER_MINUTES} "
                        "min (includes time overlap / seq out of order)",
                    ),
                    item_ids=[prev.item_id, cur.item_id],
                    day=day_no,
                )
            )
    return out


# --- iron rule 6: pace (walk distance + effective tour ratio) -------------


def _check_pace(
    day_no: int,
    day_items: list[VisitItem | TransferItem],
    visits: list[VisitItem],
    crowd_profile: CrowdProfile,
) -> list[RuleViolation]:
    out = []
    # walking distance: adjacent same-day visits, straight-line (haversine)
    # approximation; segments touching a location-less item are skipped.
    km = sum(
        haversine_km(a.location, b.location)
        for a, b in zip(visits, visits[1:])
        if a.location is not None and b.location is not None
    )
    located = [v for v in visits if v.location is not None]
    limit = WALK_KM_PER_DAY_MAX * CROWD_COEFFICIENTS[crowd_profile]
    if located and km > limit:
        out.append(
            RuleViolation(
                rule_id=6,
                severity=RuleSeverity.warning,
                message=L(
                    f"第{day_no}天 步行距离约 {km:.1f} km（直线距离近似）超过 "
                    f"{limit:.1f} km 上限（{crowd_profile.value} 人群系数）",
                    f"Day {day_no}: estimated walking distance ~{km:.1f} km "
                    f"(straight-line approximation) exceeds the {limit:.1f} km "
                    f"limit ({crowd_profile.value} crowd coefficient)",
                ),
                item_ids=[v.item_id for v in located],
                day=day_no,
            )
        )
    # effective sightseeing ratio: Σ visit duration / day time span.
    timed = [
        i
        for i in day_items
        if i.start_time is not None and _eff_end_minutes(i) is not None
    ]
    if timed:
        span = max(_eff_end_minutes(i) for i in timed) - min(
            _minutes(i.start_time) for i in timed
        )
        total = sum(v.duration_minutes for v in visits if v.duration_minutes)
        if span > 0 and total > 0 and total / span < VALID_TOUR_RATIO_MIN:
            out.append(
                RuleViolation(
                    rule_id=6,
                    severity=RuleSeverity.warning,
                    message=L(
                        f"第{day_no}天 有效游览时长占比 {total / span:.0%} 低于 "
                        f"{VALID_TOUR_RATIO_MIN:.0%}",
                        f"Day {day_no}: effective sightseeing ratio "
                        f"{total / span:.0%} is below {VALID_TOUR_RATIO_MIN:.0%}",
                    ),
                    item_ids=[
                        v.item_id for v in visits if v.duration_minutes is not None
                    ],
                    day=day_no,
                )
            )
    return out


# --- iron rule 3 (simplified): geography sanity ---------------------------


def _check_visit_cities(
    plan: ItineraryPlan, day: DayPlan, visits: list[VisitItem]
) -> list[RuleViolation]:
    out = []
    plan_cities = {_norm_city(c) for c in plan.cities}
    for v in visits:
        if _norm_city(v.city) not in plan_cities:
            out.append(
                RuleViolation(
                    rule_id=3,
                    severity=RuleSeverity.warning,
                    message=L(
                        f"第{day.day}天 {v.name} 所在城市 {v.city} "
                        f"不在行程城市 {plan.cities} 中",
                        f"Day {day.day}: {v.name} is in city {v.city}, which is "
                        f"not among the itinerary cities {plan.cities}",
                    ),
                    item_ids=[v.item_id],
                    day=day.day,
                )
            )
    return out


def _check_base_city_jumps(plan: ItineraryPlan) -> list[RuleViolation]:
    out = []
    for prev, cur in zip(plan.days, plan.days[1:]):
        # 跨城交通可以在 base 切换的前一天（出发日）或当天（到达日）——
        # 只看"变化当日"会把前一天已乘车的正常行程误报为跳变。
        jumped = _norm_city(cur.base_city) != _norm_city(prev.base_city)
        has_transfer = any(isinstance(i, TransferItem) for i in prev.items) or any(
            isinstance(i, TransferItem) for i in cur.items
        )
        if jumped and not has_transfer:
            out.append(
                RuleViolation(
                    rule_id=3,
                    severity=RuleSeverity.warning,
                    message=L(
                        f"第{cur.day}天 基准城市从 {prev.base_city} 跳变到 "
                        f"{cur.base_city} 但当日无跨城交通",
                        f"Day {cur.day}: base city jumps from {prev.base_city} to "
                        f"{cur.base_city} with no intercity transfer that day",
                    ),
                    day=cur.day,
                )
            )
    return out


# --- public API -----------------------------------------------------------


def validate_plan(
    plan: ItineraryPlan,
    *,
    poi_hours: list[PoiHours],
    crowd_profile: CrowdProfile = CrowdProfile.normal,
) -> ValidationReport:
    """Validate iron rules 1/2/3/4/5/6 over a whole plan (pure function)."""
    hours = {h.poi_id: h for h in poi_hours}
    violations: list[RuleViolation] = []
    for day in plan.days:
        visits = [i for i in day.items if isinstance(i, VisitItem)]
        transfers = [i for i in day.items if isinstance(i, TransferItem)]
        violations += _check_time_conflicts(day.day, visits)
        violations += _check_opening_hours(day.day, visits, hours)
        violations += _check_transfer_buffer(day.day, visits, transfers)
        violations += _check_transfer_sequence(day.day, transfers)
        violations += _check_pace(day.day, day.items, visits, crowd_profile)
        violations += _check_visit_cities(plan, day, visits)
    violations += _check_base_city_jumps(plan)
    return _report(violations)


def validate_change_scope(
    old_plan: ItineraryPlan, new_plan: ItineraryPlan, *, from_day: int
) -> ValidationReport:
    """Iron rule 10: days strictly before from_day must be untouched."""
    old_days = {d.day: d for d in old_plan.days}
    new_days = {d.day: d for d in new_plan.days}
    violations = []
    for day_no in sorted(old_days):
        if day_no >= from_day:
            continue
        old_d = old_days[day_no]
        new_d = new_days.get(day_no)
        if (
            new_d is None
            or new_d.base_city != old_d.base_city
            or list(new_d.items) != list(old_d.items)
        ):
            violations.append(
                RuleViolation(
                    rule_id=10,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 早于 from_day={from_day} 却与原计划不一致"
                        "（铁律 10：只动当天及之后）",
                        f"Day {day_no} is before from_day={from_day} but differs "
                        "from the original plan (iron rule 10: only change the "
                        "current day onward)",
                    ),
                    item_ids=[i.item_id for i in old_d.items],
                    day=day_no,
                )
            )
    return _report(violations)


def validate_pinned(
    old_plan: ItineraryPlan, new_plan: ItineraryPlan
) -> ValidationReport:
    """Iron rule 19: pinned VisitItems must survive unmoved and unretimed."""
    new_by_id = {i.item_id: i for d in new_plan.days for i in d.items}
    violations = []
    for d in old_plan.days:
        for old in d.items:
            if not (isinstance(old, VisitItem) and old.pinned):
                continue
            new = new_by_id.get(old.item_id)
            if new is None:
                violations.append(
                    RuleViolation(
                        rule_id=19,
                        severity=RuleSeverity.error,
                        message=L(
                            f"第{d.day}天 {old.name} 已被用户确认（pinned）却被删除",
                            f"Day {d.day}: {old.name} was user-confirmed (pinned) "
                            "but got deleted",
                        ),
                        item_ids=[old.item_id],
                        day=d.day,
                    )
                )
            elif (
                new.day != old.day
                or new.start_time != old.start_time
                or new.end_time != old.end_time
            ):
                violations.append(
                    RuleViolation(
                        rule_id=19,
                        severity=RuleSeverity.error,
                        message=L(
                            f"第{d.day}天 {old.name} 已被用户确认（pinned）"
                            "却被移动或改时间",
                            f"Day {d.day}: {old.name} was user-confirmed (pinned) "
                            "but got moved or retimed",
                        ),
                        item_ids=[old.item_id],
                        day=d.day,
                    )
                )
    return _report(violations)
