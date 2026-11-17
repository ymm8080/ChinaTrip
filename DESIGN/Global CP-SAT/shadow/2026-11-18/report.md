# Shadow diff report — corpus v1 (P2-A)

_offline batch: legacy side = recorded runs (tests/golden/legacy/); model side = live double solve (F-41)_

generated 2026-11-18T06:59:43 · budget 3.0s · corpus dir `D:\CHINATRIP\CHINATRIP CODES\tests\golden`

## F-62 acceptance gates

| Gate | Value | Pass | Note |
|---|---|---|---|
| corpus_size | 4/12 | ❌ | corpus v1 ships 4; P2-B expands to ≥ 12 |
| violation_classes_zero_new | {'B-01': 0, 'B-02': 0, 'B-03a': 0, 'B-03c': 0, 'B-06': 0} | ✅ |  |
| convergence_rate_new | 1.0 | ✅ |  |
| determinism_rate | 1.0 | ✅ |  |
| not_worse_vs_recording | 1/1 recorded scenarios | ✅ |  |
| legacy_no_solution_disclosures | 0 | ✅ | recorded legacy baseline must itself be free of 「求解器未收敛」 for a clean comparison |
| plan_score_delta | None | ⏳ | pending P1-D tiered objective + P1-F plan materialisation |
| parity_domains_14 | None | ⏳ | pending P1-F feature-parity checklist |

**Verdict**: shadow-instrument (P2-A) — pass 5 / fail 1 / pending 2

## g01

- model: status=OPTIMAL wall=17ms deterministic=True (unplaced=0, fill=0)
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

- model: status=OPTIMAL wall=1ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy: no recording committed (P2-B regenerates)

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | — | ✅ | all 1 musts timed or disclosed-unplaced |
| no_entry_cap_breach | — | ✅ | all 1 cap-known cards start within cap |
| deterministic | — | ✅ | two solves byte-identical (F-41) |

## g03_third_cluster

- model: status=OPTIMAL wall=10ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy: no recording committed (P2-B regenerates)

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | — | ✅ | all 5 musts timed or disclosed-unplaced |
| sequence | — | ✅ | relative order holds: 天安门广场 → 慕田峪长城 |
| no_unrequested_before | — | ✅ | no unrequested visit before '慕田峪长城' on day 1 |
| no_entry_cap_breach | — | ✅ | all 4 cap-known cards start within cap |
| deterministic | — | ✅ | two solves byte-identical (F-41) |

## g04_endpoint_transit

- model: status=OPTIMAL wall=13ms deterministic=True (unplaced=0, fill=0)
- model violations: B-01=0, B-02=0, B-03a=0, B-03c=0, B-06=0
- legacy: no recording committed (P2-B regenerates)

| Assertion | Legacy | Model | Detail (model) |
|---|---|---|---|
| requested_coverage | — | ✅ | all 5 musts timed or disclosed-unplaced |
| day_start_floor | — | ✅ | first visit 慕田峪长城 starts 12:08 ≥ 11:30 (C-05 arrival floor) |
| day_end_ceiling | — | ✅ | last visit 天安门广场 ends 14:40 ≤ 17:30 (C-05 departure buffer) |
| no_unrequested_before | — | ✅ | no unrequested visit before '慕田峪长城' on day 1 |
| deterministic | — | ✅ | two solves byte-identical (F-41) |

