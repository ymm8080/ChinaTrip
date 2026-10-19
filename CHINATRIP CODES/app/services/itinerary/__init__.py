"""Itinerary mutation pipeline domain service (design §6.0/§6.4, iron rule 0).

Public API: hard validators (rules.py) + diff applier / summarizer /
one-shot mutate pipeline (pipeline.py), all pure functions over the shared
domain models.
"""

from app.services.itinerary.models import (
    ChangeSummary,
    CrowdProfile,
    DayPlan,
    DiffOp,
    GeoPoint,
    ItineraryPlan,
    PoiHours,
    RuleSeverity,
    RuleViolation,
    TransferItem,
    ValidationReport,
    VisitItem,
)
from app.services.itinerary.pipeline import (
    PipelineError,
    apply_diffs,
    mutate,
    summarize_changes,
)
from app.services.itinerary.rules import (
    CROWD_COEFFICIENTS,
    haversine_km,
    validate_change_scope,
    validate_pinned,
    validate_plan,
)

__all__ = [
    "CROWD_COEFFICIENTS",
    "ChangeSummary",
    "CrowdProfile",
    "DayPlan",
    "DiffOp",
    "GeoPoint",
    "ItineraryPlan",
    "PipelineError",
    "PoiHours",
    "RuleSeverity",
    "RuleViolation",
    "TransferItem",
    "ValidationReport",
    "VisitItem",
    "apply_diffs",
    "haversine_km",
    "mutate",
    "summarize_changes",
    "validate_change_scope",
    "validate_pinned",
    "validate_plan",
]
