"""F-25 slack ladder -- disclosed relaxations, never a silent fallback.

Declared order (cumulative, ``LADDER_STEP_NAMES``): drop fill candidates
-> relax diversity caps -> relax soft time-of-day preferences -> relax
weather penalties -> relax remote-day exclusivity **only with
disclosure**.

Never relaxed, at any rung (``NEVER_RELAX``): open windows (C-01), entry
caps (C-02), user pins (C-04), timed access legs (C-08), and the
requested-coverage disclosure link (F-20). The last resort is
infeasibility with a certificate (F-26 in ``certificate.py``), never a
silently degraded plan.
"""

from __future__ import annotations

from dataclasses import dataclass

LADDER_STEP_NAMES: tuple[str, ...] = (
    "drop_fill",
    "relax_diversity",
    "relax_time_of_day",
    "relax_weather",
    "relax_remote_exclusive",
)

NEVER_RELAX: tuple[str, ...] = (
    "open windows (C-01)",
    "entry caps (C-02)",
    "user pins (C-04)",
    "timed access legs (C-08)",
    "requested-coverage disclosure link (F-20)",
)


@dataclass(frozen=True)
class SlackFlags:
    """Which ladder rungs are applied when (re)building the model."""

    drop_fill: bool = False
    relax_diversity: bool = False
    relax_time_of_day: bool = False
    relax_weather: bool = False
    relax_remote_exclusive: bool = False

    def level(self) -> int:
        """0 = nothing relaxed; else the cumulative rung index."""
        return sum(1 for name in LADDER_STEP_NAMES if getattr(self, name))


def ladder_levels() -> list[SlackFlags]:
    """Level 0 (nothing relaxed) plus one cumulative level per rung."""
    levels = [SlackFlags()]
    active: list[str] = []
    for step in LADDER_STEP_NAMES:
        active.append(step)
        levels.append(SlackFlags(**{name: True for name in active}))
    return levels


def slack_disclosures(flags: SlackFlags, lang: str = "zh") -> list[str]:
    """One bilingual template line per applied rung (F-25 log)."""
    from .certificate import render_reason

    return [
        render_reason(step, lang, family="slack_reasons")
        for step in LADDER_STEP_NAMES
        if getattr(flags, step)
    ]
