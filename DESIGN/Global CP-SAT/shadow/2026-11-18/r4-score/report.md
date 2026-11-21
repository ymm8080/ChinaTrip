# Shadow diff report — corpus (P2-B)

_offline batch: legacy side = recorded runs (tests/golden/legacy/); model side = live double solve (F-41)_

generated 2026-11-18T18:38:07 · budget 3.0s · corpus dir `D:\CHINATRIP\CHINATRIP CODES\tests\golden`

## F-62 acceptance gates

| Gate | Value | Pass | Note |
|---|---|---|---|
| corpus_size | 13/12 | ✅ | corpus v2 ships 13 scenarios (P2-B families); M9 floor is 12 |
| violation_classes_zero_new | {'B-01': 0, 'B-02': 0, 'B-03a': 0, 'B-03c': 0, 'B-06': 0} | ✅ |  |
| convergence_rate_new | 1.0 | ✅ |  |
| determinism_rate | 1.0 | ✅ |  |
| not_worse_vs_recording | 13/13 recorded scenarios | ✅ |  |
| legacy_no_solution_disclosures | 0 | ✅ | recorded legacy baseline must itself be free of 「求解器未收敛」 for a clean comparison |
| plan_score_delta | 8/12 scored within −2% | ❌ | one scorer both engines (Q5 constants): replay scores the cascade plan, F-30 materialises + scores the model plan; unscored sides stay pending |
| parity_domains_14 | 14/14 | ✅ | all 14 domains covered |

**Verdict**: shadow-instrument+legacy-replay (P2-B) — pass 7 / fail 1 / pending 0

## g01

- model: status=OPTIMAL wall=807ms deterministic=True (unplaced=0, fill=1)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=1, B-02=2, B-03a=1, B-03c=1, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ❌ | ✅ | all 5 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ✅ | ✅ | all 5 cap-known cards start within cap |
| same_venue | ❌ | ⏳ | no meal cards in view (meal assembly F-31 lands in P1-F) |
| deterministic | ➖ | ✅ | two solves byte-identical (F-41) |

## g02_tower_late_gate

- model: status=OPTIMAL wall=12ms deterministic=True (unplaced=0, fill=1)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 1 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 2 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g03_third_cluster

- model: status=OPTIMAL wall=419ms deterministic=True (unplaced=0, fill=2)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 5 musts timed or disclosed-unplaced |
| sequence | ➖ | ➖ | day 1: '慕田峪长城' not on the day |
| no_unrequested_before | ➖ | ➖ | day 1: anchor '慕田峪长城' not on the day (coverage is requested_coverage's job) |
| no_entry_cap_breach | ➖ | ✅ | all 5 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g04_endpoint_transit

- model: status=OPTIMAL wall=200ms deterministic=True (unplaced=0, fill=1)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 5 musts timed or disclosed-unplaced |
| day_start_floor | ❌ | ✅ | first visit 天安门广场 starts 11:30 ≥ 11:30 (C-05 arrival floor) |
| day_end_ceiling | ❌ | ✅ | last visit 慕田峪长城 ends 16:08 ≤ 17:30 (C-05 departure buffer) |
| no_unrequested_before | ➖ | ➖ | day 1: anchor '慕田峪长城' not on the day (coverage is requested_coverage's job) |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g05_rain_rebalance

- model: status=OPTIMAL wall=167ms deterministic=True (unplaced=2, fill=2)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 5 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 4 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g06_reopen_pins

- model: status=OPTIMAL wall=180ms deterministic=True (unplaced=0, fill=2)
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

- model: status=OPTIMAL wall=948ms deterministic=True (unplaced=0, fill=1)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 5 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 5 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g08_remote_exclusive

- model: status=OPTIMAL wall=72ms deterministic=True (unplaced=0, fill=2)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 2 musts timed or disclosed-unplaced |
| remote_day_purity | ✅ | ✅ | day 2 holding remote '慕田峪长城' carries no unrequested visit |
| no_entry_cap_breach | ➖ | ✅ | all 4 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g09_duration_clamp

- model: status=OPTIMAL wall=35ms deterministic=True (unplaced=0, fill=1)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 1 musts timed or disclosed-unplaced |
| span_cap | ❌ | ✅ | '颐和园' span 240 min ≤ 240 |
| no_entry_cap_breach | ➖ | ✅ | all 2 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g10_city_coherence

- model: status=OPTIMAL wall=151ms deterministic=True (unplaced=0, fill=4)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 3 musts timed or disclosed-unplaced |
| city_coherence | ✅ | ✅ | all 2 city-known days are single-city |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g11_trip_scale

- model: status=OPTIMAL wall=1776ms deterministic=True (unplaced=0, fill=0)
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

- model: status=OPTIMAL wall=13ms deterministic=True (unplaced=1, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 2 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 1 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |

## g13_twin_content_dup

- model: status=OPTIMAL wall=17ms deterministic=True (unplaced=0, fill=2)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy (recorded): violations B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0, 未收敛 disclosures 0
- not-worse: True

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | ✅ | ✅ | all 1 musts timed or disclosed-unplaced |
| no_entry_cap_breach | ➖ | ✅ | all 2 cap-known cards start within cap |
| deterministic | ✅ | ✅ | two solves byte-identical (F-41) |
