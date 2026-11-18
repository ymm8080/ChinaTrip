"""F-33 bilingual disclosure renderer (structured reasons only).

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


def render_disclosures(solution: "Solution", *, lang: str = "zh") -> list[str]:
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
    elif solution.items and solution.status in ("OPTIMAL", "FEASIBLE"):
        lines.append(COVERAGE_ALL[lang])
    return lines
