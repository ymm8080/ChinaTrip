# AS-IS — Current Planning Engine: Architecture, Function Inventory, Bug Register

**Date**: 2026-11-17 · **Status**: design package 1/2 (design-first per user decision; **no implementation in this round**) · **Companions**: `cpsat_trip_level_adr_2026-11-17.md` (architecture decision), `cpsat_feature_parity_2026-11-17.md` (function-level parity matrix), `cpsat_design_functions_2026-11-17.md` (design package 2/2)

---

## 1. Sources and method

- **Code scan (2026-11-17, rg over the repo)**: `app/services/agent/plan.py` ≈35k lines, 400+ module-level functions, 170+ class methods; `app/services/itinerary/` 14 modules (solver / scoring / rules / legs / fares / geo / pipeline / coverage / request_coverage / best_visit / edit_distance / item_ids / visa_check / models); `app/api/plan.py` 20 endpoints; `tests/` 150+ files.
- **Live incident evidence**: `plan_sessions` rowid 3687, session `24379abdaf744b90b52ef7e1c958b15a` (device `dev-hs4e9vhk`, Beijing 2 days starting 2026-11-25, must_visits = 天安门广场 / 故宫博物院 / 慕田峪长城 / 天坛 / 颐和园). Full payload dumped and analysed (see §5).
- **Incident history**: fix commits referenced per bug (e9b492c, 9630b98, e87f40e, 6dc89c3, 66e0a7e, 4576c32, b909d60, d721b88, 438bcfa, 29b178d, bd90b8d, fd29906, f4d6d09, 5efb1a4, 2a56cda).

## 2. Architecture as-is (pipeline, with anchors)

```
S1 Intake & intent      brief/link/message/form → _trip_brief / _mine_brief_sites /
                        trip_facts_from_llm (LLM facts, validated) → site_confirm card →
                        wish_bindings + must_visits (PlanSession)
S2 Candidate selection  _deterministic_selection + pool-worthiness / ~30 dedupe rules /
                        diversity caps / quality ranks (_cand_quality, _source_tier, _site_rank)
S3 Day assignment       _assign_must_family_days (15054) → _separate_remote_must_days (15204)
                        → _pin_musts_by_importance (15426) → _enforce_day_zones / endpoint days
                        (_day_is_arrival / _day_is_return_home / _day_has_departure)
S4 Time scheduling      solver.solve_day (CP-SAT, 3s budget, single day only);
                        solve_plan (2334) merely LOOPS days; insertion_schedule_day for inserts;
                        on infeasible → LLM repair chain → _fallback_sequence_times (12099)
                        + disclosure 「求解器未收敛，时间已按顺序兜底排列」
S5 Repair cascade       _place_with_flex (14414) → _ripple_after_duration (12024) →
                        _compress_before_evening_anchor (14060) → _lunch_before_destination_visit (12963)
                        → meal passes (_retime_meal_placeholders 13075 / _ensure_meal_cards /
                          _bind_real_food_to_cards 13961 / _open_meal_leg_gaps 13279)
                        → fill_leftover_gaps + _fill_leftover_with_diverse_sights (15942)
                        → _evict_third_cluster_extras (15832) → _rain_rebalance_days (17744)
                        → _global_resched (31302) / _rebalance_days (28147)
                        → _must_visit_room_sweep (16299) / _must_visit_crossday_rescue (30237)
                        / _seat_unplaced_musts (18859) → _finalize_untimed_visits (30774)
S6 Outbound gates       _evict_evening_gate_breachers (12902); enforce_entry_gate (read gate,
                        6dc89c3 + open-form exemption 66e0a7e); request_coverage audit
                        (三分律 missing_must_visits / ensure_must_disclosure /
                        dedupe_unplaced_against_scheduled) — run BEFORE save (fd29906)
S7 Response assembly    _plan_for_response → _strip_untimed_items + alternatives chips
                        (attach_plan_alternatives) + legs/fares materialisation
S8 Edit & session       20 API endpoints; move/retime/duration/delete/reflow_after_delete;
                        reopen preserve-pinned guards (b909d60); to_thread offload (agent 8 + api 20);
                        SQLite WAL + busy_timeout (f4d6d09); PG trip-items read-through
```

**Structural facts that matter for the redesign**

