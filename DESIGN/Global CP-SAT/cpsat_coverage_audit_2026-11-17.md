# Coverage Audit — every current function → design element (2026-11-17)

**Question answered**: does the global CP-SAT design cover *all* current functionality and rules? This audit answers it mechanically instead of by assertion.

## Method and totals

- Scanned `app/services/agent/plan.py` + 12 `itinerary/` modules (solver/scoring/rules/legs/fares/geo/pipeline/coverage/request_coverage/item_ids/edit_distance/models) for `def` at module or class level: **647 functions**.
- **235** are explicitly named in the design-package documents then existing (ADR / AS-IS / design functions / parity matrix; the implementation-phases plan and this audit were added later and belong to the same package — audit A7).
- The remaining **412** were classified by hand into the rule families below (**367 functions**) plus **45 utility/helper functions** (string/time/coordinate formatting, tiny predicates, local closures, store plumbing) whose behaviour is subsumed by the module they serve — they carry no user-visible rule of their own.
- Result: **every rule-bearing function maps to a design element** (constraint C-xx, objective F-23, input F-10…F-15, assembly F-30…F-34, gate F-40, or a retired executor whose semantics move into the model).

## Rule-family mapping (the 412 previously-uncited functions)

| Current rule family | Members | Design element |
|---|---|---|
| iron-rule validators (rules.py) | 20 | F-40 acceptance invariants + C-01/03/05/06/07/08/09 |
| travel/access/fare math | 20 | F-11 travel matrix + F-14 access intervals (input) |
| leg/return-card assembly | 28 | F-30 materialise plan (assembly entry points) |
| edit pipeline & edit-scope | 13 | F-50 edit re-solve + C-04 pins |
| global-resequence scoring (retired) | 10 | retired executor → F-23 objectives + F-50 hint re-solve |
| coverage.py premium/rain | 2 | F-13 weather conditioning + F-40 disclosure |
| weather family | 4 | F-13 weather conditioning |
| hours inputs | 8 | F-12 hours windows / entry cap (input) |
| fixed sessions & day-start anchors | 5 | C-04 user/fixed-session pins + F-01 day1_start |
| intent & question policy | 50 | F-01 intent + F-02 binding (three-trigger contract) |
| dedupe/grouping extras | 40 | F-10 candidate pool (dedupe & grouping semantics) |
| block-family & umbrella binding | 7 | C-12 family/day binding + F-10 grouping |
| cluster cohesion & reunite (retired) | 52 | retired executors → C-06/C-07/C-12 cluster constraints |
| endpoint-day classifiers | 8 | C-05 endpoint-day light-content rules |
| fill & morning passes | 7 | F-23 fill reward + C-14 coverage-before-fill |
| untimed/yield/rescue (retired) | 7 | retired executors → F-20 unplaced_var + F-26 certificate |
| meal slot/binding/nesting | 29 | C-09 meal anchors + F-31 meal assembly |
| shows/night & type classifiers | 19 | C-11 show sessions + F-12 attribute inputs |
| solver cost terms & internals (absorbed) | 22 | F-23 objectives (cost terms) / absorbed by F-24 |
| geo/id/store engineering | 11 | F-34 session & trip-center sync + F-30/F-42 engineering |
| disclosure text helpers | 5 | F-33 disclosure renderer |

## Full member list per family

### iron-rule validators (rules.py) → F-40 acceptance invariants + C-01/03/05/06/07/08/09

`_check_base_city_jumps`, `_check_delivery_gates`, `_check_opening_hours`, `_check_pace`, `_check_time_conflicts`, `_check_transfer_buffer`, `_check_transfer_sequence`, `_check_visit_cities`, `validate_plan`, `current_violations`, `travel_gap_needed`, `travel_gap_violations`, `tight_cluster_split_violations`, `_report`, `_scope_key`, `_apply_geo_invariants`, `_scheduled_entries`, `_scheduled_names`, `_name_matches`, `_norm`

### travel/access/fare math → F-11 travel matrix + F-14 access intervals (input)

