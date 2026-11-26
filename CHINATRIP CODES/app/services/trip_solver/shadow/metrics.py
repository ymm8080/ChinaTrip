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

# F-62 parity checklist — the 14 domains of cpsat_feature_parity_2026-11-17
# §1..§14. "covered" = the domain's semantics have their mapped home AND the
# implementation landed (evidence = the suite that pins it). Pending entries
# are switch blockers, not shadow blockers (P2-B reports them honestly).
PARITY_DOMAINS: tuple[tuple[str, str, str, str], ...] = (
    (
        "意图理解与请求绑定",
        "输入/模型外（F-01/F-02 留 legacy，snapshot 契约）",
        "covered",
        "test_trip_solver_p1a",
    ),
    (
        "选点与候选池",
        "输入 F-10 复用现行选点口径",
        "covered",
        "test_trip_solver_inputs",
    ),
    ("分天结构", "硬约束 C-05/C-06/C-07", "covered", "test_trip_solver_model_c2"),
    (
        "日内排时与入场闸",
        "硬约束 C-01..C-04 + C-08",
        "covered",
        "test_trip_solver_model_c1+c2",
    ),
    (
        "餐饮体系",
        "C-09/C-10 + F-31 装配",
        "covered",
        "test_trip_solver_model_d+assembly",
    ),
    (
        "交通与接驳",
        "C-03/C-08 + 输入 F-11/F-14",
        "covered",
        "test_trip_solver_inputs+model_c2",
    ),
    (
        "天气",
        "输入 F-13 + 条件目标 C-11/C-12",
        "covered",
        "test_trip_solver_model_d(rain)",
    ),
    ("地理与清退", "C-06/C-15/C-16", "covered", "test_trip_solver_model_c2+d"),
    (
        "空档补点/untimed 治理",
        "C-14 覆盖优先 + F-26 证书 + F-32 备选",
        "covered",
        "test_trip_solver_model_d+e+assembly",
    ),
    (
        "编辑与会话生命周期",
        "P4 F-50/F-51 edit.py（retime/pin=用户钉 C-04、move/duration/delete、"
        "hint 重解、Q7 800ms 超时保现计划+披露）",
        "covered",
        "test_trip_solver_edit",
    ),
    (
        "审计与披露",
        "模型外保留 F-40 + F-33 双语披露",
        "covered",
        "test_trip_solver_assembly(disclosures)",
    ),
    (
        "演出/夜游/晚档特则",
        "C-11 场次 + C-12 家庭/日载",
        "covered",
        "test_trip_solver_model_d(shows)",
    ),
    ("酒店/住宿/预订", "C-13 酒店锚", "covered", "test_trip_solver_model_d(hotel)"),
    (
        "运行时契约",
        "F-35/F-36/F-41（F-42 随 api 缝）",
        "covered",
        "test_trip_solver_entry+model_e",
    ),
)
CORPUS_TARGET = 12
CONVERGENCE_TARGET = 0.99
# R26: a host so slow that the wall cap fires for most scenarios cannot
# measure the engine at all — the gate must fail loudly instead of silently
# hiding behind the pollution exclusion.
POLLUTED_TARGET = 0.20


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

    # R26（满载抖动根治）：墙帽先于确定性时间触发（host_polluted）的跑次
    # =宿主太慢，不是引擎结论——分子分母同时剔除（墙帽但 within 仍 True
    # 的解也不得放大比率：value 必须 ≤ 1.0），并在门禁加污染率护栏
    # （>20% 视为宿主不可测，门禁照红，绝不借剔除掩盖回归）。
    def _conv_of(r):
        return r.get("new", {}).get("convergence") or {}

    host_polluted = sum(1 for r in corpus if _conv_of(r).get("host_polluted"))
    converged = sum(
        1
        for r in corpus
        if _conv_of(r).get("within_budget") and not _conv_of(r).get("host_polluted")
    )
    deterministic = sum(1 for r in corpus if r.get("new", {}).get("deterministic"))
    recorded = [r for r in corpus if r.get("legacy")]
    not_worse = [r for r in recorded if (r.get("not_worse") or {}).get("pass")]
    no_solution = sum(
        int(
            (r.get("legacy", {}) or {})
            .get("convergence", {})
            .get("no_solution_disclosures")
            or 0
        )
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

    scored = [
        r for r in corpus if (r.get("plan_score_delta") or {}).get("within") is not None
    ]
    scored_ok = [r for r in scored if r["plan_score_delta"]["within"]]
    parity_covered = [d for d in PARITY_DOMAINS if d[2] == "covered"]
    parity_pending = [d[0] for d in PARITY_DOMAINS if d[2] != "covered"]

    corpus_ok = len(corpus) >= CORPUS_TARGET
    measurable = max(0, len(corpus) - host_polluted)
    conv_rate = (converged / measurable) if measurable else 0.0
    polluted_rate = (host_polluted / len(corpus)) if corpus else 0.0
    det_rate = (deterministic / len(corpus)) if corpus else 0.0
    (len(not_worse) / len(recorded)) if recorded else None

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
            "pass": conv_rate >= CONVERGENCE_TARGET
            and polluted_rate <= POLLUTED_TARGET,
            "note": "host-polluted runs (wall cap before the deterministic "
            "budget) are excluded from the denominator: %d/%d; pollution "
            "guard %.0f%%" % (host_polluted, len(corpus), POLLUTED_TARGET * 100),
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
            "value": "%d/%d scored within −2%%" % (len(scored_ok), len(scored)),
            "pass": bool(scored) and len(scored_ok) == len(scored) if scored else None,
            "note": "one scorer both engines (Q5 constants): replay scores the "
            "cascade plan, F-30 materialises + scores the model plan; "
            "unscored sides stay pending",
        },
        "parity_domains_14": {
            "value": "%d/14" % len(parity_covered),
            "pass": len(parity_covered) == 14,
            "note": "parity registry in metrics.PARITY_DOMAINS; pending: %s "
            "(switch blocker, not a shadow blocker)" % ", ".join(parity_pending)
            if parity_pending
            else "all 14 domains covered",
        },
    }

    evaluated = [g for g in gates.values() if g["pass"] is not None]
    blocked = [g for g in gates.values() if g["pass"] is None]
    verdict = {
        "mode": "shadow-instrument+legacy-replay (P2-B)",
        "switch_ready": False,
        "reason": (
            "P3 switch requires: P4 edit domain (parity 13/14), "
            "plan-score density burn-down (model under-fills vs "
            "legacy), the api seam (with F-42) and the quiet window "
            "+ full suite; shadow stays zero-risk until then"
        ),
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
