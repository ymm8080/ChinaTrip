"""F-03 enrichment + M14 readiness report.

EnrichedSnapshot = base FactSnapshot + per-candidate derived inputs:
entry caps (F-12), duration tiers (F-15), travel matrix (F-11), weather
conditions (F-13), access intervals (F-14). Pure — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .duration import duration_tier
from .hours_caps import entry_cap_minutes, parse_first_window
from .travel import build_matrix
from .weather import weather_conditions


@dataclass
class EnrichedSnapshot:
    snapshot: object
    caps: dict[str, tuple[int | None, str]]
    windows: dict[str, tuple[int, int] | None]
    tiers: dict[str, tuple[int, int, int, bool]]
    matrix: dict[tuple[str, str], int]
    matrix_coverage: dict
    weather: dict[tuple[str, str], dict]
    access_by_poi: dict[str, object]
    readiness: dict
    # R12-H25（2026-11-20 用户令「天安门取真实的升旗时间 FIX」）：
    # day → 升旗分钟（flag_schedule 批次库，live 侧查好传入；空=回
    # 落静态 06:30 晨锁带）。
    flag_times: dict = None

    def cap(self, cid: str) -> int | None:
        return self.caps.get(cid, (None, "unknown"))[0]


def _access_profile_rank(p) -> tuple:
    """同 POI 多行择优序（越大越优）。

    R20⑤（2026-11-23）：核心是**有返程班次最优先**——回程卡 / 回城三段 /
    班次 chips 都读 returns；此前盲目后写覆盖，若「只有去程」的行排在
    「去程+返程」的行之后，会把返程班次盖掉。其次按班次数（更接近真实
    排班）、车程有效排序，保证与 DB 返回顺序无关的确定性。
    """
    return (
        bool(p.returns),
        len(p.returns),
        len(p.departures),
        p.ride_minutes > 0,
        p.last_mile_minutes,
    )


def _better_access_profile(a, b):
    """同 to_poi 两行择一（R20⑤）。

    - 同一服务被拆两行（乘车点 gateway 与车程一致）：合并班次——去程/返程
      取并集排序，显示字段取信息更全者；同乘车点/同车程下拼接无口径冲突。
    - 不同服务（gateway/ride 不同）：按 _access_profile_rank 择优，**绝不**
      跨服务拼接口径（去程 A 的乘车点 + 返程 B 的时刻＝不可执行的组合）。
    """
    if (
        a.gateway == b.gateway
        and a.ride_minutes == b.ride_minutes
        and a.ride_minutes > 0
    ):
        merged_departures = tuple(sorted(set(a.departures) | set(b.departures)))
        merged_returns = tuple(sorted(set(a.returns) | set(b.returns)))
        richer = a if _access_profile_rank(a) >= _access_profile_rank(b) else b
        return replace(
            richer,
            departures=merged_departures or richer.departures,
            returns=merged_returns or richer.returns,
        )
    return a if _access_profile_rank(a) >= _access_profile_rank(b) else b


def enrich(
    snapshot,
    weather_days: tuple[tuple[str, str, str], ...] = (),
    flag_times: dict | None = None,
) -> EnrichedSnapshot:
    from .access import total_one_way_minutes as _tw  # noqa: F401 (re-exported)

    if flag_times is None:
        # R18（2026-11-22 用户令「不可能没有升旗时间」）：未显式给值即取
        # flag_schedule 真值。此前只有 entry 缝传（模型侧 C-01 升旗等式
        # 依赖它），而 enrich(snapshot) 的直接调用方一律退化成静态 06:30
        # 下界，装配期再补锚就会和已排好的后继卡打架。查表失败/无出发
        # 日期返回空 → 行为与旧口径完全一致（回落静态晨锁带）。
        try:
            from ...flag_schedule import flag_minutes_by_day

            flag_times = flag_minutes_by_day(
                getattr(snapshot.request, "start_date", None),
                getattr(snapshot.request, "days", 0),
            )
        except Exception:  # noqa: BLE001 - 纯查表增强，失败退兜底
            flag_times = {}

    caps: dict[str, tuple[int | None, str]] = {}
    windows: dict[str, tuple[int, int] | None] = {}
    tiers: dict[str, tuple[int, int, int, bool]] = {}
    keys: list[str] = []
    pinned_cids = {
        cand.cid
        for pin in (getattr(snapshot.request, "pins", ()) or ())
        for cand in snapshot.candidates
        if pin.rid == cand.rid or (pin.cid and pin.cid == cand.cid)
    }

    for cand in snapshot.candidates:
        key = cand.poi_id or cand.cid
        keys.append(key)
        window = parse_first_window(cand.opening_hours)
        windows[cand.cid] = window
        cap, reason = entry_cap_minutes(
            name=cand.name,
            category=cand.category,
            best_visit_time=cand.best_visit_time,
            opening_hours_text=cand.opening_hours,
            duration_min=cand.suggested_duration_min,
            tier=cand.tier,
            pinned_with_time=cand.cid in pinned_cids,
        )
        caps[cand.cid] = (cap, reason)
        tiers[cand.cid] = duration_tier(cand.suggested_duration_min, cand.category)

    class _Keyed:
        """Read-only view exposing .key/.lon/.lat for the matrix builder."""

        def __init__(self, cand, key):
            self.cid = cand.cid
            self.key = key
            self.lon = cand.lon
            self.lat = cand.lat

    keyed = []
    key_by_cid = {}
    for cand, key in zip(snapshot.candidates, keys):
        keyed.append(_Keyed(cand, key))
        key_by_cid[cand.cid] = key

    class _Leg:
        def __init__(self, leg):
            self.from_key = leg.from_key
            self.to_key = leg.to_key
            self.minutes = leg.minutes
            self.mode = leg.mode

    matrix, coverage = build_matrix(keyed, [_Leg(t) for t in snapshot.travel])

    # R20⑤（2026-11-23）：同 POI 多行不再盲目后写覆盖——顺带修正「有返程
    # 的行被无返程的行盖掉 → 回程卡/回城三段丢失」的 DB 返回顺序依赖。
    access_by_poi: dict[str, object] = {}
    for prof in snapshot.access_profiles:
        prev = access_by_poi.get(prof.to_poi)
        access_by_poi[prof.to_poi] = (
            prof if prev is None else _better_access_profile(prev, prof)
        )

    weather_all = tuple(weather_days) or snapshot.weather
    weather = weather_conditions(weather_all, snapshot.candidates)

    readiness = readiness_report(
        snapshot=snapshot,
        windows=windows,
        access_by_poi=access_by_poi,
        tiers=tiers,
        coverage=coverage,
    )

    return EnrichedSnapshot(
        snapshot=snapshot,
        caps=caps,
        windows=windows,
        tiers=tiers,
        matrix=matrix,
        matrix_coverage=coverage,
        weather=weather,
        access_by_poi=access_by_poi,
        readiness=readiness,
        flag_times=dict(flag_times or {}),
    )


def readiness_report(*, snapshot, windows, access_by_poi, tiers, coverage) -> dict:
    """M14 data-readiness gates. Values are computed honestly; a gate can
    fail on a sparse fixture (G-01 is known-sparse for indoor/rain_ok)."""
    total = len(snapshot.candidates)
    hours_ok = sum(1 for w in windows.values() if w is not None)
    remote_no_access = [
        c.cid
        for c in snapshot.candidates
        if getattr(c, "remote", False) and (c.poi_id or c.cid) not in access_by_poi
    ]
    indoor_ok = sum(
        1 for c in snapshot.candidates if c.indoor is not None or c.rain_ok is not None
    )
    tier_ok = sum(1 for t in tiers.values() if t is not None)

    gates = {
        "hours_parse": {
            "value": round(hours_ok / max(1, total), 3),
            "threshold": 0.99,
            "pass": total > 0 and hours_ok == total or hours_ok / max(1, total) >= 0.99,
        },
        "remote_access_coverage": {
            "value": f"{len(remote_no_access)} missing",
            "threshold": "0 missing",
            "pass": not remote_no_access,
            "missing": remote_no_access,
        },
        "indoor_rain_ok": {
            "value": round(indoor_ok / max(1, total), 3),
            "threshold": 0.95,
            "pass": total > 0 and indoor_ok / max(1, total) >= 0.95,
        },
        "duration_tier": {
            "value": round(tier_ok / max(1, total), 3),
            "threshold": 1.0,
            "pass": tier_ok == total,
        },
        "matrix_coverage": {
            "value": coverage.get("coverage_pct"),
            "threshold": 100.0,
            "pass": not coverage.get("uncovered"),
        },
    }
    return {
        "gates": gates,
        "all_pass": all(g["pass"] for g in gates.values()),
        "note": "G-01 fixture is known-sparse on indoor/rain_ok (backfill is "
        "a data task, audit M5/M14); sparse fixtures are accepted for "
        "skeleton tests, real-store snapshots must pass all gates.",
    }
