"""F-15 duration tiers (Q1: typ = min(library, 240) for park/garden-type
big sites, always disclosed when clamped; min/max derive from typ)."""

from __future__ import annotations

from typing import Optional

DEFAULT_DURATION_MIN = 90
CLAMP_TARGET_MINUTES = 240
CLAMP_CATEGORIES = frozenset({"park", "garden", "nature", "scenic"})


def duration_tier(
    suggested: Optional[int], category: Optional[str]
) -> tuple[int, int, int, bool]:
    """(min, typ, max, clamped) — max keeps the library value."""
    lib = int(suggested) if suggested and suggested > 0 else DEFAULT_DURATION_MIN
    clamped = lib > CLAMP_TARGET_MINUTES and (category or "") in CLAMP_CATEGORIES
    typ = min(lib, CLAMP_TARGET_MINUTES) if clamped else lib
    low = max(30, typ // 2)
    return low, typ, lib, clamped