`access_breakdown`, `access_chain_minutes`, `_return_breakdown`, `_fastest_return_ride`, `_fastest_ride`, `taxi_leg_min`, `_taxi`, `_taxi_to`, `haversine_km`, `access_fare_estimate`, `estimate_taxi_fare`, `_city_key`, `_eff_end_minutes`, `_hhmm_minutes`, `_fmt`, `_after_transfer_buffer`, `_fixed_transfer_window`, `_is_incity_transfer`, `_leg_minutes_estimate`, `_nearby_poi_rows`

### leg/return-card assembly → F-30 materialise plan (assembly entry points)

`annotate_legs`, `attach_return_cards`, `_attach_tail_return`, `_attach_plain_tail_return`, `_attach_leg_returns`, `_lift_return_over_placeholders`, `_trim_site_for_return`, `_next_start_after`, `_service_window`, `_gate_item_links`, `_verified_links`, `_options_detail`, `_access_detail`, `_access_return_detail`, `_access_profile`, `_return_card_name`, `_return_hint_text`, `_url`, `_sane`, `_trim_band`, `_clear_leg`, `leg_pairs`, `_city_center`, `_day_city_anchor`, `_clock`, `_clock_minutes`, `_parse_clock_text`, `_point`

### edit pipeline & edit-scope → F-50 edit re-solve + C-04 pins

`apply_diffs`, `mutate`, `summarize_changes`, `_recompute_end_times`, `_find_item`, `_item_name`, `set_access_departure`, `validate_change_scope`, `_coerce_v0_items`, `_coerce_visit`, `_edit_system_prompt`, `morning_departure_anchor`, `_is_morning_hotel`

### global-resequence scoring (retired) → retired executor → F-23 objectives + F-50 hint re-solve

`summarize`, `weighted_total`, `_day_orders`, `_item_key`, `_norm_name`, `_start_minutes`, `score_payload`, `ok`, `_near_mate_km`, `_minutes`

### coverage.py premium/rain → F-13 weather conditioning + F-40 disclosure

`premium_coverage_gaps`, `rain_swap_advice`

### weather family → F-13 weather conditioning

`_rain_exposure_label`, `_rain_unmarked`, `_site_fit_problem`, `_enforce_site_day_fit`

### hours inputs → F-12 hours windows / entry cap (input)

`_hours_db_pass`, `_plan_poi_hours`, `_hours_from_visit`, `_merged_hours_segments`, `_hours_hit_mismatch`, `_has_usable_time_info`, `_family_best_visit`, `_fits_after`

### fixed sessions & day-start anchors → C-04 user/fixed-session pins + F-01 day1_start

`_apply_flag_schedule`, `_flag_pin_reachable`, `_apply_comment_day_start`, `_day_fixed_windows`, `_fixed_block_conflict`

### intent & question policy → F-01 intent + F-02 binding (three-trigger contract)

`clarify_questions`, `wish_city_question`, `_resto_question`, `_type_ask_hit`, `_pref_question`, `_site_keep_all`, `_parse_resto_answer`, `_match_site_names`, `_record_link_sites`, `new_trip_brief`, `_absorb_days_cities`, `_resolve_brief_cities`, `_brief_day_value`, `_brief_is_route_declaration`, `_brief_standin`, `_is_new_trip_request`, `_user_corpus`, `_wish_grounded_in_user_text`, `_significant_units`, `_wish_draft_session`, `_backfill_wish_city`, `_finalize_wish_cities`, `_wish_city_hint`, `_wish_core`, `_wish_pure_core`, `_same_wish_name`, `_wish_when_text`, `_wish_row_plan_fields`, `_wish_candidate_rank`, `_resto_search_enabled`, `_far_foods`, `_food_visit`, `_search_anchor`, `_search_chain`, `_parse_cities`, `_normalize_city`, `_norm_site_name`, `_text_site_kind`, `_longest_common_span`, `_cn_number`, `_cn_hour`, `_window_of`, `_pace_assumption`, `_schedule_text`, `_brief_typo_rival_row`, `_is_preference_style_option`, `_is_service_meta_wish`, `_is_trip_brief_wish`, `_category_label_tokens`, `_category_search_keyword`

### dedupe/grouping extras → F-10 candidate pool (dedupe & grouping semantics)

