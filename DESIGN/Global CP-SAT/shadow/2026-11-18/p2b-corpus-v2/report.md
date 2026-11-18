# Shadow diff report — corpus (P2-B)

_offline batch: legacy side = recorded runs (tests/golden/legacy/); model side = live double solve (F-41)_

generated 2026-11-18T08:39:29 · budget 3.0s · corpus dir `D:\CHINATRIP\CHINATRIP CODES\tests\golden`

_legacy replay_: {"written": [], "kept": ["g01", "g02_tower_late_gate", "g03_third_cluster", "g04_endpoint_transit", "g05_rain_rebalance", "g06_reopen_pins", "g07_name_variants", "g08_remote_exclusive", "g09_duration_clamp", "g10_city_coherence", "g11_trip_scale", "g12_closed_weekday", "g13_twin_content_dup"], "failed": []}

## F-62 acceptance gates

| Gate | Value | Pass | Note |
|---|---|---|---|
| corpus_size | 13/12 | ✅ | corpus v2 ships 13 scenarios (P2-B families); M9 floor is 12 |
| violation_classes_zero_new | {'B-01': 0, 'B-02': 0, 'B-03a': 0, 'B-03c': 0, 'B-06': 0} | ✅ |  |
| convergence_rate_new | 1.0 | ✅ |  |
| determinism_rate | 1.0 | ✅ |  |
| not_worse_vs_recording | 13/13 recorded scenarios | ✅ |  |
| legacy_no_solution_disclosures | 0 | ✅ | recorded legacy baseline must itself be free of 「求解器未收敛」 for a clean comparison |
| plan_score_delta | None | ⏳ | pending P1-D tiered objective + P1-F plan materialisation |
| parity_domains_14 | None | ⏳ | pending P1-F feature-parity checklist |

**Verdict**: shadow-instrument+legacy-replay (P2-B) — pass 6 / fail 0 / pending 2

## g01

- model: status=OPTIMAL wall=35ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=1, B-02=2, B-03a=1, B-03c=1, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ❌ | ✅ | all 5 musts timed or disclosed-unplaced |
| sequence | ✅ | ✅ | relative order holds: 天安门广场 → 慕田峪长城 |
| no_unrequested_before | ❌ | ✅ | no unrequested visit before '慕田峪长城' on day 1 |
| time_range | ➖ | ➖ | scenario sets no pin for '天安门广场' (timetable-fixed time only assertable with the pin) |
| same_venue | ❌ | ⏳ | no meal cards in view (meal assembly F-31 lands in P1-F) |
| card_leg_consistent | ❌ | ✅ | visit start == leg arrival (12:08) |
| time_range | ➖ | ➖ | scenario sets no pin for '天安门广场' (timetable-fixed time only assertable with the pin) |
| no_entry_cap_breach | ✅ | ✅ | all 5 cap-known cards start within cap |
| deterministic | ➖ | ✅ | two solves byte-identical (F-41) |

## g02_tower_late_gate

- model: status=OPTIMAL wall=3ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 1 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 1 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g03_third_cluster

- model: status=OPTIMAL wall=18ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 5 musts timed or disclosed-unplaced |
| sequence | ➖ | ✅ | relative order holds: 天安门广场 → 慕田峪长城 |
| no_unrequested_before | ➖ | ✅ | no unrequested visit before '慕田峪长城' on day 1 |
| no_entry_cap_breach | ➖ | ✅ | all 4 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g04_endpoint_transit

- model: status=OPTIMAL wall=21ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 5 musts timed or disclosed-unplaced |
| day_start_floor | ❌ | ✅ | first visit 慕田峪长城 starts 12:08 ≥ 11:30 (C-05 arrival floor) |
| day_end_ceiling | ❌ | ✅ | last visit 天安门广场 ends 14:40 ≤ 17:30 (C-05 departure buffer) |
| no_unrequested_before | ➖ | ✅ | no unrequested visit before '慕田峪长城' on day 1 |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g05_rain_rebalance

- model: status=OPTIMAL wall=25ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 5 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 5 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g06_reopen_pins

- model: status=OPTIMAL wall=13ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| time_range | ❌ | ✅ | 天安门广场 starts 07:10 within [07:00, 07:40] |
| time_range | ❌ | ✅ | 颐和园 starts 09:00 within [08:30, 09:59] |
| requested_coverage | ✅ | ✅ | all 5 musts timed or disclosed-unplaced |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g07_name_variants

- model: status=OPTIMAL wall=24ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 5 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 5 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g08_remote_exclusive

- model: status=OPTIMAL wall=6ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 2 musts timed or disclosed-unplaced |
| remote_day_purity | ✅ | ✅ | day 2 holding remote '慕田峪长城' carries no unrequested visit |
| no_entry_cap_breach | ➖ | ✅ | all 2 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g09_duration_clamp

- model: status=OPTIMAL wall=2ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 1 musts timed or disclosed-unplaced |
| span_cap | ❌ | ✅ | '颐和园' span 120 min ≤ 240 |
| no_entry_cap_breach | ➖ | ✅ | all 1 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g10_city_coherence

- model: status=OPTIMAL wall=20ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 3 musts timed or disclosed-unplaced |
| city_coherence | ✅ | ✅ | all 3 city-known days are single-city |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g11_trip_scale

- model: status=OPTIMAL wall=473ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 6 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 6 cap-known cards start within cap |
| city_coherence | ✅ | ✅ | all 5 city-known days are single-city |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g12_closed_weekday

- model: status=OPTIMAL wall=5ms deterministic=True (unplaced=1, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 2 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 1 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g13_twin_content_dup

- model: status=OPTIMAL wall=12ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 1 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 1 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

