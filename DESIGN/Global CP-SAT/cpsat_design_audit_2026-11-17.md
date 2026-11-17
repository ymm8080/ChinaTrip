# Design Package Audit — gaps, staleness, updates needed

**Date**: 2026-11-17 (evening) · **Scope**: the six documents in `DESIGN/Global CP-SAT/` (ADR, AS-IS, design functions, feature parity, coverage audit, implementation phases) · **Method**: full re-read of the ADR + mechanical cross-reference scan of all six files + consistency check against the current code state and this week's decisions. **Per user instruction: no comments on agreed parts — only what is missing, stale, or needs updating.**

**Status: APPLIED 2026-11-17** — A1–A9 fixed in the respective files; M1–M15 incorporated (M1/M2/M4/M7 into design functions + phases, the rest with their owning packages); Q6/Q7 appended to open questions.

---

## A. Stale / inconsistent — mechanical updates, no new decisions needed

| # | File · location | Problem | Fix |
|---|---|---|---|
| **A1** | ADR · D1 硬约束 bullet | Says 「**16:00**/15:30 白天入场闸」 — the agreed cap was corrected to **16:30** (大点 15:30) by c93a712 (晚闸口径 v2). The D1 bullet predates the correction and was never updated. | Change to 「16:30/大点 15:30」 |
| **A2** | ADR · D3 设计包 bullet | Lists only 3 companion docs (AS-IS / design functions / parity) — the **coverage audit** and **implementation phases** docs were added later and are never mentioned in the ADR. | Add both to the package list |
| **A3** | ADR · D2 | No cross-reference to the implementation phases doc (packages P1-A…P4, dependency DAG, session budgets). P4 is mentioned only *inside* the P3 bullet, which reads as if P4 were part of P3. | Add one line: 「实施分包/依赖图/会话预算见 `cpsat_implementation_phases_2026-11-17.md`」; move the P4 clause out of the P3 item |
| **A4** | AS-IS · header Companions | Lists only ADR / parity / design functions — missing coverage audit + phases. | Add both |
| **A5** | Design functions · header Inputs | Same — missing phases doc reference. | Add |
| **A6** | Feature parity · P3 切流硬门槛 (5 steps) | Does **not** include the coverage-audit standing rule (「any engine function not in the audit blocks the switch」) — the rule exists only inside the audit appendix, not in the gate list that P3 is executed against. | Add step 6 + link `cpsat_coverage_audit_2026-11-17.md` |
| **A7** | Coverage audit · §Method | Says 「the **four** design documents」 — the package is now six; the phases doc postdates the audit and isn't known to it. | Reword to 「the design package (ADR/AS-IS/design functions/parity)」+ note the phases plan |
| **A8** | AS-IS · bug register | Statuses are anchored to commits up to b2f6597/2a56cda; parallel keeps landing fixes (B-16/B-17/B-18 may move). No 「as-of」 timestamp or refresh rule. | Add 「statuses as of origin `9ca19ba` 2026-11-17 PM; refresh before P3 gate」 |
| **A9** | Phases · P1-A | G-01 fixture is planned as `tests/golden/g01.json`, but the source payload (session 24379abd) **lives only in a workspace dump and contains `device_id` + `account_id` (email)** — committing it as-is leaks identifiers into the repo. | Add an explicit **sanitization step** to P1-A (strip device/account/session ids, keep musts/dates/plan shape) |
| **A10** | All docs · cross-refs after folder move | Verified OK (bare same-folder filenames) — **no action**, recorded here only to close the check. | — |

## B. Missing content — substantive gaps (each needs a small new section or a decision)

