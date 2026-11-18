"""F-62 acceptance metrics — aggregate over per-scenario diff reports.

Thresholds per audit M9 (informational until P1-F exists: the harness is
the measuring instrument; the P3 gate is evaluated when the corpus is ≥ 12
scenarios and the model has its full objective/assembly stack).

- corpus ≥ 12 scenarios incl. G-01 (M9) — corpus v1 ships 4, P2-B expands
- violation classes B-01/B-02/B-03a/B-03c/B-06 = 0 on the model engine
- convergence (OPTIMAL|FEASIBLE within budget) ≥ 99% of corpus runs
- 「求解器未收敛」 disclosures = 0
- determinism: byte-identical across 2 runs of every snapshot
- relative criterion: not-worse vs the legacy recording per scenario
  (plan-score Δ ≥ −2% becomes evaluable at P1-D/P1-F when the tiered
  objective + plan materialisation exist — reported as pending)
"""

from __future__ import annotations

from typing import Any, Iterable

TRACKED_CLASSES = ("B-01", "B-02", "B-03a", "B-03c", "B-06")
CORPUS_TARGET = 12
CONVERGENCE_TARGET = 0.99


def acceptance_metrics(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    reports = list(reports)
    corpus = [r for r in reports if r.get("scenario")]

    new_violations: dict[str, int] = {cls: 0 for cls in TRACKED_CLASSES}
    legacy_violations: dict[str, int] = {cls: 0 for cls in TRACKED_CLASSES}
    for r in corpus:
        for cls, n in (r.get("new", {}).get("violation_counts") or {}).items():
            new_violations[cls] = new_violations.get(cls, 0) + int(n)
        legacy_block = r.get("legacy") or {}
        for cls, n in (legacy_block.get("violation_counts") or {}).items():
            legacy_violations[cls] = legacy_violations.get(cls, 0) + int(n)

    converged = sum(
        1 for r in corpus if (r.get("new", {}).get("convergence") or {}).get("within_budget")
    )
    deterministic = sum(
        1 for r in corpus if r.get("new", {}).get("deterministic")
    )
    recorded = [r for r in corpus if r.get("legacy")]
    not_worse = [r for r in recorded if (r.get("not_worse") or {}).get("pass")]
    no_solution = sum(
        int((r.get("legacy", {}) or {}).get("convergence", {}).get("no_solution_disclosures") or 0)
        for r in recorded
    )

    replay_kinds: dict[str, int] = {}
    replay_det = 0
    replay_total = 0
    for r in recorded:
        kind = (r.get("legacy") or {}).get("kind") or "unknown"
        replay_kinds[kind] = replay_kinds.get(kind, 0) + 1
        det = (r.get("legacy") or {}).get("determinism")
        if det is not None:
            replay_total += 1
            if det:
                replay_det += 1

    corpus_ok = len(corpus) >= CORPUS_TARGET
    conv_rate = (converged / len(corpus)) if corpus else 0.0
    det_rate = (deterministic / len(corpus)) if corpus else 0.0
    nw_rate = (len(not_worse) / len(recorded)) if recorded else None

    gates = {
        "corpus_size": {
            "value": "%d/%d" % (len(corpus), CORPUS_TARGET),
            "pass": corpus_ok,
            "note": "corpus v2 ships 13 scenarios (P2-B families); M9 floor is 12",
        },
        "violation_classes_zero_new": {
            "value": new_violations,
            "pass": all(new_violations[cls] == 0 for cls in TRACKED_CLASSES),
        },
        "convergence_rate_new": {
            "value": round(conv_rate, 3),
            "threshold": CONVERGENCE_TARGET,
            "pass": conv_rate >= CONVERGENCE_TARGET,
        },
        "determinism_rate": {
            "value": round(det_rate, 3),
            "threshold": 1.0,
            "pass": det_rate == 1.0,
        },
        "not_worse_vs_recording": {
            "value": "%d/%d recorded scenarios" % (len(not_worse), len(recorded)),
            "pass": bool(recorded) and len(not_worse) == len(recorded),
        },
        "legacy_no_solution_disclosures": {
            "value": no_solution,
            "pass": no_solution == 0,
            "note": "recorded legacy baseline must itself be free of "
            "「求解器未收敛」 for a clean comparison",
        },
        "plan_score_delta": {
            "value": None,
            "pass": None,
            "note": "pending P1-D tiered objective + P1-F plan materialisation",
        },
        "parity_domains_14": {
            "value": None,
            "pass": None,
            "note": "pending P1-F feature-parity checklist",
        },
    }

    evaluated = [g for g in gates.values() if g["pass"] is not None]
    blocked = [g for g in gates.values() if g["pass"] is None]
    verdict = {
        "mode": "shadow-instrument+legacy-replay (P2-B)",
        "switch_ready": False,
        "reason": "P3 switch requires P1-D/E/F (objectives, slack ladder, "
        "assembly) + corpus ≥ 12 (P2-B) + quiet window; this report is the "
        "baseline measurement, not the gate decision.",
        "gates_pass": sum(1 for g in evaluated if g["pass"]),
        "gates_fail": sum(1 for g in evaluated if not g["pass"]),
        "gates_pending": len(blocked),
    }

    return {
        "corpus": [r.get("scenario") for r in corpus],
        "legacy_violations_total": legacy_violations,
        "new_violations_total": new_violations,
        "legacy_side": {
            "recorded": len(recorded),
            "kinds": replay_kinds,
            "replay_deterministic": "%d/%d" % (replay_det, replay_total)
            if replay_total
            else None,
            "note": "in-process replay recordings (P2-B) carry two-run "
            "calibration; hand recordings keep kind "
            "recorded-actual-output",
        },
        "gates": gates,
        "verdict": verdict,
    }
