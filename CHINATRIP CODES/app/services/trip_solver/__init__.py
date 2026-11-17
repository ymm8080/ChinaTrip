"""Trip-level solver (global CP-SAT) — side module.

Design refs (DESIGN/Global CP-SAT/):
  cpsat_design_functions_2026-11-17.md  §2 data contracts, F-20/F-24, F-35
  cpsat_implementation_phases_2026-11-17.md  P1-A (this skeleton)

Hard rule (audit M2): this package may import read-only pure helpers from
app.services.itinerary.* but NEVER app.services.agent.plan; and it performs
no DB / network I/O inside solve — everything comes from a FactSnapshot.
"""

__all__ = ["SNAPSHOT_SCHEMA_VERSION"]

SNAPSHOT_SCHEMA_VERSION = 1
