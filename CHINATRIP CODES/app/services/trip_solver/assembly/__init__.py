"""P1-F assembly: Solution -> ItineraryPlan (F-30..F-34).

Module boundary (audit M2): imports itinerary pure helpers + the model
solution only; never agent/plan. Serving-ready for the F-35 entry adapter
(``entry.serving_ready`` imports this package).
"""

from .chips import attach_alternatives
from .disclosures import render_disclosures
from .materialize import assemble, materialize_plan
from .meals import attach_meal_cards
from .sync import planned_row_projection, wish_row_projection

__all__ = [
    "assemble",
    "materialize_plan",
    "attach_meal_cards",
    "attach_alternatives",
    "render_disclosures",
    "wish_row_projection",
    "planned_row_projection",
]
