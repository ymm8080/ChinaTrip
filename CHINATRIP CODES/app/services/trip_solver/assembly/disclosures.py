"""F-33 bilingual disclosure renderer (structured reasons only):
slack log + certificate + weather + coverage inputs.

Every line derives from certificate reason codes, slack rungs, or
coverage counts — 「求解器未收敛，时间已按顺序兜底排列」 is deleted by
construction (the model has no sequential fallback). ``lang`` selects
the template language; ``zh`` lines land on plan.assumptions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..model.certificate import render_reason
from ..model.slack import LADDER_STEP_NAMES

if TYPE_CHECKING:  # pragma: no cover
    from ..types import Solution

COVERAGE_ALL = {
    "zh": "必去景点已全部排入行程。",
    "en": "All must-see stops are scheduled.",
}
COVERAGE_SOME = {
    "zh": "有 {n} 个想去的点当天排不下，已列入「想去」并附原因。",
    "en": '{n} requested stop(s) did not fit; listed under "want" with reasons.',
}


WEATHER_LINE = {
    "zh": "第{day}天预报{cond}，当天户外点（{names}）已按雨天偏好安排。",
    "en": "Day {day} forecast {cond}; outdoor stops ({names}) scheduled "
    "under rain preferences.",
}
INDOOR_YES = {"yes", "true", "1", "indoor"}


def _weather_lines(solution: "Solution", snapshot, lang: str) -> list[str]:
    if not getattr(snapshot, "weather", None):
        return []
    cand_by_poi = {c.poi_id: c for c in snapshot.candidates if c.poi_id and c.rid}
    day_iso = {}
    from ..model.c01_c04 import day_date

    for day in range(1, snapshot.request.days + 1):
        dt = day_date(snapshot.request.start_date, day)
        if dt is not None:
            day_iso[dt.isoformat()] = day
    lines = []
    for poi_id, iso, cond in snapshot.weather:
        day = day_iso.get(iso)
        cand = cand_by_poi.get(poi_id)
        if not day or not cand or not cond:
            continue
        if str(cand.rain_ok or "").lower() in INDOOR_YES:
            continue
        seated = any(it.cid == cand.cid and it.day == day for it in solution.items)
        if not seated:
            continue
        lines.append(WEATHER_LINE[lang].format(day=day, cond=cond, names=cand.name))
    return lines


def render_disclosures(
    solution: "Solution", snapshot, *, lang: str = "zh"
) -> list[str]:
    lines: list[str] = []
    if solution.slack_level:
        for step in LADDER_STEP_NAMES[: solution.slack_level]:
            lines.append(render_reason(step, lang, family="slack_reasons"))
    if solution.unplaced:
        lines.append(COVERAGE_SOME[lang].format(n=len(solution.unplaced)))
        seen: set[str] = set()
        for entry in solution.unplaced:
            for code in entry.get("reason_codes", ()):
                if code in seen:
                    continue
                seen.add(code)
                lines.append(
                    render_reason(code, lang, name=str(entry.get("name") or ""))
                )
    lines.extend(_weather_lines(solution, snapshot, lang))
    if (
        not lines
        and solution.items
        and solution.status
        in (
            "OPTIMAL",
            "FEASIBLE",
        )
    ):
        lines.append(COVERAGE_ALL[lang])
    return lines