1. CP-SAT already exists but its authority stops at **single-day times**. Day assignment, must binding, candidate selection, and all cross-day reasoning live in the heuristic cascade.
2. ~30 repair passes are **order-dependent and locally scoped**: each pass sees a local view, so a legal output of pass A can be pushed illegal by pass B (observed: ripple chain sliding items past the 15:30 entry cap; lunch re-sequencing leaving a city-anchored lunch before a remote leg).
3. Outbound gates exist **because** the cascade cannot guarantee invariants (silent must-drop, double presence, entry-cap breach). They are compensations, not proofs.
4. Response assembly strips untimed cards — so any pass that leaves a must-visit untimed produces a **silent disappearance** in the UI (B-01).

## 3. Function inventory (14 domains — summary)

Full function-level matrix (every domain: current implementation → fate in the global model → acceptance test anchor) is in `cpsat_feature_parity_2026-11-17.md`. Summary:

| # | Domain | Representative entry functions |
|---|---|---|
| 1 | Intent understanding & request binding | `_parse_text_start_date`, `trip_facts_from_llm`, `_parse_site_answer`, `_wish_bind_candidate`, `commit_wish_drafts`, `_merge_must_visits` |
| 2 | Candidate pool: eligibility / dedupe / diversity / quality | `_pool_worthy`, `_same_site`, `_contained_twin_pair`, `_museum_umbrella_dup`, `_cand_diversity_group`, `_cand_quality`, `_deterministic_selection` |
| 3 | Day structure (must families, remote days, city clusters, endpoint days, intake, reopen) | `_assign_must_family_days`, `_separate_remote_must_days`, `_pin_musts_by_importance`, `_day_is_arrival`, `_apply_intake_times` |
| 4 | Day scheduling & entry gates | `solver.solve_day`, `insertion_schedule_day`, `generic_entry_cap`, `_hours_open_form`, `_place_with_flex`, `_closed_weekdays` |
| 5 | Meals (placeholders, cards, real restaurants, banquet shows) | `_ensure_meal_cards`, `_bind_real_food_to_cards`, `_lunch_before_destination_visit`, `_open_meal_leg_gaps`, `_reassign_banquet_days` |
| 6 | Transport & access legs | `_apply_transfer_schedule`, `_placeholder_leg`, `_access_profiles`, `_replay_measured_legs`, `_travel_matrix`, return-card family |
| 7 | Weather | `_rain_map`, `_rain_rebalance_days`, `_rain_exposed`, `_MUST_RAIN_OUTDOOR_PENALTY` |
| 8 | Geography & evictions | `_near_day_city_anchor`, `_evict_third_cluster_extras`, `_day_already_remote`, `_city_side_ok` |
| 9 | Gap fill / alternatives / untimed governance | `fill_leftover_gaps`, `_fill_leftover_with_diverse_sights`, `attach_plan_alternatives`, `_yield_for_premium`, `_finalize_untimed_visits` |
| 10 | Edit & session lifecycle (20 endpoints) | `move_item`, `retime_item`, `set_item_duration`, `reflow_after_delete`, `_apply_structural`, pin endpoints |
| 11 | Audit & disclosure (P0 defense-in-depth) | `missing_must_visits`, `ensure_must_disclosure`, `dedupe_unplaced_against_scheduled`, `enforce_entry_gate`, `_lang_directive` |
| 12 | Shows / night activities | `effective_show_sessions`, `_enforce_show_per_day`, `_show_off_season`, evening exemptions |
| 13 | Hotels / bookings / travelers / visa | `_reanchor_nights_hook`, set-hotel endpoint, bookings/travelers/visa modules |
| 14 | Runtime contract | `_deterministic_selection`, to_thread offload, 3s budget, WAL pragmas, idempotent gates |

## 4. Bug register

Class: **S** = structural (decomposed-cascade root), **I** = implementation (single-pass/ wiring), **D** = data. Status: OPEN / PARTIAL / FIXED(commit).