| # | What's missing | Why it matters | Where it belongs |
|---|---|---|---|
| **M1** | **Engine entry/adapter contract** — how the legacy/api layer invokes `trip_solver` (function signature, feature-flag name & config, sync/async + `to_thread` boundary, timeout behavior, `INFEASIBLE`-with-certificate path into the response, exception policy = fail loud in tests / fall back to legacy engine in production while flag is on) | 「P3 = one small entry diff」 is asserted but never specified; this is the single file the switch commit touches | Design functions — new **F-35 entry adapter** (Module E or G) |
| **M2** | **Module boundary rules** — allowed imports (itinerary pure functions incl. legs/solver helpers: read-only; **never** `agent/plan.py`), no DB/network I/O inside solve (snapshot only), package layout | Prevents the side module quietly growing tentacles back into the hot zone; P1 reviewers need the rule written down | Design functions §2 (one subsection) |
| **M3** | **Snapshot & fixture versioning** — `FactSnapshot.schema_version`, frozen anonymized golden fixtures committed to the repo, re-bless policy when the POI library evolves (fixture rot) | G-01 assertions must stay reproducible after library backfills change hours/durations | Phases P1-A/P1-B + design §2 |
| **M4** | **Performance envelope decomposition** — is snapshot build inside the 3 s budget? latency split (snapshot ≤ X ms / solve ≤ 3 s / assemble ≤ Y ms), model-size arithmetic from the Q2 cap ((requested + ≤6·days) × days variables), memory bound, worst-case certificate latency | 「3 s 预算不动」 currently ambiguous about what it covers; Q3's convergence proof needs the envelope defined | Design functions D3-perf + phases P1-E |
| **M5** | **Observability** — per-solve structured log/metrics (status, wall time, var/constraint counts, slack level used, unplaced count, fill count, hint used?) | Q3 is proven and P3 is monitored with data, not anecdotes; also the post-switch regression tripwire | Design functions — new **F-36 solve telemetry** |
| **M6** | **Shadow-mode operations** — where shadow runs (in-request extra `to_thread` vs offline batch), sample rate, double-compute cost ceiling, diff-report storage & retention, review cadence, flag config | P2-A is scoped as code but not as an *operating* mode | Phases P2-A |
| **M7** | **Golden assertion schema** — per-scenario strictness: exact times vs shape invariants (sequence, same-venue, entry-cap, coverage-before-fill, card≡leg, no-filler-before-remote); how E-1…E-4 prose becomes machine assertions | 「G-01 green」 is currently undefined at the assertion level; determinism guard (byte-identical) and shape assertions are different granularities | Phases P1-A |
| **M8** | **P3 rollback plan** — trigger metrics (error rate / convergence / audit-gate failures), who flips the flag, confirmation that plan/session schemas need no migration, procedure | 「保留级联开关一版」 says the switch exists, not when/how it gets pulled | Phases P3 |
| **M9** | **P2 relative-criteria thresholds** — numeric definitions: 「not-worse」 = plan-score Δ ≥ −ε (ε=?), violation classes = 0, convergence ≥ x %, corpus ≥ N scenarios | F-62 names the metrics but no pass thresholds; P2-B can't finish without them | Design functions F-62 |
| **M10** | **Constants migration table** — one appendix mapping current numeric constants into model parameters: entry caps (16:30 / 大点 15:30), day-load cap, rain penalties (240/60), must/wish/fill weights, Q2 fill cap | Q5 says 「keep numeric parity where possible」 but the numbers are scattered across solver/scoring/plan | Design functions appendix |
| **M11** | **Multi-city order policy** — is the city sequence an intent-layer input or a model decision? C-05/C-07 assume `city_days` given; ≥3-city trips with ordering freedom are unspecified | Either answer is fine; unstated is not | Design functions C-05 note — candidate **Q6** |
| **M12** | **Edit-channel latency budget (P4)** — target ms for re-solve on move/retime/duration; hint-effectiveness assumption; policy when re-solve exceeds budget mid-interaction | Edits are interactive; a full 3 s re-solve per drag would regress UX vs the current ripple ladder | Phases P4 — candidate **Q7** |
| **M13** | **Disclosure template ownership** — certificate reason-code → bilingual template table: who writes/maintains it, where it lives, tests for coverage of all codes | F-33 says templates exist; without an owner/table the first certificate will meet an unmapped code | Design functions F-33 |
| **M14** | **P1-B data prerequisites checklist** — hours-quality gate, access-profile coverage per remote POI, indoor/rain_ok completeness, duration-tier sources, each with acceptance | Adapters on bad data produce a confidently wrong plan (GIGO); the checklist makes 「input ready」 checkable | Phases P1-B |
| **M15** | **B-16 ownership** — form/preferences 「必去」 not binding is an intake bug in the *current* engine; no package owns its fix (design F-01 states the requirement, but nothing schedules the legacy fix or explicitly defers it to the new intent layer) | Otherwise it survives P3 by migration | AS-IS bug register + phases (explicit: hotfix now or defer-with-note) |

## C. Open questions to add

- **Q6 (new)**: multi-city trip — city order fixed by intent layer, or optimized by the model? *(recommend: intent layer input, model respects it — keeps model smaller)*
- **Q7 (new)**: edit re-solve latency budget and fallback *(recommend: ≤ 800 ms target with hint; if exceeded, keep current plan + disclose 「重排中」)*

## D. Recommended application order

1. **A1–A8, A9 sanitization note**: mechanical, apply immediately (one editing pass, no decisions).
2. **M1, M2, M4, M7**: must land **before P1-A/P1-E coding starts** (they define the entry contract, boundaries, envelope, assertion schema).
3. **M3, M5, M6, M8–M10, M13, M14**: land with their owning packages (P1-A/P1-B/P2-A/P3) — each is a short section, not a redesign.
4. **M11, M12 → Q6/Q7**: settle with Q1–Q5 at kickoff.
5. **M15**: decide hotfix-now vs defer when answering Q1–Q5 (one line either way).
