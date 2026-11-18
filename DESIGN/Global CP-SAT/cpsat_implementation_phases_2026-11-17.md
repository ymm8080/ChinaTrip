# Global CP-SAT — Implementation Phases, Complexity & Session Budgets

**Date**: 2026-11-17 · **Status**: plan only (design-first; no implementation yet) · **Why this document**: the build must fit **token-limited working sessions** — each package is sized to be started, finished, tested and committed in **one session**, with no session ever beginning mid-package. **Inputs**: `cpsat_design_functions_2026-11-17.md` (F-01…F-62, C-01…C-16), `cpsat_as_is_2026-11-17.md`, `cpsat_coverage_audit_2026-11-17.md`, `cpsat_feature_parity_2026-11-17.md`.

---

## 1. How big is it, honestly

| Aspect | Estimate |
|---|---|
| New code (side module `trip_solver/`, no edits to `agent/plan.py` until P3) | **≈ 3,500–5,000 LOC** including tests |
| Share that is genuinely new logic | ~40 % model core + ~20 % assembly + ~15 % shadow harness |
| Share that is **reuse via thin read-only adapters** over existing pure functions (intent parsing, ~30 dedupe rules, hours/access/fare math, weather attrs) | ~25 % — this is what keeps the build small |
| Working sessions needed (token-limited) | **P1: 6–8 · P2: 2–4 · P3+P4: 1–2 ⇒ ≈ 9–14 sessions total** |
| Biggest risks | ① constraint fidelity for travel arcs/sequence (C-03), ② 3 s convergence at trip level (Q3), ③ semantic edge cases (remote lunch F-22, endpoint days C-05) |
| What this is **not** | not a rewrite of the 35 k-line `plan.py`; not a big-bang cutover; the current engine stays live and untouched through P1/P2 |

So: **a real build, but additive and de-risked** — and smaller than it looks, because most existing rule semantics are *reused*, not rewritten.

## 2. Complexity legend and session sizing rule

- **S (simple)**: scaffolding/plumbing, mostly deterministic code, ≤ ~300 LOC. → 0.5–1 session.
- **M (medium)**: 300–700 LOC or several edge cases, but well-understood semantics. → 1 session.
- **X (sophisticated)**: CP-SAT modelling correctness, subtle semantics, or convergence risk. → 1.5–2 sessions, **split into sub-packages** so no session exceeds its budget.

**Session sizing rule**: one package = one session = one commit. A package is done when its acceptance checks pass; anything unfinished is split, never carried over as a half-state.

## 3. Phase plan (per-package: scope, complexity, budget, acceptance)

