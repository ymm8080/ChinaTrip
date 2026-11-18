"""Shadow harness CLI (P2-A, offline batch — audit M6).

Usage (from the code root, i.e. the folder that contains `app/`):

    python -m app.services.trip_solver.shadow                 # corpus v1 → report
    python -m app.services.trip_solver.shadow --corpus tests/golden
    python -m app.services.trip_solver.shadow --out \
        "DESIGN/Global CP-SAT/shadow/manual-run"
    python -m app.services.trip_solver.shadow --replay-legacy
        # P2-B: regenerate missing legacy recordings first

Writes `report.json` (machine) + `report.md` (review) into the report dir
(default: <repo>/DESIGN/Global CP-SAT/shadow/<today>/, retained ≥ 8 weeks,
reviewed at every P2-B iteration). Exit codes: 0 report written, 2 corpus
load errors.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .compare import shadow_compare
from .corpus import default_corpus_dir, default_report_dir, load_corpus
from .metrics import acceptance_metrics


def build_report(corpus_dir: str | None = None, budget_s: float = 3.0) -> dict:
    import datetime

    scenarios = load_corpus(corpus_dir)
    if not scenarios:
        raise SystemExit("no scenarios found in %r" % corpus_dir)
    reports = [shadow_compare(s, budget_s=budget_s) for s in scenarios]
    metrics = acceptance_metrics(reports)
    return {
        "engine_note": "offline batch: legacy side = recorded runs "
        "(tests/golden/legacy/); model side = live double solve (F-41)",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "corpus_dir": corpus_dir or default_corpus_dir(),
        "budget_s": budget_s,
        "scenarios": reports,
        "acceptance": metrics,
    }


def render_markdown(report: dict) -> str:
    lines: list[str] = []
    acc = report["acceptance"]
    lines.append("# Shadow diff report — corpus (P2-B)")
    lines.append("")
    lines.append("_%s_" % report["engine_note"])
    lines.append("")
    lines.append(
        "generated %s · budget %.1fs · corpus dir `%s`"
        % (report["generated_at"], report["budget_s"], report["corpus_dir"])
    )
    lines.append("")
    if report.get("replay"):
        lines.append(
            "_legacy replay_: %s" % json.dumps(report["replay"], ensure_ascii=False)
        )
        lines.append("")
    lines.append("## F-62 acceptance gates")
    lines.append("")
    lines.append("| Gate | Value | Pass | Note |")
    lines.append("|---|---|---|---|")
    for name, gate in acc["gates"].items():
        lines.append(
            "| %s | %s | %s | %s |"
            % (
                name,
                gate.get("value"),
                {True: "✅", False: "❌", None: "⏳"}[gate.get("pass")],
                gate.get("note") or "",
            )
        )
    lines.append("")
    lines.append(
        "**Verdict**: %s — pass %d / fail %d / pending %d"
        % (
            acc["verdict"]["mode"],
            acc["verdict"]["gates_pass"],
            acc["verdict"]["gates_fail"],
            acc["verdict"]["gates_pending"],
        )
    )
    lines.append("")
    for scen in report["scenarios"]:
        lines.append("## %s" % scen["scenario"])
        lines.append("")
        new = scen["new"]
        conv = new.get("convergence") or {}
        lines.append(
            "- model: status=%s wall=%sms deterministic=%s (unplaced=%s, fill=%s)"
            % (
                new["status"],
                new["wall_ms"],
                new["deterministic"],
                conv.get("unplaced_count"),
                conv.get("fill_count"),
            )
        )
        lines.append("- model violations: %s" % _fmt_counts(new["violation_counts"]))
        if scen.get("legacy"):
            leg = scen["legacy"]
            lines.append(
                "- legacy (recorded): violations %s, 未收敛 disclosures %d"
                % (
                    _fmt_counts(leg["violation_counts"]),
                    leg["convergence"]["no_solution_disclosures"],
                )
            )
            lines.append("- not-worse: %s" % scen["not_worse"]["pass"])
        else:
            lines.append("- legacy: no recording committed (P2-B regenerates)")
        lines.append("")
        lines.append("| Assertion | Legacy | Model | Detail (model) |")
        lines.append("|---|---|---|---|")
        legacy_by_type = {
            r["type"]: r for r in (scen.get("legacy") or {}).get("assertions", ())
        }
        for r in new["assertions"]:
            leg = legacy_by_type.get(r["type"])
            mark = {"pass": "✅", "fail": "❌", "pending": "⏳", "skipped": "➖"}
            lines.append(
                "| %s | %s | %s | %s |"
                % (
                    r["type"],
                    mark.get(leg["status"], "—") if leg else "—",
                    mark.get(r["status"], "?"),
                    r["detail"],
                )
            )
        if new["violations"]:
            lines.append("")
            lines.append("**Model-side violations (P2-B burn-down):**")
            for v in new["violations"]:
                lines.append(
                    "- `%s` day %s: %s" % (v["bug"], v.get("day"), v["evidence"])
                )
        lines.append("")
    return "\n".join(lines) + "\n"


def _fmt_counts(counts: dict) -> str:
    parts = ["%s=%d" % (cls, n) for cls, n in counts.items()]
    return ", ".join(parts) if parts else "none"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="trip_solver shadow harness (P2-A)")
    parser.add_argument("--corpus", default=default_corpus_dir(), help="corpus dir")
    parser.add_argument(
        "--out",
        default=None,
        help="report output dir (M6 default under DESIGN/Global CP-SAT/shadow/)",
    )
    parser.add_argument(
        "--budget", type=float, default=3.0, help="solve budget seconds"
    )
    parser.add_argument(
        "--replay-legacy",
        action="store_true",
        help="regenerate missing legacy recordings via in-process cascade "
        "replay (P2-B) before building the report",
    )
    parser.add_argument(
        "--replay-force",
        action="store_true",
        help="overwrite existing in-process-replay recordings (hand "
        "recordings are never overwritten)",
    )
    args = parser.parse_args(argv)

    replay_summary = None
    if args.replay_legacy:
        from .replay import replay_corpus

        replay_summary = replay_corpus(args.corpus, force=args.replay_force)
        print("replay      :", replay_summary)

    report = build_report(args.corpus, budget_s=args.budget)
    if replay_summary is not None:
        report["replay"] = replay_summary
    out_dir = args.out or default_report_dir()
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "report.json")
    md_path = os.path.join(out_dir, "report.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(report))

    acc = report["acceptance"]
    print("report.json :", json_path)
    print("report.md   :", md_path)
    print(
        "scenarios   : %d | gates pass=%d fail=%d pending=%d"
        % (
            len(report["scenarios"]),
            acc["verdict"]["gates_pass"],
            acc["verdict"]["gates_fail"],
            acc["verdict"]["gates_pending"],
        )
    )
    print("new engine  : violations %s" % _fmt_counts(acc["new_violations_total"]))
    print("legacy      : violations %s" % _fmt_counts(acc["legacy_violations_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