`_cand_twin`, `_named_kin`, `_kin_core_name`, `_content_core`, `_content_dup`, `_sibling_core`, `_sibling_pair_eligible`, `_site_dup`, `_planned_duplicate_visit`, `dedupe_plan_visits`, `_same_visit`, `_museum_cand`, `_museum_card`, `_museum_core`, `_generic_substitute_group`, `_substitute_canon_rank`, `_substitute_dup`, `_unesco_serial_only`, `_same_category_full`, `_street_banquet_split`, `_umbrella_specs_bundle`, `_bundle_umbrella_spec_days`, `_day_umbrella_pairs`, `_combo_day_interiors`, `_visit_item_cand_view`, `_cand_tags`, `_is_intl_candidate`, `_plain_street_cand`, `_theme_block_cand`, `_night_cand`, `_show_bucket`, `_show_night_only`, `_cand_is_show`, `_is_experience_cand`, `_is_experience_candidate`, `_cand_at_fallback`, `_backfill_eligible`, `_cand_endpoint_content`, `_endpoint_content_visit`, `_itin_cap_bucket`

### block-family & umbrella binding → C-12 family/day binding + F-10 grouping

`_bind_block_family`, `_block_family_host`, `_block_family_guest`, `_block_family_window`, `_family_has_strong_constraint`, `fam_duration`, `fam_pts`

### cluster cohesion & reunite (retired) → retired executors → C-06/C-07/C-12 cluster constraints

`_created_wedge_reunite`, `_evict_wedge_strays`, `_relocate_stranger`, `_purify_cluster_days`, `_reunite_tight_kin`, `_reunite_show_with_venue`, `_near_cluster_mate_on`, `_tight_cluster_mate_on`, `_venue_anchor_on`, `_dominant_kin`, `_dom_core_ids`, `_anchor_rank`, `_compact_family_day`, `_host_day_for_visit`, `_heavy_rehome_visit`, `_arrival_far_skip`, `_far_from_anchor`, `_far_conflict_items`, `_best_anchor_km`, `_plan_center`, `_remote_km_of`, `_day_is_edge`, `_bcity`, `_city`, `_same_city`, `_day_place_city`, `_meal_city_at`, `_zone`, `_components`, `_countable`, `_countable_on`, `_has_xy`, `_vxy`, `_pt`, `_proj`, `_travel`, `_load`, `_families`, `_fam_intol`, `_intol`, `_swappable`, `_try_swap`, `_has_transfer`, `_drop_untimed_from_day`, `_street_block_mate`, `_street_block_mate_km`, `_street_like_visit`, `_street_visit`, `_street`, `_near_mate_on`, `area_labels`, `cluster_days`

### endpoint-day classifiers → C-05 endpoint-day light-content rules

`_arrival_simple_visit`, `_arrival_sight_visit`, `_arrival_heavy_visit`, `_ep_stay_violation`, `_transfer_day_sweep`, `_pick_arrival_nearby`, `heal_arrival_light`, `_intake_target_day`

### fill & morning passes → F-23 fill reward + C-14 coverage-before-fill

`_morning_fill`, `_morning_borrow`, `_clamp_to_morning_floor`, `_borrow_rollback`, `_morning_occupied`, `_first_free_gap`, `_day_free_minutes`

### untimed/yield/rescue (retired) → retired executors → F-20 unplaced_var + F-26 certificate

`_rescue_premium_stranded`, `_premium_full`, `_stack_uncashable`, `_jointly_cashable_with`, `_untimed_protected_reason`, `_untimed_musts`, `drop_dangling_visits`

### meal slot/binding/nesting → C-09 meal anchors + F-31 meal assembly

`_meal_slot_plan`, `_meal_slot_time_ok`, `_meal_slot_default_start`, `_meal_card_start_candidates`, `_meal_chain_yieldable`, `_meal_card_binding`, `_meal_card_label`, `_meal_card_legs_stale`, `_day_has_meal_card`, `_day_meal_card_present`, `_day_meal_card_taken`, `_meal_card_slot`, `_is_system_meal`, `_is_real_food`, `_place_late_dinner_card`, `_place_meal_card`, `_reconcile_meal_site_overlaps`, `_drop_stale_missing_meal_notes`, `_with_meal_bands`, `_same_venue_times`, `fusion_food_nested`, `is_same_venue_food_pair`, `_nested_food_pair`, `_fusion_host_span`, `_day_has_show_banquet`, `_is_dinner_show_item`, `_evening_anchor_visit`, `_meal_gap_movable`, `is_show_banquet_item`

