"""CLI for the trip-level solver skeleton (P1-A).

Usage (from the code root, i.e. the folder that contains `app/`):

    python -m app.services.trip_solver.cli --snapshot tests/golden/g01.json
    python -m app.services.trip_solver.cli            # defaults to the G-01 fixture
    python -m app.services.trip_solver.cli --json     # machine-readable summary

Prints the request summary, candidate counts and any snapshot validation
errors. Exit codes: 0 ok, 2 validation errors.
"""

from __future__ import annotations

import argparse
import json
import sys

from .snapshot import default_golden_path, load_golden, snapshot_hash
from .types import validate_snapshot


def build_summary(path: str) -> tuple[dict, list[str]]:
    snapshot, expect, provenance = load_golden(path)
    errors = validate_snapshot(snapshot)
    musts = [r.name for r in snapshot.request.musts]
    requested = [c for c in snapshot.candidates if c.kind == "requested"]
    fill = [c for c in snapshot.candidates if c.kind == "fill"]
    summary = {
        "snapshot": path,
        "hash": snapshot_hash(snapshot),
        "schema_version": snapshot.schema_version,
        "source": snapshot.source,
        "library_version": snapshot.library_version,
        "request": {
            "days": snapshot.request.days,
            "cities": list(snapshot.request.cities),
            "start_date": snapshot.request.start_date,
            "musts": musts,
        },
        "candidates": {"requested": len(requested), "fill": len(fill)},
        "access_profiles": [
            {"gateway": a.gateway, "to_poi": a.to_poi, "departures": list(a.departures)}
            for a in snapshot.access_profiles
        ],
        "travel_legs": len(snapshot.travel),
        "expect_assertions": len(expect),
        "provenance": provenance,
        "errors": errors,
    }
    return summary, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="trip-level solver skeleton (P1-A)")
    parser.add_argument(
        "--snapshot", default=default_golden_path(), help="path to a snapshot JSON"
    )
    parser.add_argument("--json", action="store_true", help="print JSON summary")
    args = parser.parse_args(argv)

    summary, errors = build_summary(args.snapshot)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("snapshot      :", summary["snapshot"])
        print("hash          :", summary["hash"][:16])
        print("schema        :", summary["schema_version"])
        print(
            "days / cities :",
            summary["request"]["days"],
            "|",
            ",".join(summary["request"]["cities"]),
        )
        print("musts         :", ", ".join(summary["request"]["musts"]))
        print(
            "candidates    : requested=%d fill=%d"
            % (summary["candidates"]["requested"], summary["candidates"]["fill"])
        )
        print(
            "access legs   :",
            len(summary["access_profiles"]),
            "| travel legs:",
            summary["travel_legs"],
        )
        print("assertions    :", summary["expect_assertions"])
        if errors:
            print("VALIDATION ERRORS:")
            for err in errors:
                print("  -", err)
        else:
            print("validation    : ok")
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