| ID | Symptom (evidence) | Root cause | Class | Status |
|---|---|---|---|---|
| **B-01** | Required 颐和园 invisible in UI: untimed `PIN,MUST` card at end of D2, `start_time=null`; response strips untimed cards; `unplaced=[]`, no disclosure (session 24379abd) | Producer: bind-by-name sets `pinned=True` before `_pin_musts_by_importance` assigns times; when time-pinning fails the must stays **pinned+untimed** (same intermediate state as B-04 trigger #1). Then: audit counts "untimed card present" as *scheduled* (三分律 hole); response strip makes it invisible | **S** (cascade leaves untimed + audit/assembly mismatch) | **OPEN** |
| **B-02** | Unrequested POIs occupy slots while a required must has none: 梵高星空艺术馆 D2 15:30-17:00 with 颐和园 untimed; 老舍茶馆 D1 09:10-10:10 | `fill_leftover_gaps` / diversity fill scores gaps & variety only; no priority of requested coverage over unrequested fill | **S** (priority inversion) | **OPEN** |
| **B-03** | Remote-day departure blocked: D1 天安门 07:10-08:40 → 老舍茶馆 09:10-10:10 (unrequested) → lunch 11:38-12:38 **anchored at 老舍茶馆 (city)** → 慕田峪 12:38-15:38. Disclosure claims 「午饭 11:38 在慕田峪长城」; lunch card's own leg detail says board 12:45 → arrive 14:33, contradicting card times; 115-min access leg absent from card times | (a) experience-type fill passes the "remote day experiences only" gate and lands **before** the remote visit; (b) lunch-first re-sequencing anchors lunch to previous city item instead of the remote site; (c) card times and access-leg times computed by different passes, never reconciled | **S** (a,c) + **I** (b anchor) | **OPEN** |
| **B-04** | 「求解器未收敛，时间已按顺序兜底排列」 on 13/13 generations in baseline probes | Two concrete degradation triggers now FIXED: (1) pin-by-name sets `pinned=True` before times are assigned, and the intermediate `pinned + no-time` card made `solver._visit_spec` reject the whole day (e6133a4); (2) `TransferItem.poi_id` AttributeError crashed `_travel_cost` (b2f6597). Residual structural cause: single-day CP-SAT infeasible → LLM repair → sequential fallback; cross-day/must reasons not representable | **S** | **PARTIAL** (e6133a4 + b2f6597 + disclosure split 5efb1a4 landed; convergence rate to re-measure; structural fallback remains the global model target) |
| **B-05** | Same input → different plans (binding drift) historically; fresh structured-start binding weak | Cascade order-dependence + LLM in the loop + non-fixed search | **S** | **PARTIAL** (message path byte-stable since e9b492c; fresh v0 path weak) |
| **B-06** | Double presence: same site as pinned card AND in `unplaced` (69/500 sessions at baseline) | Multiple passes move/copy items without a single invariant | **S** | Gate FIXED 9630b98 (dedupe at outbound); **production source OPEN** |
| B-07 | Observation towers scheduled past entry cap (上海中心大厦 19:00) | `best_visit_time` heuristic `viewpoint→sunset` exempted towers from the day-entry cap | I+D | FIXED e87f40e + read gate 6dc89c3 + open-form 66e0a7e; 115 heuristic rows rolled back, 64 real night rows manually tagged |
| B-08 | Lunch driven back to city on 慕田峪 day; third-cluster POI (延庆观景台) filled into D1 | Distance gates failed on return-home day; centroid dragged north | I | FIXED 4576c32 (25km city circle, day-anchor remoteness, third-cluster eviction) |
| B-09 | Reopen dropped already-scheduled musts (慕田峪 「暂排不上时刻」) | Reopen chain cleared times of pinned/must cards | I | FIXED b909d60 (five reopen guards) |
| B-10 | ZHUJIAZUI recognised as 陆家嘴 instead of 朱家角 | LLM normalised the misspelling to a famous name; no library verification | I | FIXED d721b88 (typo prefix/near tiers + fuzzy confirmation card) |
| B-11 | No transport info → both days treated as arrival/departure endpoints, big sites evicted | Unconditional `day==1` / last-day mirror branches (11-08) bypassed the intake system | I | FIXED 438bcfa (endpoint day requires a timed leg; no info = full day) |
| B-12 | LLM asked endless clarifying questions / asked when not needed | Prompt discipline | I | FIXED 29b178d (three-trigger confirmation contract) |
| B-13 | English dates unread; 「11AM」 parsed as 11 days | Regex gaps; bare-int fallback unmasked | I | FIXED bd90b8d (LLM-first facts + regex fallback + time masking) |
| B-14 | Coverage audit only affected the response, DB stayed dirty (dup 67→62 after fix) | `store.save` happened before the audit | I | FIXED fd29906 (audit before save on GET/start) |
| B-15 | Event loop frozen 8.2s during generation; SQLite cross-process write lock | Sync solver chain on the loop; no WAL/busy_timeout | I | FIXED to_thread (d721b88) + WAL (f4d6d09); **residual ~2.8s freeze OPEN-minor** |
| B-16 | Form/preferences 「必去：…」 not bound on fresh structured `/plan/start` (brief/message paths bind fine) | Binding channel coverage | I | **OPEN** |
| B-17 | `test_rechain_visit_after_earlier_arrival` red on clean baseline | Parallel transfers area | I | **OPEN** (parallel-session account) |
| B-18 | `_wish_bindings` singleton draft shared across concurrent sessions (cross-contamination risk) | Process-global draft buffer | I | **OPEN** (risk, no confirmed user incident) |
| B-19 | 颐和园 `suggested_duration_min=300` (5h) makes a 2-day/5-must trip barely feasible; duration has no tiers | Library duration is a single unbounded value | **D** | **OPEN** (duration tiering/clamping policy needed) |
| B-20 | Engine-pinned musts could not be retimed/moved even when infeasible (pin semantics) | No provenance on `pinned` | I | Decision landed 2a56cda (**D5**: user pin = iron rule 19, engine pin = must-stay-but-retimable); implementation rides with P1 |

**Structural conclusion**: B-01, B-02, B-03(a,c), B-04, B-05, B-06 are **one family** — the decomposed cascade produces locally-legal/globally-broken plans and the outbound gates only mop up afterwards. This family is the target set of the global CP-SAT model. B-07…B-18 are engine-independent fixes that must keep working (the global model inherits their *semantics*, not their patch machinery). B-19 is data and must be fixed regardless of engine.

## 5. Reference incident 24379abd — evidence and expected shapes

**Input**: Beijing, 2 days from 2026-11-25, user-confirmed musts 天安门广场 / 故宫博物院 / 慕田峪长城 / 天坛 / 颐和园 (from link text + 「必去：…」 confirmation). No arrival/departure times → both days are full days per B-11.

**Actual output (verbatim sequence)**:

- D1: 🏨 06:10-06:40 → 天安门广场 07:10-08:40 [PIN,MUST] → **老舍茶馆 09:10-10:10 (unrequested, extras-1-)** → 午饭 11:38-12:38 (**anchor = 老舍茶馆 coords, city**) → 慕田峪长城 12:38-15:38 [PIN,MUST] → 晚饭 19:00 → 🏨 21:00. Lunch leg detail: board 12:45 → arrive 14:33 (contradicts card times).
- D2: 🏨 08:30 → 故宫博物院 09:00-11:00 [PIN,MUST] → 午饭 11:30-12:00 → 天坛 12:00-14:30 [PIN,MUST] → **梵高星空艺术馆 15:30-17:00 (unrequested)** → 晚饭 19:00 → 🏨 21:00 → **颐和园 [PIN,MUST] start=null (invisible after response strip)**.
- `unplaced=[]`; only 颐和园-related disclosures: 「按同片区整族并到第1天：颐和园」「远郊那天只留「慕田峪长城」：必去「颐和园」改到第2天」 — moved, then never timed.

**User-expected shapes (acceptance for the golden corpus)**:

- **E-1 (D1 remote day)**: 天安门 ends 08:40 → depart directly for 慕田峪 (no unrequested filler before the remote leg). Shuttle 09:30 from 前门北口 → arrive ≈11:08 → lunch at the site 11:08-12:08 (先午餐后游览 decision) → visit 12:08-15:08 → return shuttle 15:30/16:30 → city ≈17:00/18:00 → dinner. Lunch must never be a hard gate before the remote departure; card times must equal leg times.
- **E-2 (coverage over fill)**: while any required must is untimed/unplaced, no unrequested filler may be inserted; existing unrequested fillers yield their slots to a seatable must (梵高星空艺术馆 must not hold D2 15:30-17:00 while 颐和园 has no time).
- **E-3 (no silent drop)**: 颐和园 either appears with concrete times or lands in `unplaced` with a plain-language disclosure (reason + how to add back). An untimed requested card in `days` is a contract violation.
- **E-4 (feasibility honesty)**: 颐和园 300 min + 故宫 120 + 天坛 150 in one day is near-infeasible in winter hours (故宫 last entry 15:30, closes 16:30; 颐和园 last entry 18:00). If the engine cannot seat all five musts, it must say exactly why (certificate), not silently drop one. A feasible shape exists if durations are tiered (e.g. 故宫 08:30-10:30 → 颐和园 11:00-16:00 → 天坛 16:50-19:20, 天坛 open to 22:00) — the engine should find such shapes or disclose precisely.

## 6. What this document feeds

- `cpsat_design_functions_2026-11-17.md`: every domain above maps to design functions (coverage matrix), every bug above maps to a design mechanism (bug→design traceability), and §5 becomes golden-corpus scenario **G-01**.
