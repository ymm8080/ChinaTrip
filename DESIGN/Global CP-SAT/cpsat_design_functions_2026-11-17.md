# Global CP-SAT — Design Function Specification

**Date**: 2026-11-17 · **Status**: design package 2/2, **design only — no implementation** (user decision: design first) · **Inputs**: `cpsat_as_is_2026-11-17.md` (architecture + function inventory + bug register B-01…B-20 + reference incident), `cpsat_feature_parity_2026-11-17.md` (14-domain function matrix), `cpsat_trip_level_adr_2026-11-17.md` (ADR, migration P0–P3), `cpsat_implementation_phases_2026-11-17.md` (packages + DAG), `cpsat_coverage_audit_2026-11-17.md` (function audit), `cpsat_design_audit_2026-11-17.md` (package audit whose findings this revision applies)

---

## 0. Direct answer: can incident 24379abd be resolved by the global CP-SAT model?

**Yes for the scheduling core — with two honest caveats (assembly and data), which are covered by dedicated design functions below.**

| Symptom (AS-IS §5) | Global-model mechanism | Model alone sufficient? |
|---|---|---|
| **B-01** 颐和园 silently invisible (untimed must card stripped from response) | `requested[r] ∧ ¬presence[r] → unplaced_var[r] = 1`. A requested item is either present with concrete times or explicitly unplaced with a reason. **Untimed requested cards cannot exist in the solution type.** Disclosure is a variable, not an afterthought (F-20, F-26, F-30). | **Yes, by construction.** |
| **B-02** Unrequested fillers (梵高星空艺术馆, 老舍茶馆) occupy slots while a must has none | Lexicographic objective: tier-① = requested coverage (weighted), tier-② = preference/diversity/**fill reward**. A fill candidate's presence can never trade against requested coverage. Plus a hard gate: no fill on a day while a seatable requested item is unseated (F-21 C-14, F-23). | **Yes, by construction** (this is precisely what the cascade cannot express). |
| **B-03a** Unrequested filler before the remote departure | Hard constraint: on a remote day, no unrequested item may precede the remote visit's access leg (F-21 C-15). 天安门 → direct departure is the only legal shape unless the user asks for more. | Yes. |
| **B-03b** Lunch as a hard gate in the city before the remote leg | Lunch is a **conditional interval**: on a remote day it must nest inside the remote site's same-venue window (先午餐后游览 decision) or follow the visit; it may not sit between the previous city item and the access leg (F-22). Departure time is chosen by the solver, not by the lunch card. | Yes (constraint semantics). |
| **B-03c** Card times ≠ access-leg times (12:38 card vs board 12:45/arrive 14:33) | Access legs are **explicit intervals inside the model**; F-30 materialises cards from the *same* intervals the constraints used. Card ≡ leg by construction. | Model provides the intervals; **consistency is F-30's contract** (assembly). |
| **B-03b′** Lunch anchored to the wrong address (city teahouse instead of 慕田峪) | F-31 anchors meal cards at solution locations (remote site), never at "previous city item". | **Assembly function, not the model** — specified here so it is not forgotten. |
| **B-19** 颐和园 duration 300 min makes the day near-infeasible | F-15 duration tiers (min/typ/max) + clamp-with-disclosure policy; F-26 certificate explains infeasibility instead of dropping. | **Data/policy, not the model** — F-15 + F-26 together. |

## 1. Design principles

1. **Semantics are pinned, machinery is replaced.** All user decisions to date (entry cap 16:30 / big-site 15:30, open-form street exemption, SHOW/night-cruise/night-market exemption, towers not exempt, lunch-before-visit on destination days, no-transport-info = full day, endpoint days only with timed legs, must-coverage disclosure, twin-name disclosure, three-trigger confirmation, best_visit_time library-value only, D5 pin provenance) become **constraints/objectives/inputs**. None of their semantics is dropped.
2. **LLM never places.** LLM does intent extraction (schema-validated, deterministic fallback) and narration only.
3. **Determinism is a red line**: `num_workers=1`, fixed seed, immutable `FactSnapshot`; same snapshot → byte-identical plan (test, not aspiration).
4. **Disclosure is a variable.** Silent loss is unrepresentable; infeasibility returns certificates, not fallbacks.
5. **P0 outbound gates stay** as acceptance invariants on any generation path (defense-in-depth, not duplicate scheduling).
6. **Design-first**: this file specifies functions, data and contracts. Implementation begins only after this package is reviewed.

## 2. Request model and fact snapshot (data contracts)

```
TripRequest        days, dates, cities(+city_days), musts[], wishes[], avoid[],
                   user_pins[], intake{arrival/departure no+time|None}, preferences{},
                   lang, day1_start?, source_itinerary_id?
RequestedItem      rid, poi_id, name, kind=must|wish, importance, user_day_hint?, duration_tier
CandidateItem      cid, poi_id, kind=requested(rid)|fill, category, tier, quality, diversity_group,
                   coords, hours, best_visit_time(lib), indoor, rain_ok, sessions?, remote_cluster
FactSnapshot       TripRequest + candidates + travel matrix + access profiles + weather map +
                   duration tiers + library version hash        (immutable; determinism key)
Solution           presence[cid,day], start[cid], dur[cid], day[cid], access intervals,
                   unplaced_var[rid] + reason codes, slack log, certificate (if infeasible)
```

**Module boundary rules (audit M2)**: `trip_solver/` may import read-only pure helpers from `app/services/itinerary/` (hours/access/fare/geo math) and nothing from `app/services/agent/plan.py`. No DB or network I/O inside solve — everything the solver reads comes from the immutable `FactSnapshot`; I/O happens only in snapshot construction (F-03) and in assembly/edit adapters.

**Snapshot & fixture versioning (audit M3)**: `FactSnapshot.schema_version = 1` (bump on any field change). Golden fixtures are **anonymized** (device/account/session ids stripped) and committed to the repo (`tests/golden/*.json`); when the POI library evolves (hours/durations backfills), fixtures are regenerated and re-blessed in the same commit as the expectation update — never silently.

## 3. Design functions

Conventions: **Inputs/Outputs** are design-level types above. **Covers** = AS-IS domains. **Resolves** = bug IDs. Each function is a *specification unit* for P1 implementation, not existing code.

### Module A — Intent & request (outside the model)

**F-01 `parse_intent(text|form|link, today) -> TripRequest draft`**
LLM-first facts + regex fallback (dates EN/CN, days, day1_start, cities, avoid, wishes); schema validation drops bad fields silently; ambiguity triggers confirmation cards per the three-trigger contract (unique hit = no question).
Covers D1. Resolves: keeps B-10/B-12/B-13 semantics; **B-16** — form/preferences 「必去：…」 must produce `musts[]` on the fresh structured path too (explicit requirement, currently missing). Question policy follows the three-trigger contract across `clarify_questions`, `wish_city_question`, `_resto_question`, `_type_ask_hit`, `_pref_question` and the wish/link/brief parsing family.

**F-02 `bind_requests(draft, library) -> RequestedItem[]`**
Name→POI binding incl. typo prefix/near tiers and fuzzy candidate cards; twin/dup resolution (`_twin_cover` semantics); city gate (out-of-city wishes disclosed, not scheduled); importance ranking.
Covers D1, D2(dedupe). Resolves B-10; feeds requested literals for B-01.

**F-03 `snapshot_facts(request, stores) -> FactSnapshot`**
Single immutable snapshot of everything the solver reads (candidates, hours, matrix, weather, access, durations, library hash). No solver-side I/O.
Covers D14 (determinism precondition). Resolves B-05 (with F-24).

### Module B — Input preparation (outside the model)

**F-10 `build_candidate_pool(snapshot) -> CandidateItem[]`**
Eligibility gates (address shells, bank branches, no-coords), ~30 dedupe semantics, diversity caps, quality ranks (类别精确>距离>时长>评分), `kind=requested|fill` flag. Fill pool capped per city/day to bound model size.
Covers D2. Resolves: preserves B-07 dedupe semantics; enables B-02 gating (kind flag).

**F-11 `travel_matrix(candidates, measured_legs, access_profiles) -> arc costs`**
Haversine estimates + measured-leg replay + cross-river penalties + taxi estimates; access profiles (board windows, ride, last mile, fares) become arc/interval parameters.
Covers D6, D8. Feeds C-03/C-08 and objective③.

**F-12 `hours_windows(candidate, date) -> windows + entry_cap + exemptions`**
Open windows incl. seasonal/closed weekdays; entry cap 16:30 (big 15:30); open-form street exemption; evening-only/SHOW/night exemptions from **library attributes only** (no heuristics); best_visit_time library-value passthrough.
Covers D4, D12. Resolves B-07 semantics; supplies C-01/C-02.

**F-13 `weather_conditions(forecast, candidates) -> per-(cid,day) penalty|forbid`**
`weather_reports` × indoor/rain_ok; rainy-day outdoor = heavy penalty or forbid (heavy rain); rain_outdoor reason emitted for disclosure.
Covers D7. Feeds objective②/conditional constraints. `coverage.py` (`premium_coverage_gaps`, `rain_swap_advice`) supplies premium-gap detection and rain-swap candidates.

**F-14 `access_legs(remote_candidates, profiles) -> interval templates`**
Outbound/return intervals with board windows, ride, last-mile, return-last; **the same templates drive C-08 and F-30**, so card times ≡ leg times.
Covers D6. Resolves B-03c (with F-30).

**F-15 `duration_policy(candidate) -> {min, typ, max}`**
Library `suggested_duration_min` → tiers; outliers clamped **with disclosure** (e.g. 颐和园 300 min → typ 240 / max 300, disclosed when clamped); user-specified durations respected.
Covers D4. Resolves **B-19** (data/policy). Open policy question §7-Q1.

### Module C — The trip-level model (the core)

**F-20 `define_variables(snapshot) -> model vars`**
`presence[cid,day]` (optional), `start[cid]`, `dur[cid]` (within tier), `day[cid]`, access intervals per remote visit, `requested[rid]` literals, `unplaced_var[rid]` bools, arc variables for intra-day sequencing.
**Hard link**: `requested[rid] ∧ ¬presence[rid] → unplaced_var[rid]`.
Covers D3/D4. Resolves **B-01** (no invisible state exists), B-06 (an item is either present or unplaced, never both).

**F-21 `hard_constraints(model, snapshot) -> constraint groups (assumption-tagged)`**

| ID | Constraint | AS-IS semantics preserved |
|---|---|---|
| C-01 | Open windows / closed weekdays / seasonal | `_fits_hours_window`, `_closed_weekdays` |
| C-02 | Entry cap 16:30/big 15:30 + open-form & night exemptions | `generic_entry_cap`, `_hours_open_form`, `_hours_evening_only` (B-07) |
| C-03 | NoOverlap incl. travel arcs (intra-day sequence + travel time) | solver NoOverlap + `_travel_matrix` |
| C-04 | User pins = iron rule 19 (fixed time); engine pins = must-stay, retimable; **fixed sessions** from flag schedule (`_apply_flag_schedule`), comment day-start (`_apply_comment_day_start`), user-chosen shuttle departure (`set_access_departure`) | **D5** (2a56cda), reopen guards (B-09) |
| C-05 | Endpoint days only with timed intercity legs; no transport info = full day; **city order fixed by intent layer (Q6)** | B-11 (438bcfa), `_apply_intake_times` |
| C-06 | Remote-day exclusivity: day with remote cluster item → other items same cluster or none | `_separate_remote_must_days`, `_day_already_remote`, third-cluster eviction (B-08) |
| C-07 | Same city / same river-side per day; multi-city day ranges | `_enforce_day_zones`, `_city_side_ok` |
| C-08 | Access legs as intervals: board windows, ride, last mile, return-last | `_access_profiles`, shuttle timetables (B-03c) |
| C-09 | Meal anchors: lunch/dinner windows; real-restaurant binding immovable; same-venue nesting | `_meal_anchor`, `_bind_real_food_to_cards`, palace rulings |
| C-10 | Lunch-before-visit on destination days (≥15km, arrival 10:30-13:00) | `_lunch_before_destination_visit` (b909d60) |
| C-11 | Show sessions / one show per day / sessionless shows excluded | `effective_show_sessions`, `_enforce_show_per_day` |
| C-12 | Must family same day; day load budget; weekend/weather day preferences | `_assign_must_family_days` family |
| C-13 | Hotel anchors / night return | `_reanchor_nights_hook`, `_head_hotel_anchor` |
| C-14 | **Coverage-before-fill**: while any `unplaced_var[rid]=1` is *seatable*, no `fill` candidate may be present on that day; existing fills yield (objective tiering makes this strict) | **Resolves B-02** (replaces no current pass — the cascade had no such invariant) |
| C-15 | **Remote-day departure**: on a remote day, no unrequested item precedes the outbound access interval | **Resolves B-03a** (supersedes the experience-type fill loophole) |
| C-16 | Diversity caps per day/category (as hard caps where user-visible today) | `_cap_sights_per_day`, diversity families |

Every group carries **assumption literals** so F-26 can name exactly which rule fails.

**F-22 `remote_lunch_constraints(model, snapshot)`** *(called out separately because it is the incident's hard gate)*
On a remote day, lunch is a conditional interval that must either (a) nest in the remote site's same-venue window at arrival (C-10 case) or (b) start after the visit ends; it may **not** be placed between the previous city item and the outbound access interval. Lunch duration/anchor never constrains the outbound departure.
Resolves **B-03b**; replaces the lunch-first swap + city-anchor patch (b909d60's assembly bug is covered by F-31).

**F-23 `objectives(model) -> lexicographic tiers`**
① requested coverage, weighted by importance (must ≫ wish) — **strictly dominates everything**;
② preference/diversity/quality score + weather-conditioned penalties + **fill reward** (fill can only ever win inside tier ②);
③ total travel minutes (incl. access) minimised;
④ makespan.
Covers D2/D3/D9 scoring semantics (`plan_score` cost tower becomes tiered objectives).
Resolves **B-02** (with C-14); replaces `_morning_extra_cost/_big_first_cost/...` hand-tuned tower.

**F-24 `solve_budgeted(model, budget=3s, workers=1, seed=fixed, hint?) -> Solution|INFEASIBLE`**
Fixed workers+seed; optional previous-solution hint (edits); returns solution or tagged-infeasible — **never** a sequential fallback.
Covers D14. Resolves B-05 (determinism), removes B-04's fallback path.

**F-25 `slack_ladder(model) -> relaxation steps`**
Declared order, each step logged for disclosure: drop fill candidates → relax diversity caps → relax soft time-of-day preferences → relax weather penalties → relax remote-day exclusivity **only with disclosure** → (never relax: open windows, entry cap, user pins, timed legs, requested-coverage disclosure link).
Each relaxation emits a structured reason; the last resort is infeasibility with certificate, not a silently degraded plan.
Resolves B-04 (fallback replaced by explicit, disclosed relaxation).

**F-26 `infeasibility_certificate(model, assumption tags) -> reason set`**
`sufficient_assumptions_for_infeasibility` → minimal conflicting rule set → reason codes (e.g. 「故宫 15:30 停止检票 + 颐和园需 ≥240min + 天坛 150min ⇒ D2 不可全排」). Reason codes attach to `unplaced_var[rid]`.
Resolves B-01/E-4 (honest "why"), B-04 (no 「未收敛」 hand-wave).

### Performance envelope (audit M4)

- Budget split per solve: snapshot build **outside** the 3 s CP-SAT budget, target ≤ 300 ms; solve ≤ 3 s (incl. certificate path); assembly ≤ 200 ms. End-to-end worst case ≈ 3.5 s per generation, same order as today's cascade.
- Model-size bound (from Q2): candidates = requested (musts+wishes) + ≤ 6 fill/day, so variables ≈ (requested + 6·days) × days presence + start/day vars + access intervals. Example: 5 requested + 12 fill × 2 days ≈ 34 presence vars + ~70 time vars — small for CP-SAT; 7 days × (10 + 42) ≈ 364 presence vars is the Q3 stress case.
- Worst case = INFEASIBLE → F-25 ladder + F-26 certificate, bounded by the same budget; **never** a sequential fallback.

### Module D — Solution → plan assembly (outside the model)

**F-30 `materialize_plan(Solution, FactSnapshot) -> ItineraryPlan`**
Cards start/end come from solution intervals; access-leg cards come from the **same** F-14 intervals (card ≡ leg by construction); a requested item not present becomes an `unplaced` entry with reason + disclosure — **an untimed requested card is a type error** (assert in tests).
Resolves B-01, B-03c. Assembly entry points retained and driven by the same solution intervals: `annotate_legs` (leg/fare materialisation) and `attach_return_cards`; reservation-hint helpers attach here.

**F-31 `meal_card_assembly(Solution) -> meal cards + anchors`**
Meal cards anchored at solution locations: remote-day lunch at the remote site (or post-visit), city meals at the neighbouring visit; address from the POI record, never "previous city item".
Resolves B-03b′ (the 老舍茶馆-anchor defect).

**F-32 `alternatives_chips(plan, pool) -> response extras`**
Unchanged: 0.3 km alternative pairing, insert-alt support, reservation hints, bilingual fields.
Covers D9/D11/D13 assembly.

**F-33 `disclosure_renderer(slack log, certificate, weather, coverage) -> bilingual lines`**
All disclosures from structured reasons (not LLM invention); bilingual by `lang`; 「求解器未收敛，时间已按顺序兜底排列」 is **deleted** — replaced by certificate/relaxation lines.
Resolves B-04 wording + B-01/E-3 visibility. Reason-code → bilingual text lives in `trip_solver/disclosure_templates.json`; every certificate reason code must have both-lang entries, and a test asserts 100% code coverage (audit M13).

**F-34 `session_trip_center_sync(plan, session) -> synced stores`**
Session persistence and trip-center (行程中心) sync: `sync_trip_rows`, `_sync_wish_rows`, `_sync_planned_rows`, `sync_removals_to_trip_items`, `ensure_unique_item_ids`, session-store plumbing (`get_plan_session_store`, `live_itinerary_ids`, `alloc_item_id`). Wish rows mirror scheduled/unplaced state with disclosures; removals propagate; item ids stay unique.
Covers D10/D13. Engine-independent; behavior unchanged, driven by F-30's materialised plan.

### Module E — Acceptance & runtime invariants (stay outside)

**F-40 `runtime_gates(plan, request) -> violations`** — P0 gates retained verbatim: must三分律, double-presence dedupe, entry-cap read gate, rain_outdoor, twin-substitution disclosure. Any generation path (old or new) must pass; on the new engine these should be vacuously green (proof of "class eliminated").
**F-41 `determinism_guard(snapshot) -> bool`** — same snapshot → byte-identical plan; red-line test in CI.
**F-42 `runtime_offload`** — solver runs in `to_thread` (or a worker); event-loop freeze budget ≤ today's post-fix level (p95 target ≤ ~250 ms during generation).
Covers D11/D14; resolves B-15 regression risk.

**F-35 `entry_adapter` (audit M1)** — the only call path between legacy/api and the new engine: `solve_trip(request, snapshot, *, flag='legacy'|'shadow'|'cpsat', budget, hint=None) -> Solution`, always invoked via `asyncio.to_thread`. `flag` from env `TRIP_SOLVER` (default `legacy`). Timeout/INFEASIBLE → F-25/F-26 certificate, never a fallback sequence. Exceptions: fail loud in tests; in production with flag=cpsat, catch → emit telemetry, fall back to legacy engine **with disclosure** (this is also the P3 rollback path). P0 outbound gates run downstream of either engine, always.

**F-36 `solve_telemetry` (audit M5)** — structured per-solve log: `{snapshot_hash, schema_version, status, wall_ms, n_vars, n_cons, slack_level, unplaced_count, fill_count, hint_used, solver_version}`; feeds the F-62 convergence metric, the P2 diff report, and the P3 rollback triggers. Logged for both engines in shadow so the comparison is apples-to-apples.

### Module F — Edit & lifecycle

**F-50 `edit_resolve(session, DiffOp) -> Solution`** — move/retime/duration/delete/pin → re-solve with previous solution as hint; reopen keeps already-timed user pins and engine musts as anchors (B-09 guards become C-04 facts).
**F-51 `pin_provenance`** — user pin vs engine pin persisted on items (D5); engine-pinned items retimable/movable by the solver, user pins never.
Covers D10; resolves B-09 semantics, B-20 implementation.

### Module G — Shadow evaluation & acceptance

**F-60 `golden_corpus`** — incident-derived scenarios, starting with **G-01 = session 24379abd** (expected shapes E-1…E-4 in AS-IS §5), plus this week's fixed incidents as regression scenarios (tower late-gate, ZHUJIAZUI, reopen preserve, no-transport full-day, rain rebalance, third-cluster eviction…).
**F-61 `shadow_compare(snapshot) -> diff report`** — old cascade vs global model on the same snapshot; **relative criteria**: not-worse on every corpus scenario + bug classes eliminated + convergence rate; never requires the old engine to be perfect first.
**F-62 `acceptance_metrics` (P3 gate, thresholds per audit M9)** — parity checklist 14/14 domains; corpus ≥ 12 scenarios incl. G-01, all green; relative criterion per scenario = not-worse (plan-score Δ ≥ −2% vs legacy) **and** violation classes B-01/B-02/B-03/B-06 = 0; convergence (OPTIMAL or FEASIBLE within budget) ≥ 99% of corpus runs; 「求解器未收敛」 disclosures = 0; contract/audit suites green; determinism = byte-identical across 2 runs of every snapshot; latency inside the M4 envelope. Failing any ⇒ stay in shadow (zero-risk).

## 4. Traceability — every bug has a design mechanism

| Bug | Design function(s) | Mechanism | Residual risk / companion work |
|---|---|---|---|
| B-01 silent must-drop | F-20, F-26, F-30, F-33, F-40 | unplaced_var + no-untimed-type + disclosure + P0 gate | none (class eliminated by type) |
| B-02 fill over must | C-14, F-23 | coverage strictly dominates fill; fills yield | fill-pool cap tuning (§7-Q2) |
| B-03a filler before remote departure | C-15 | hard ordering ban | — |
| B-03b lunch hard gate / wrong anchor | F-22, F-31 | conditional interval + solution-location anchor | — |
| B-03c card ≠ leg times | F-14, F-30 | one interval source | — |
| B-04 solver fallback | F-24, F-25, F-26, F-33 | no fallback; disclosed relaxation + certificate | trip-level convergence must be proven in shadow (§7-Q3) |
| B-05 binding drift | F-03, F-24, F-41 | snapshot + fixed seed/workers + red-line test | LLM intent still needs confirmation cards (kept) |
| B-06 double presence | F-20, F-40 | presence xor unplaced + P0 gate | — |
| B-07 tower late gate | F-12 (C-02) | library attributes only, no heuristic night tags | data backfill stays manual/LLM-tagged |
| B-08 third-cluster / city lunch | C-06, F-22 | remote exclusivity + lunch placement | — |
| B-09 reopen drops | C-04, F-50 | reopen anchors as facts | — |
| B-10 typo misbind | F-01, F-02 | fuzzy candidates + confirmation | — |
| B-11 endpoint without transport | C-05 | timed-leg precondition | — |
| B-12/B-13 LLM questions/dates | F-01 | same validated intent layer | — |
| B-14 audit-before-save | F-40 wiring | save-time gate unchanged | — |
| B-15 loop freeze | F-42 | offload contract | residual small freezes monitored |
| B-16 form must-binding | F-01, F-02 | explicit requirement for fresh structured path | **independent of engine; fix in P1 intake** |
| B-17 rechain test red | — | parallel transfers account, not model scope | fix independently |
| B-18 wish singleton | — | session-store concern, not model scope | fix independently (per-session bindings) |
| B-19 颐和园 300 min | F-15, F-26 | duration tiers + honest certificate | **policy decision needed (§7-Q1)** |
| B-20 pin provenance | F-51, C-04 | D5 user/engine pin split | lands with P1 |

**Domain coverage**: D1→F-01/02, D2→F-10/F-23, D3→F-20/C-05/06/07/12, D4→F-12/F-15/C-01/02, D5→C-09/10/F-22/F-31, D6→F-11/F-14/C-08, D7→F-13, D8→F-11/C-06/07/15, D9→C-14/F-23/F-32, D10→F-50/51, D11→F-33/F-40, D12→F-12/C-11, D13→C-13/F-32/F-34, D14→F-24/41/42. Every AS-IS function from the parity matrix maps to exactly one fate: constraint (C-xx), objective (F-23), input (F-10…F-15), assembly (F-30…F-33), gate (F-40), or retired executor (ripple/flex/fallback/LLM-repair — semantics absorbed by C-xx/F-25).

## 5. What the global model does NOT solve alone (be explicit)

1. **Data quality** (durations, hours, coords, names): garbage in → faithfully wrong plan out. B-19 policy + backfill pipelines continue independently.
2. **Shuttle timetable truth**: the model uses access profiles as given; wrong/outdated schedules need data maintenance (F-14 input, not solver logic).
3. **LLM intent mistakes**: kept in check by the existing confirmation-card contract (F-01/F-02), not by the solver.
4. **Weather forecasting itself**: forecast is input (F-13); the model only conditions on it.
5. **Assembly defects** (anchors, addresses, bilingual text): F-30…F-33 are specified precisely because the model cannot fix them.
6. **Concurrency/session-store concerns** (B-18, residual freezes): engineering, independent of engine.

## 6. Migration mapping (unchanged from ADR, now function-indexed)

- **P1 (side module, no plan.py contact, start any time)**: F-01…F-26 in a new `trip_solver` module + unit tests per function; legacy cascade remains live.
- **P2 (shadow)**: F-60…F-62; corpus built from AS-IS §4/§5; relative-criteria reports.
- **P3 (switch, single small diff behind a flag)**: F-30…F-33 wired as the plan source; F-40 gates stay as acceptance; quiet-window precondition (48 h or aligned with parallel session) applies **only here**.
- **P4 (edits)**: F-50/F-51 hint-based re-solve replacing the ripple/resequence ladders.

## 7. Open design questions — **all accepted 2026-11-17 (user 「DEFAULTS OK」)**

**The seven values below are binding design decisions, not proposals.**

- **Q1 Duration tiers**: default clamp policy for outlier `suggested_duration_min` (e.g. 颐和园 300): typ = min(library, 240)? Per-category caps? Always disclose clamps (recommended).
- **Q2 Fill pool cap**: max unrequested candidates per city/day entering the model (performance vs variety); default proposal ≤ 6/day, only after requested coverage is feasible.
- **Q3 Trip-level convergence**: prove within the 3 s budget on the largest realistic case (5 musts + ≤12 fill × 2–7 days); if tight, escalate budget per tier with disclosure, never fall back to sequential ordering.
- **Q4 Remote-lunch semantics**: exact nesting rule when arrival < 11:00 (lunch window not yet open) — visit-then-lunch vs wait; default: visit first if arrival + lunch would start before 11:00.
- **Q5 Objective weights**: importance weights for must/wish tiers and the weather penalty scale, migrated from `_MUST_RAIN_*` and `plan_score` constants (keep numeric parity where possible).
- **Q6 Multi-city order** (audit M11): city sequence is fixed by the intent layer (recommended) — the model respects it; only day allocation inside each city is optimized.
- **Q7 Edit latency** (audit M12): re-solve on edit targets ≤ 800 ms with hint; if exceeded, keep the current plan and disclose 「重排中，稍后自动更新」 while the background re-solve completes.

**Next step on user approval**: review this package, settle Q1–Q7, then implement P1 (F-01…F-26) in the side module with G-01 as the first golden test.

---

### Constants migration table (audit M10)

| Parameter | Current source of truth | Model value |
|---|---|---|
| Generic entry cap | solver `_GENERIC_ENTRY_CAP_MINUTES` (16:30) | 990 min |
| Big-site entry cap | solver big-site cap (15:30) | 930 min |
| Rain penalties | `_MUST_RAIN_OUTDOOR_PENALTY=240`, `_MUST_RAIN_INDOOR_PENALTY=60` | 240 / 60 (unchanged) |
| Fill-pool cap | new (Q2) | ≤ 6 unrequested/day |
| Duration tier clamp | new (Q1) | typ = min(library, 240) for big park/garden sites, disclosed |
| Day-load / cluster caps, family weights, head/morning cost terms | solver/scoring/plan constants | **migrate verbatim at P1-B** — lifted from the current constants into the model params file with a source comment; never re-tuned during migration |

## 8. Coverage audit (647 functions, 2026-11-17)

Mechanical verification that this design covers all current functionality and rules — full per-function mapping in `cpsat_coverage_audit_2026-11-17.md`.

- 647 engine functions scanned (`agent/plan.py` + 12 `itinerary/` modules).
- 235 explicitly cited in the four design docs; **367 more mapped to rule families** (rules.py validators, leg/return assembly, fixed-session anchors, block-family/umbrella binding, cluster cohesion, endpoint classifiers, meal slot/nesting, solver cost terms, intent/question policy, geo/id/store engineering…); **45 pure utilities** (formatting/tiny predicates/local closures) carry no user-visible rule of their own.
- Added by this audit: F-34 (session & trip-center sync); C-04 now names fixed sessions from `_apply_flag_schedule`, `_apply_comment_day_start`, `set_access_departure`; F-30 names `annotate_legs`/`attach_return_cards`; F-01 names the question-policy functions; F-13 names `premium_coverage_gaps`/`rain_swap_advice`; `rules.py` validators (`validate_plan`, `_check_*`, travel-gap) are explicitly F-40 acceptance invariants.
- Standing rule: any function found hereafter that is not in this audit gets added to the appendix and to the parity checklist, and blocks the P3 switch until mapped.
