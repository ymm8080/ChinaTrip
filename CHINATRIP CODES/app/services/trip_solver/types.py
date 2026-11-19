"""Core data types for the trip-level solver (P1-A skeleton).

Kept dependency-free so every later package (model core, assembly, shadow)
can import it without pulling in OR-Tools or the legacy agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

SNAPSHOT_SCHEMA_VERSION = 2  # v2: solver-read meal/family/diversity/pin fields

RequestedKind = Literal["must", "wish"]
CandidateKind = Literal["requested", "fill"]


@dataclass(frozen=True)
class RequestedItem:
    """A user-requested item (must or wish). Carries the importance weight."""

    rid: str
    name: str
    poi_id: Optional[str] = None
    kind: RequestedKind = "must"
    importance: int = 3
    duration_tier: Optional[tuple[int, int, int]] = None  # (min, typ, max)
    day_hint: Optional[int] = None


@dataclass(frozen=True)
class CandidateItem:
    """A schedulable candidate. `kind=fill` items can never outrank requested ones."""

    cid: str
    name: str
    poi_id: Optional[str] = None
    kind: CandidateKind = "fill"
    rid: Optional[str] = None
    category: Optional[str] = None
    tier: Optional[int] = None
    quality: Optional[float] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    opening_hours: Optional[str] = None
    best_visit_time: Optional[str] = None
    indoor: Optional[str] = None
    rain_ok: Optional[str] = None
    suggested_duration_min: Optional[int] = None
    remote: bool = False
    city: Optional[str] = None  # C-07 city coherence (multi-city requests)
    diversity_group: Optional[str] = None  # C-16 optional-fill diversity cap
    family_id: Optional[str] = None  # C-12 explicit must-family binding
    meal_slot: Optional[str] = None  # C-09 real restaurant → lunch/dinner card
    # R12-D 菜系键（同菜系不重样罚项用；None=识别不出/非餐馆）
    cuisine: Optional[str] = None
    same_venue: Optional[str] = None  # C-09 nested host cid or poi_id


@dataclass(frozen=True)
class AccessProfile:
    """Shuttle / access-service interval template (F-14)."""

    gateway: str
    to_poi: str
    ride_minutes: int
    wait_minutes: int = 0
    last_mile_minutes: int = 0
    departures: tuple[str, ...] = ()
    returns: tuple[str, ...] = ()
    taxi_minutes: int = 0
    fare_text: Optional[str] = None
    operator: Optional[str] = None


@dataclass(frozen=True)
class TravelLeg:
    """One measured or estimated arc between two keys (poi_id or name)."""

    from_key: str
    to_key: str
    minutes: int
    mode: str = "taxi"
    source: str = "estimate"


@dataclass(frozen=True)
class FixedPin:
    """C-04: an immovable placement (iron rule 19)."""

    rid: str
    day: int
    start_min: int
    cid: str = ""  # optional direct candidate binding


@dataclass(frozen=True)
class TripRequest:
    days: int
    cities: tuple[str, ...]
    start_date: Optional[str] = None
    musts: tuple[RequestedItem, ...] = ()
    wishes: tuple[RequestedItem, ...] = ()
    avoid: tuple[str, ...] = ()
    arrival_time: Optional[str] = None
    departure_time: Optional[str] = None
    # 交通模式（2026-11-18 跨管线对齐+拍板「火车 2h/飞机 2.5h」）：
    # 落地/离城缓冲按模式取 120/150，缺省 150
    arrival_mode: Optional[str] = None
    departure_mode: Optional[str] = None
    day1_start: Optional[str] = None
    lang: str = "zh"
    # R8（2026-11-18 拍板「偏好重排也要换 CP-SAT」）：偏好文本随快照入
    # 模型——池排序 boost + tier② 偏好奖励，解析与 legacy
    # _preference_tokens/_pref_category_hit 同源
    preferences: str = ""
    # R9-2（2026-11-19 拍板「复杂开局也走 CP-SAT」收尾）：中途转移日
    # ——到达/离开落在第 N 天（None=首/末日，S1 前的默认端点形状）。
    # C-05 地板/顶盖挪到该日；天窗外仍全天窗（legacy 撤腿重排同语义
    # ——日是行程日，不因到达晚而清空）
    arrival_day: Optional[int] = None
    departure_day: Optional[int] = None
    pins: tuple["FixedPin", ...] = ()  # C-04 fixed placements
    hotel_anchors: bool = True  # C-13 morning departure + night return
    day_load_budget_min: int = 570  # legacy _MUST_DAY_USABLE_MIN
    sight_cap_per_day: int = 4  # legacy _cap_sights_per_day
    fill_cap_per_day: int = 6  # Q2 fill-pool cap
    # R8-S2（2026-11-18 拍板「全量切引擎」口径 A）：H5 分城停留
    # 天数——C-17 legacy 拆窗镜像（城市块连续+请求序，末位吃满）
    city_days: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class FactSnapshot:
    """Immutable solver input (determinism key)."""

    schema_version: int
    request: TripRequest
    candidates: tuple[CandidateItem, ...]
    access_profiles: tuple[AccessProfile, ...] = ()
    travel: tuple[TravelLeg, ...] = ()
    weather: tuple[tuple[str, str, str], ...] = ()  # (poi_id, day_iso, condition)
    library_version: str = "fixture"
    source: str = "fixture"


@dataclass
class SolutionItem:
    """A placed item in the solution (minutes since midnight)."""

    cid: str
    day: int
    start_min: int
    end_min: int
    kind: str = "visit"
    pinned: bool = False
    source: str = "model"


@dataclass
class Solution:
    """Solver output. INFEASIBLE always carries a certificate, never a fallback."""

    status: str  # OPTIMAL | FEASIBLE | UNKNOWN | INFEASIBLE
    items: list[SolutionItem] = field(default_factory=list)
    unplaced: list[dict] = field(default_factory=list)
    disclosures: list[str] = field(default_factory=list)
    slack_level: int = 0  # F-25: cumulative ladder rung applied
    certificate: list[dict] = field(
        default_factory=list
    )  # F-26: {code,rid,name,detail,evidence}
    wall_ms: Optional[int] = None
    access_legs: list[dict] = field(default_factory=list)  # C-08 intervals
    meal_anchors: list[dict] = field(default_factory=list)  # C-09/F-22
    hotel_anchors: list[dict] = field(default_factory=list)  # C-13
    objective_values: dict[str, int] = field(default_factory=dict)  # F-23
    hint_used: bool = False  # F-24: previous solution seeded the search
    n_vars: Optional[int] = None  # F-36 telemetry
    n_cons: Optional[int] = None  # F-36 telemetry


def validate_snapshot(snapshot: FactSnapshot) -> list[str]:
    """Structural validation; returns a list of human-readable errors (empty = ok)."""
    errors: list[str] = []

    if snapshot.schema_version != SNAPSHOT_SCHEMA_VERSION:
        errors.append(
            "schema_version %r != %r"
            % (snapshot.schema_version, SNAPSHOT_SCHEMA_VERSION)
        )
    if snapshot.request.days < 1:
        errors.append("request.days must be >= 1")
    if not snapshot.request.cities:
        errors.append("request.cities is empty")

    seen_cids: set[str] = set()
    rid_by_poi: dict[str, str] = {}
    for req in snapshot.request.musts + snapshot.request.wishes:
        if req.poi_id:
            rid_by_poi[req.poi_id] = req.rid
    for cand in snapshot.candidates:
        if cand.cid in seen_cids:
            errors.append("duplicate cid %r" % cand.cid)
        seen_cids.add(cand.cid)
        if cand.kind == "requested" and not cand.rid:
            errors.append("requested candidate %r has no rid" % cand.cid)
        if cand.lon is not None and not (-180.0 <= cand.lon <= 180.0):
            errors.append("candidate %r lon out of range" % cand.cid)
        if cand.lat is not None and not (-90.0 <= cand.lat <= 90.0):
            errors.append("candidate %r lat out of range" % cand.cid)

    covered = {c.rid for c in snapshot.candidates if c.kind == "requested" and c.rid}
    for req in snapshot.request.musts:
        if req.rid not in covered:
            errors.append(
                "must %r (%s) has no requested candidate" % (req.rid, req.name)
            )

    for prof in snapshot.access_profiles:
        if prof.ride_minutes <= 0:
            errors.append("access profile %r has non-positive ride time" % prof.gateway)

    return errors
