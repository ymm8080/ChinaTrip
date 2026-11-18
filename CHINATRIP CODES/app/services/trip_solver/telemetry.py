"""F-36 solve_telemetry — structured per-solve record (P3 wiring).

Emitted for every model-engine solve (serving, shadow sample, or fallback
attempt) so the F-62 convergence metric, the P2 diff report and the M8
rollback triggers all read the same shape. Fields landed by P1-E machinery
(``slack_level`` / ``n_vars`` / ``n_cons``) are emitted as ``None`` until
the slack ladder lands — honest blanks, never fakes.
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover
    from ..types import FactSnapshot, Solution

logger = logging.getLogger(__name__)

_solver_version: Optional[str] = None


def solver_version() -> str:
    """ortools package version (cached; the metadata lookup is not free)."""
    global _solver_version
    if _solver_version is None:
        try:
            from importlib.metadata import version

            _solver_version = str(version("ortools"))
        except Exception:  # pragma: no cover - metadata absent in odd envs
            _solver_version = "unknown"
    return _solver_version


def solve_telemetry(
    snapshot: "FactSnapshot",
    solution: Optional["Solution"],
    *,
    engine: str,
    hint_used: bool = False,
    fallback_reason: Optional[str] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    """One F-36 record. `solution=None` + `error` marks a failed solve."""
    from .snapshot import snapshot_hash

    fill_ids = {
        c.cid for c in snapshot.candidates if getattr(c, "kind", None) == "fill"
    }
    items = list(solution.items) if solution is not None else []
    return {
        "snapshot_hash": snapshot_hash(snapshot),
        "schema_version": snapshot.schema_version,
        "engine": engine,
        "status": solution.status if solution is not None else "ERROR",
        "wall_ms": solution.wall_ms if solution is not None else None,
        "unplaced_count": len(solution.unplaced) if solution is not None else None,
        "fill_count": sum(1 for it in items if it.cid in fill_ids),
        "hint_used": bool(hint_used or (solution is not None and solution.hint_used)),
        "slack_level": solution.slack_level if solution is not None else None,
        "n_vars": solution.n_vars if solution is not None else None,
        "n_cons": solution.n_cons if solution is not None else None,
        "solver_version": solver_version(),
        "fallback_reason": fallback_reason,
        "error": error,
        "emitted_at": datetime.datetime.now().isoformat(timespec="milliseconds"),
    }


def emit(record: dict[str, Any]) -> dict[str, Any]:
    """Log the record as one JSON line (structured sink of record is the
    caller's choice — the P2 report reads replayed corpus runs, not this)."""
    logger.info(
        "trip_solver.solve %s",
        json.dumps(record, ensure_ascii=False, sort_keys=True, default=str),
    )
    return record