### shows/night & type classifiers → C-11 show sessions + F-12 attribute inputs

`_night_combo_pairs`, `_glue_evening_mate`, `_show_early_cost`, `_has_tba_session_mark`, `_is_show`, `_is_show_item`, `_is_show_v`, `_is_relax_item`, `_is_morning_site`, `_is_big_site`, `_is_light_sight`, `_is_theme_block`, `_is_citywalk`, `_is_remote_visit`, `_is_big_visit`, `_is_light_visit`, `_is_theme_block_visit`, `_is_citywalk_visit`, `_cand_is_big`

### solver cost terms & internals (absorbed) → F-23 objectives (cost terms) / absorbed by F-24

`_added_travel`, `_adjacent_big_ids`, `_afternoon_big_cost`, `_cw_afternoon_cost`, `_head_first_cost`, `_head_dist`, `_remote_late_cost`, `_attempt`, `_first_feasible`, `_fits`, `_try_insert`, `_dist`, `_hkey`, `_solve`, `_to_minutes`, `_to_time`, `_haversine_km`, `_norm_city_name`, `_priority_early_enabled`, `_rating_near_priority`, `_street_block_priority`, `_head_dist_km`

### geo/id/store engineering → F-34 session & trip-center sync + F-30/F-42 engineering

`ensure_unique_item_ids`, `heal_item_ids`, `alloc_item_id`, `_split_item_id`, `sync_trip_rows`, `_sync_wish_rows`, `_sync_planned_rows`, `sync_removals_to_trip_items`, `get_plan_session_store`, `live_itinerary_ids`, `heal_leg_gaps`

### disclosure text helpers → F-33 disclosure renderer

`_append_solve_degradation_notes`, `_dedupe_assumptions`, `_plan_digest`, `_item_line`, `_reservation_hint_from_row`

## Utilities (no user-visible rule of their own)

`__init__`, `_cand_xy`, `_coord`, `_entry_xy`, `_exempt`, `_find`, `_find_transfer_item`, `_fmt_hm`, `_free_day`, `_home_day`, `_is_unspecified`, `_item_end_minutes`, `_item_xy`, `_key`, `_km`, `_leg_point`, `_location_dict`, `_m`, `_meal`, `_mins`, `_minutes_of`, `_movable`, `_move`, `_norm_city_key`, `_other_musts`, `_parse_time`, `_pick`, `_rank`, `_rating`, `_rt`, `_shift_hm`, `_sights`, `_tier`, `_time_of`, `_unspecified`, `_untouchable`, `_visits`, `_weak_key`, `_window_gap_minutes`, `_xy`, `_xy_km`, `anchor_no`, `get`, `norm`, `probe`

## What this audit changed in the design

- `rules.py` iron-rule validators (`validate_plan`, `_check_*`, travel-gap validators) are now explicitly assigned to **F-40 acceptance invariants** (they run on any engine output, old or new).
- Leg/return-card assembly entry points (`annotate_legs`, `attach_return_cards`) are named in **F-30**.
- Fixed sessions from the flag schedule (`_apply_flag_schedule`), comment day-start (`_apply_comment_day_start`) and user-chosen shuttle departure (`set_access_departure`) are named in **C-04**.
- **F-34 session & trip-center sync** was added (`sync_trip_rows`, `_sync_wish_rows`, `_sync_planned_rows`, `sync_removals_to_trip_items`, `ensure_unique_item_ids`, store plumbing).
- `coverage.py` (`premium_coverage_gaps`, `rain_swap_advice`) assigned to F-13/F-40; question-policy functions (`clarify_questions`, `wish_city_question`, `_resto_question`, `_type_ask_hit`) assigned to F-01.

## Hard guarantee beyond this document

Coverage is not accepted on paper: P3 switch is blocked until the 14-domain parity checklist is checked item by item, the golden corpus (incident-derived scenarios incl. G-01) is green under shadow comparison, and the existing contract/audit suites stay green. Any genuine gap found hereafter is added to this appendix and to the parity checklist, and blocks the switch.