| Pkg | Scope (design functions) | New files | Cmplx | Sessions | Acceptance |
|---|---|---|---|---|---|
| **P1-A** | Skeleton + golden harness: `TripRequest/FactSnapshot/Solution` types, snapshot loader, **G-01 fixture** from incident 24379abd (payload already dumped), CLI runner printing old-vs-new diff | `trip_solver/{types,snapshot,cli}.py`, `tests/golden/g01.json` | **S** | 0.5–1 | fixture loads; CLI runs; G-01 expected shapes E-1…E-4 encoded as assertions (initially failing = red target) |
| **P1-B** | Input adapters: F-03 snapshot, F-10 pool (reuse dedupe/eligibility), F-11 travel matrix, F-12 hours+entry caps, F-13 weather, F-14 access intervals, F-15 duration tiers (needs **Q1**) | `trip_solver/inputs/*.py` | **M** | 1 | adapter unit tests; snapshot for G-01 contains every candidate with hours/caps/legs/weather; no solver yet |
| **P1-C1** | Model core part 1: F-20 variables + `unplaced_var` link + C-01 hours, C-02 entry caps, C-03 NoOverlap+travel arcs, C-04 pins/fixed sessions | `trip_solver/model/{vars,c01_c04}.py` | **X** | 1 | tiny synthetic days solve; untimed-requested = type error proven; pins immovable |
| **P1-C2** | Model core part 2: C-05 endpoint days, C-06 remote exclusivity, C-07 city/side coherence, C-08 access legs as intervals | `trip_solver/model/c05_c08.py` | **X** | 1 | G-01 D1 legality: direct departure after 天安门; card≡leg times; remote day has no city filler |
| **P1-D** | C-09 meal anchors, C-10 lunch-before-visit, C-11 shows, C-12 family/day, C-13 hotel anchors, **C-14 coverage-before-fill**, **C-15 remote-departure ban**, C-16 diversity caps + F-22 remote lunch + F-23 lexicographic objectives | `trip_solver/model/c09_c16.py`, `objectives.py` | **X** | 1–1.5 | G-01 D2: 梵高-type filler can never outrank 颐和园; remote lunch nests at site or post-visit (needs **Q4**) |
| **P1-E** | F-24 budgeted solve (workers=1, fixed seed, hints), F-25 slack ladder, F-26 infeasibility certificates, F-41 determinism guard | `trip_solver/{solve,slack,certificate}.py` | **M–X** | 1 | same snapshot → byte-identical plan; infeasible case returns named rule set, never a sequential fallback |
| **P1-F** | Assembly F-30 plan materialisation, F-31 meal anchors, F-32 chips, F-33 bilingual disclosures, F-34 trip-center sync + **G-01 golden pass end-to-end** | `trip_solver/assembly/*.py` | **M** | 1 | **G-01 green**: 颐和园 timed or disclosed-unplaced, no unrequested filler before musts, lunch at 慕田峪 site, card≡leg; P0 gates vacuously green |
| **P2-A** | Shadow harness F-60/F-61: run old cascade and new model on the same snapshot, diff report (relative criteria), convergence metrics F-62 | `trip_solver/shadow/*.py` | **M** | 1 | diff report on corpus v1 (G-01 + this week's fixed incidents) — **✅ 2026-11-18**: harness (`shadow/{views,asserts,violations,corpus,compare,metrics}` + CLI), corpus v1 = g01 + g02 tower-late-gate/g03 third-cluster/g04 endpoint-transit + G-01 recorded baseline (`tests/golden/legacy/`), first report in `shadow/2026-11-18/` (model 0 violations, legacy baseline detects B-01×1/B-02×2/B-03a×1/B-03c×1); legacy side = recorded runs (M6 offline batch); in-process cascade replay + determinism calibration deferred to P2-B corpus regeneration |
| **P2-B** | Corpus expansion + gap burn-down: scenario families (remote days, endpoint days, rain, towers, reopen, typo…) each as JSON + expected shapes; every gap becomes a scenario **before** fixing | `tests/golden/*.json`, report iterations | **X** | 1–3 | all corpus scenarios not-worse-than-legacy + bug classes eliminated + convergence within budget (**Q3** proven) — **P2-B1 ✅ 2026-11-18**: corpus 4→13（g05 rain / g06 reopen-pins / g07 name-variant / g08 remote-exclusive / g09 duration-clamp(Q1) / g10 multi-city(C-07) / g11 trip-scale(Q3) / g12 closed-weekday(C-01) / g13 content-twin，`build_corpus_v2.py` 可再生）；进程内级联回放 落地（`shadow/replay.py`：快照桩库+BoomLLM 哨兵+天气双窗映射，M6 离线批）→ 12 份 legacy 记录再生（g01 手录不覆盖）+ 双跑确定性校准 12/12；新断言 remote_day_purity / span_cap / city_coherence；报告 `shadow/2026-11-18/p2b-corpus-v2/`：gates 6过/0败/2挂——corpus 13/12 ✅、收敛率 1.0（g11 全趟规模 270ms ≪ 3s，Q3 语料级实证）、确定性 1.0、not-worse 13/13、B 类新引擎全 0、legacy 未收敛披露 0（plan-score Δ 与 14 域 parity 仍挂 P1-D/F）。烧录续档：g04 端点日回放违例（day_start_floor/day_end_ceiling ❌）、g06 钉回放缺位（v1 不回放 pin，断言诚实失败）、g09 回放侧 span>240 —— 全部随 P1-D/E/F 落地逐轮迭代报告 |
| **P3** | Flag-gated switch: one small entry diff + rollback switch; P0 gates as acceptance; quiet-window precondition | `api/plan.py` (few lines) | **S (code) / gated** | 0.5–1 | contract/audit suites green; 「求解器未收敛」 disclosures = 0; rollback verified |
| **P4** | Edit re-solve with hints F-50/F-51 (move/retime/duration/delete/pin) | `trip_solver/edit.py` | **M** | 1 | edit scenarios re-solve deterministically; reopen preserve-pinned green |

## 4. Dependency graph (DAG)

Legend: **T** = type/code dependency (will not compile or run without it) · **D** = data dependency (needs the real snapshot; synthetic fixtures are used until then, so it never blocks writing code) · **A** = acceptance dependency (only meaningful once the other exists) · **X** = external precondition.

**Global preconditions for every package**: design package complete (done) + **Q1–Q7 settled** (X).

```
P1-A ──T──> P1-B ────────────────D──────────────┐
  │T                                          │
  ├─T──> P1-C1 ──T──> P1-C2 ──T──> P1-D ──T──> P1-E ─┐
  │T             (soft D on P1-B: F-14/F-11)           │T
  ├─T──> P2-A (shadow harness)                          │
  │                                                     ▼
  └──────────────────────────────► P1-F (assembly + G-01 green)
                                        │A                     ▲
                                        ▼                     │
                                       P2-B ──A──> P3 (+X quiet window)
P4 (edit re-solve) ──T── needs P1-E; data from P1-F; runs parallel with P2-B
```

| Package | Hard depends (T) | Soft / data (D) | Acceptance (A) | Can run in parallel with | Why |
|---|---|---|---|---|---|
| P1-A | — (Q1–Q5 X) | — | — | — | produces the types + G-01 fixture every package uses |
| P1-B | P1-A | — | — | C1 / C2 / D / E, P2-A | adapters need only the types + loader; independent of the model |
| P1-C1 | P1-A | synthetic matrix/hours until B lands | — | B, P2-A | model builder + variables + C-01…C-04 |
| P1-C2 | P1-C1 | P1-B (F-14 access templates, F-11 matrix) | — | B, P2-A | extends the same model; access legs need templates (synthetic OK at first) |
| P1-D | P1-C2 | P1-B (F-13 weather penalties) | — | B, P2-A | adds C-09…C-16 + F-22 remote lunch + objectives |
| P1-E | P1-D | — | — | B | slack-ladder ordering spans the full constraint set |
| P1-F | P1-C2, P1-D, P1-E | P1-B (real G-01 snapshot) | — | P2-A | end-to-end assembly + first golden pass |
| P2-A | P1-A | — | useful reports after P1-F | B / C1 / C2 / D / E | harness compares legacy vs new through the CLI stub; can calibrate legacy determinism early |
| P2-B | — | P1-F | P2-A + P1-F | P4 | corpus burn-down needs a working new engine + harness |
| P3 | — | — | P2-B green + full suite + quiet window (X) | — | only after the evidence exists and the external window is open |
| P4 | P1-E | P1-F (F-34 sync) | — | P2-B | hint re-solve on the finished solver |

**Two-track execution (recommended, matches the session-budget plan)**

- **Track A — model core**: P1-C1 → P1-C2 → P1-D → P1-E → (P4 optional)
- **Track B — data + harness + assembly**: P1-B → P2-A → P1-F → P2-B
- **Join point**: P1-F needs P1-E from Track A (and the real snapshot from Track B); P3 needs P2-B green **plus** the external quiet window.
- Nothing in Track A needs Track B's data to *write code* — synthetic fixtures cover every D edge; the tracks only join for the end-to-end golden pass.

## 5. Audit-driven additions (2026-11-17)

**A9 + M3 — Fixture sanitization & versioning (P1-A)**: G-01's source payload is anonymized before becoming `tests/golden/g01.json` (strip `device_id`, `account_id`, session ids; keep musts/dates/candidates/plan shape). `FactSnapshot.schema_version = 2` (2026-11-18 P1-D 字段扩展后升级，G-01 同提交迁移)；fixture regeneration + expectation re-bless land in the same commit when the POI library changes.

**M7 — Golden assertion schema (P1-A)**: per scenario, an ordered list of assertions `{type, args}`: `sequence` (relative card order), `time_range` (start/end window), `same_venue` (meal anchor == site coords), `card_leg_consistent` (visit.start == leg.arrive + last_mile), `no_unrequested_before` (before the remote access leg), `requested_coverage` (every requested item timed **or** unplaced+disclosure — untimed requested cards are a hard failure), `no_entry_cap_breach`, `disclosure_contains` (bilingual key), `deterministic` (two runs byte-identical). Exact times are asserted **only** where a timetable fixes them (e.g. shuttle 09:30 → arrive 11:08); everything else asserts shape invariants.

**M6 — Shadow operations (P2-A)**: offline batch by default (no in-request double compute): the harness replays committed snapshots through both engines and writes diff reports. Optional live sampling behind flag at ≤ 5% of generations, max 1 extra solve per session. Reports retained ≥ 8 weeks under `DESIGN/Global CP-SAT/shadow/`; reviewed at every P2-B iteration.

**M8 — P3 rollback plan**: instant flag flip `TRIP_SOLVER=legacy` (no data migration — plan/session schemas unchanged). Triggers: any P0-gate violation on live traffic, convergence < 99% on the live sample, error rate above the legacy baseline, or a user-reported regression class. After a rollback, every incident becomes a corpus scenario before the next attempt.

**M12 / Q7 — Edit latency (P4)**: re-solve on edit targets ≤ 800 ms with hint; on overrun, keep the current plan, disclose 「重排中，稍后自动更新」, and finish in background — interactions never block on the solver.

**M14 — P1-B data-readiness checklist (acceptance)**: hours parse success ≥ 99% of candidates; access profile present for every remote candidate; indoor/rain_ok non-null ≥ 95%; duration tier present for 100% of candidates; travel-matrix coverage 100% within selected cities. Any unmet gate fails P1-B acceptance — adapters must not run on bad data.

**M4 (phases part) — P1-E envelope acceptance**: measured snapshot ≤ 300 ms, solve ≤ 3 s including certificate path, assembly ≤ 200 ms; model-size arithmetic documented against the Q2 cap (see design-functions performance envelope).

**M15 — B-16 ownership**: assigned to the new intent layer (F-01/F-02). P1-B acceptance adds 「form/preferences 必去 binds on fresh structured start」; a legacy hotfix is optional and outside this plan.

## 6. Token-economy operating rules (how each session stays cheap)

1. **Work from the package spec, never re-scan the repo.** The function inventory, coverage audit and parity matrix already exist; each session reads *its own package section* of the design doc, not the codebase.
2. **Reuse fixtures, not live probing.** G-01's real session payload is already dumped; every corpus scenario is a static JSON. No repeated live-server reproduction unless something is genuinely new.
3. **Targeted tests only.** Run the new module's tests plus named contract suites; the full ~3.6 k-test suite runs **once at P3** (and at P1-F if desired), not after every package.
4. **`plan.py` only by line range.** Anchors for every pass already recorded (e.g. `_assign_must_family_days` 15054). Never load the whole 35 k-line file into context.
5. **Adapters, not rewrites.** When an existing pure function has the semantics (dedupe, hours, access, fares), call it read-only instead of re-implementing — fewer LOC, fewer tokens, fewer bugs.
6. **Decide Q1–Q5 up front** (below) so no package is reworked for a policy change mid-build.
7. **Commit at every package boundary** (auto-commit rule). A fresh session always starts from a clean, committed state.

## 7. Prerequisites — Q1–Q7 (**all accepted 2026-11-17: 「DEFAULTS OK」**)

| Q | Question | Default (accepted 2026-11-17) |
|---|---|---|
| Q1 | Duration tiers for outliers (颐和园 300 min) | typ = min(library, 240) for park/garden-type big sites; always disclose clamping |
| Q2 | Fill-pool cap entering the model | ≤ 6 unrequested candidates per day, only after requested coverage is feasible |
| Q3 | Trip-level convergence within 3 s | measured at P1-E/P2-B; if tight, raise budget per tier **with disclosure** — never fall back to sequential ordering |
| Q4 | Remote-lunch nesting when arrival < 11:00 | visit first, lunch after, if arrival+lunch would start before 11:00; otherwise lunch at arrival (先午餐后游览) |
| Q5 | Objective weights | must ≫ wish ≫ fill; keep `_MUST_RAIN_*` and `plan_score` constants numerically where they exist |
| Q6 | City order on multi-city trips | **intent-layer input** (model respects it) — from audit M11 |
| Q7 | Edit re-solve latency | ≤ 800 ms with hint; on overrun keep plan + disclose 「重排中」 — from audit M12 |

## 8. What deliberately stays out of scope (keeps the build small)

- No changes to intent/LLM prompts, H5 front-end, bookings/payments/travelers, POI backfill pipelines.
- `plan.py` untouched through P1/P2 (side module + shadow). Only P3 adds a few lines behind a flag.
- Existing P0 outbound gates and contract suites are **reused as acceptance**, not rebuilt.
