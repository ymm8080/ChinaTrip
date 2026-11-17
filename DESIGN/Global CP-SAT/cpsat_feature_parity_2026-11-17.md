# 功能对照清单：现行系统 → 全程级 CP-SAT（2026-11-17）

**目的**：全程级模型（见 cpsat_trip_level_adr_2026-11-17.md）必须**等价覆盖现行全部用户可见功能**——本清单是 P3 切流的验收契约，不是设计文档。P1/P2 期间现行链路继续承载全部功能（旁路零风险）；P3 切流的门槛=本清单逐项打勾，任何「现在有、模型无」条目=切流阻塞项，回 P1 补核。

**规模盘点（2026-11-17 实测）**：`agent/plan.py` 模块级函数 400+ / 类方法 170+（~35k 行）；`itinerary/` 14 模块（solver/scoring/rules/legs/fares/geo/pipeline/coverage/request_coverage/best_visit/edit_distance/item_ids/visa_check/models）；`api/plan.py` 20 端点；`tests/` 150+ 文件。清单按用户可见能力分 14 域，函数名为证据锚点。

**归宿判级**：
- 【硬约束】→ 模型硬约束（违反=不可行，走松弛阶梯+证书）
- 【目标】→ 字典序目标/软约束
- 【输入】→ 模型外输入准备（候选池/属性/矩阵/预报），模型之前完成
- 【模型外】→ 不进模型：出站闸验收线/响应装配/API/交互/叙述
- 【退役】→ 手搓执行器退役，**语义进模型**（约束或 hint 重解）
- 【工程】→ 工程保证不变（确定性/并发/预算/持久化）

---

## 1. 意图理解与请求绑定（全部【输入】：LLM/正则 → request model）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 中英文日期/天数/出发时刻 | `_parse_text_start_date`/`_parse_days`/`_parse_text_day_start`/`_count_text_dates`/`_weekday_hits`；LLM `trip_facts_from_llm`（`_norm_city`/`_parse_hm` 校验，坏字段静默丢） | 输入 | test_comment_understanding, test_comment_intake_gate, test_city_days |
| 城市推断与歧义闸 | `_match_city_token`、poi_names `name_city_spread`/`latin_typo_prefix`/`latin_typo_near`、`_infer_city_from_site_text`（唯一命中直用，多城才问） | 输入 | test_typo_place_fuzzy, test_poi_city, test_city_fallback |
| 简报挖点+确认卡 | `_trip_brief`/`_parse_site_answer`/`_site_confirm_question`/`_brief_bare_place`/`_negated_brief_sites`；ZHUJIAZUI 类模糊候选「按拼写近似列出」确认卡 | 输入（交互） | test_brief_text_input, test_brief_avoid_sites, test_llm_interactive |
| 心愿/必去绑定 | `_wish_bind_candidate`/`commit_wish_drafts`/`materialize_wish_rows`/`_merge_must_visits`/`_coerce_wishes`/wish_fast 内核兜底 | 输入（→requested 字面量） | test_wish_bind, test_wish_fast_place, test_wish_draft_lifecycle, test_block_family_bind, test_wish_row_city_gate |
| preferences 归一 | `_norm_pref_text`/`_preference_tokens`/`_pref_category_hit`/`_is_preference_meta` | 输入 | test_pref_split, test_site_rating_preference, test_price_band |

## 2. 选点与候选池

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 资格闸（地址壳/银行/无坐标） | `_pool_worthy`/`_cand_is_bank_branch`/`_name_is_addr_shell` | 输入（池过滤） | test_bank_poi_gate, test_plan_candidates_require_location |
| 去重语义族（~30 判定） | `_same_site`/`_contained_twin_pair`/`_museum_umbrella_dup`/`_umbrella_cand_dup`/`_tower_pair_group`/`_palace_park_group`/`_substitute_group`/`_sibling_dup`/`_heritage_dup`/`_relic_park_dup`/`_composite_dup`/`_town_dup`/`_show_dup`/`_name_dup`/`_dup_blocks_item`/`_drop_duplicate_sites`/`_dedupe_visit_keepers` | 输入（选点侧）；审计侧镜像=request_coverage `_twin_cover`（模型外） | test_dup_pairs_sweep, test_named_kin, test_poi_merge, test_plan_dedupe_gate |
| 多样性 | `_cand_diversity_group`/`_cap_sights_per_day`/`_trim_optional_sights_on_heavy_days` | 目标（多样性项）+约束（每日上限） | test_category_diversity, test_type_diversity_selection, test_day_mix, test_morning_one_site, test_sibling_one_site |
| 质量排序（类别精确>距离>时长>评分 拍板） | `_cand_quality`/`_source_tier`/`_site_rank`/`_cand_rating_count`/`_cand_is_curated` | 目标（偏好评分项） | test_source_tier, test_poi_tag_selector, test_site_rating_preference |
| 确定性选择 | `_deterministic_selection`/`_placeholder_selection` | 目标+工程（同输入同输出） | test_algo_v0, test_score_regression, test_perturbation_robustness |

## 3. 分天结构（【硬约束】+【目标】）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 必去族定天 | `_must_visit_families`/`_assign_must_family_days`（fam score/pick）/`_must_day_load`/`_day_is_weekend`/`_family_is_outdoor`/`_family_is_remote`/`_must_weather_day_penalty` | 目标①（必去覆盖，重要度加权）+约束（族同天） | test_must_family_arrangement |
| 远郊分离/独占日 | `_mark_remote_visits`/`_is_remote_daytrip`/`_needs_own_day`/`_separate_remote_must_days`/`_is_full_day_item`/`_enforce_full_day` | 硬约束（日级聚合：远郊簇点独占日） | test_remote_must_day, test_remote_morning, test_geo_cluster |
| 按重要度钉时 | `_pin_musts_by_importance`/`_must_rank_key`/`_must_day_order`/`_must_anchor` | 硬约束（pin）+目标（重要度序） | test_must_family_arrangement, test_head_slot_rule |
| 房间清扫/跨天救援 | `_must_visit_room_sweep`/`_seat_unplaced_musts`/`_must_visit_crossday_rescue` | 退役（模型保证必去有可行窗，不可行→证书） | test_plan_agent |
| 城簇/多城分段 | `_city_day_ranges`/`_geo_cluster_day`/`city_days_trial`/`_day_hosts_city`/`_enforce_day_zones`/`_day_purity_sweep` | 硬约束（城-天绑定，同日同城） | test_city_days, test_city_cluster_same_day, test_cluster_first_days |
| 端点日（到达轻量/离城早收） | `_day_is_arrival`/`_day_is_return_home`/`_day_has_departure`/`_recruit_arrival_light`/`_endpoint_day_light_sweep`/solver `_leaving_morning_cap` | 硬约束（端点窗+轻量面），端点仅由定时腿触发 | test_arrival_day_fill, test_arrival_day_light, test_arrival_day_no_big, test_return_day_citywalk, test_return_day_light, test_return_day_urban_only, test_leaving_day_morning |
| 无交通信息=全天（拍板） | 无腿不端点化（`_placeholder_leg` 撤腿逻辑，438bcfa） | 硬约束（到达/返城日=带定时腿才成立） | test_intake_times + 真机 |
| 行前卡班次吸收 | `_apply_intake_times`（填班次钉腿/不填撤腿） | 输入+硬约束 | test_intake_times |
| 重开保位（reopen 已排 pin/must=硬锚） | reopen 五守卫（挪天跳过/远郊双守卫/清空跳过/探针加窗/让位 victims=[]） | 硬约束（条件 pin）+上一版解作 hint | test_reopen_preserve_pinned |

## 4. 日内排时与入场闸（【硬约束】核心）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| CP-SAT 单日排期 | solver `solve_day`（区间变量/开放窗/NoOverlap/pin/`_add_travel_objective`/`_add_makespan_objective`/3s 预算） | 被全程级模型取代（同一 OR-Tools 栈） | test_solver, test_timing_engine |
| 插入式排时 | `insertion_schedule_day`/`_candidate_starts` | P4 编辑热启动（hint 重解）吸收 | test_insertion_scheduler |
| 白天入场闸 16:30/大点 15:30 | solver `generic_entry_cap`/`_cand_entry_cap`/`_entry_cap_feasible` | 硬约束 | test_entry_cap_gate, test_entry_gate_readgate |
| 晚闸口径 v2（封闭景点吃闸；M50/武康路类开放形态豁免；SHOW/夜游/夜市豁免；塔类不豁免） | solver `_hours_open_form`/`_hours_evening_only`；plan `_evict_evening_gate_breachers`/`enforce_entry_gate`（出站闸保留为验收线） | 硬约束（豁免面=库属性输入）；出站闸=模型外验收线 | test_evening_gate_outbound, test_theme_block_evening |
| best_visit_time 库值直传（禁启发式拍板） | `_sched_best_visit`/best_visit.py（apply_rules 已删） | 输入（偏好窗属性） | test_best_visit, test_backfill_best_visit |
| 贴锚/探针放置 | `_place_with_flex`/`_probe_visit_slot`/`_shrink_band`/`_flex_allowed` | 退役（模型自放+pin） | test_flex_place |
| 顺延链/兜底顺序 | `_ripple_after_duration`/`_fallback_sequence_times`/`_clamp_chain_gaps` | 退役（hint 重解；降级披露归零） | test_plan_transfers, test_time_slot_integrity |
| 头档/晨卡规则 | `_is_head_candidate`/`_head_pick`/`_head_hotel_anchor`/`_morning_head_displacement` | 目标+约束（晨锚） | test_head_slot_rule, test_morning_fill |
| 服务窗/用户 stated 时刻守卫 | `_service_window_bounds`/`_pin_service_windows`/`_guard_llm_times`/`_user_stated_times` | 硬约束 | test_flag_schedule, test_llm_time_guard, test_soft_time_gate |
| 闭馆日/季节窗 | `_closed_weekdays`/`_weekday_hits`/hours 季节解析 | 硬约束（窗=∅ 不可排） | test_hours_seasonal_parse, test_ctrip_hours |

## 5. 餐饮体系（【硬约束】餐锚 +【模型外】卡装配）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 午/晚占位与餐卡 | `_lunch_placeholder`/`_dinner_placeholder`/`_meal_anchor`/`_plan_lunch_slot`/`_ensure_meal_cards`/`_drop_surplus_auto_meals` | 硬约束（餐锚窗）+装配（卡生成在解后） | test_meal_cards, test_meal_card_generality, test_meal_periods, test_soft_meal_pins |
| 真实餐厅绑定/嵌套 | `_bind_real_food_to_cards`/`_place_real_food_on_day`/`_retime_real_food_cards`/`_real_food_blockers`/`_food_slot_score`/`_make_room_for_meal`/`_nested_block_food`/`_meal_nesting_host`/`_reanchor_meal_to_host` | 硬约束（同址嵌套/绑定不换）+目标（slot score） | test_restaurants, test_same_venue_fusion, test_banquet_nearby, test_entertainment_floor |
| 先午餐后游览（目的地日拍板） | `_lunch_before_destination_visit`（15km 闸+10:30 下限+回滚闸） | 退役（→约束：目的地日午餐先于游览） | test_lunch_first |
| 餐腿间隙/重锚 | `_open_meal_leg_gaps`/`_retime_meal_placeholders`/`_meal_card_back_to_default`/`_adopt_legacy_meal_anchors`/legs `resolve_meal_anchors` | 退役+装配 | test_meal_leg_gap, test_meal_cards |
| 宴会/演出餐 | `_reassign_banquet_days`/`_is_show_banquet_item`/`_day_has_dinner_show`/`_cand_is_show_banquet` | 约束+输入（属性） | test_family_merge_street, test_show_sessions |
| 宫殿餐位裁定 | palace meal slot 规则 | 硬约束（特殊窗） | test_palace_meal_slot_rulings |

## 6. 交通与接驳（【硬约束】转移/端点 +【输入】矩阵）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 城际腿与班次链 | TransferItem/`_first_intercity_transfer`/`_last_intercity_transfer`/`_reconcile_transfer_days`/`_apply_transfer_schedule`/`_leg_date_iso`/`_extract_transport_numbers`/`_detect_transfer_kind` | 硬约束（端点+班次缓冲链） | test_plan_transfers, test_itinerary_legs, test_transfer_dates, test_trains, test_flight_service, test_transfer_city_gate |
| 占位腿/撤腿 | `_placeholder_leg`/`_drop_placeholder_legs_conflicting`/`_relax_intake_day` | 硬约束（填班次才钉/不填=全天拍板） | test_intake_times, test_fallback_legs |
| 接驳档案（access/board/票价） | access_services/`_access_profiles`/`_replay_measured_legs` | 输入（转移弧权） | test_access_services, test_leg_fares, test_qunar_duration |
| 腿间隙愈合 | leg_gap_heal/`heal_meal_cards` | 退役（模型保证无隙）+验收线保留 | test_leg_gap_heal |
| 回城专线卡 | return card 体系（时间/日） | 硬约束（离城腿）+装配 | test_return_card, test_return_card_time |
| 通勤估计/跨江 | `_travel_matrix`/`_leg_windows`/`_taxi_minutes_to`/`_center_taxi_minutes`/`_cross_river_penalty` | 输入（代价矩阵） | test_route_direction, test_amap |
| 交通模式/班次/订票链接 API | /transfers/mode、/number、/booking-links 端点 | 模型外（API） | test_plan_api |

## 7. 天气（【输入】+条件【目标】）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 预报×室内外属性 | `_rain_map`（weather_reports）×库 indoor/rain_ok（backfill_indoor_rain） | 输入（POI×天条件） | test_weather, test_backfill_indoor_summary |
| 雨日重排/降权 | `_rain_rebalance_days`/`rain_rebalance_days`/`_rain_exposed`/`_rain_heavy`/`_rain_light`/`_MUST_RAIN_OUTDOOR_PENALTY`/`_MUST_RAIN_INDOOR_PENALTY` | 条件目标（雨日户外降权/禁排）；预报变更=换输入重解 | test_rain_rebalance, test_rain_swap_hard, test_rain_city_first, test_rain_preference, test_rain_unmarked_sites |
| rain_outdoor 披露 | 「雨日露天」披露（14757 起） | 模型外（披露，由约束事实生成） | test_rain_rebalance |

## 8. 地理与清退（【硬约束】+【目标】+审计【模型外】）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 距离亲和闸（5km/25km 市区圈） | `_near_day_city_anchor`/`_day_city_anchor_pt`/`_too_close_to_plan`/`_in_park_of_existing` | 目标③（总车程最小化）+约束 | test_geo_invariants, test_geo_cluster |
| 第三片区清退 | `_evict_third_cluster_extras` | 硬约束（不贴簇不出圈=不可排；不可行→证书披露） | test_leftover_fill |
| 远郊日专属性 | `_day_already_remote`/`_is_remote_point`/`_urban_medoid` | 硬约束（日级聚合） | test_remote_must_day |
| 邻近顶替审计（必去被排成邻近另一景点必披露） | request_coverage `_twin_cover`/`_contained_twin_pair` | 模型外（审计验收线） | test_coverage_audit, test_plan_contract, test_poi_alternatives |
| 城市侧一致性 | `_city_side_ok`/`_city_side` | 硬约束（同日同侧） | test_plan_transfers |

## 9. 空档补点/备选/untimed 治理

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 空档补点 | pipeline `fill_leftover_gaps`/`_fill_leftover_with_diverse_sights`/`_bench_candidates_from_library`/`_day_opening_hole`/`_day_fill_floor` | 目标（填充偏好分）——模型内补点 | test_leftover_fill, test_morning_fill |
| 备选池/chips 配对 | attach_plan_alternatives（0.3km 备选配对）/poi_alternatives/insert-alt 端点 | 模型外（响应装配） | test_poi_alternatives, test_plan_api, test_offer_cards |
| 让位梯 | `_yield_for_premium`/`_must_yield_ok`/`_visit_keep_rank`/`_rehome_or_drop_displaced` | 退役（→字典序目标自动仲裁） | test_alt_insert, test_arrival_premium_rescue |
| 全局重排 | `_global_resched`/`_rebalance_days`/`_reanchor_nights_hook`/`_anchor_chain_pass`/`_apply_brief_sequence` | 退役（→hint 重解） | test_global_resched, test_global_rebalance |
| untimed 治理 | `_has_untimed_visits`/`_drop_untimed_visits`/`_rehome_untimed_visits`/`_untimed_promises_on`/`_finalize_untimed_visits`/untimed final sweep/`_untimed_response_strip` | 退役（模型保证解内全带时刻）；response strip 保留装配 | test_untimed_final_sweep, test_untimed_response_strip, test_wish_untimed_not_scheduled |
| show 让窗清退 | `_evict_shows_for_windowed_visits`/`_evict_shows_for_windowed_stage`/`_drop_sessionless_shows` | 硬约束冲突仲裁（证书化披露） | test_show_sessions |
| 顺路点 | `_panda_waypoint_pass` | 目标（顺路收益） | test_panda_waypoint |

## 10. 编辑与会话生命周期（【模型外】API + hint 热启动）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 20 个 API 端点 | save/from-itinerary/GET/start/message/sites-confirm/images/pin/delete/move/retime/duration/departure/transfers(mode·number·booking-links)/replace/insert-alt/set-hotel | 模型外（API 面不变，入口内部换引擎） | test_plan_api, test_itineraries_api |
| 编辑语义（挪/改时/删/换） | `move_item`/`retime_item`/`set_item_duration`/`reflow_after_delete`/`_apply_structural`/`_is_structural`/`_coerce_diffs` | P4：上一版解作 hint 热启动重解 | test_mutation_pipeline, test_trip_changes |
| pin 生命周期 | `_release_confirmed_pins`/`_drop_unconfirmed_pin_diffs`/pin 端点 | 硬约束（条件 pin） | test_plan_api, test_reopen_preserve_pinned |
| 三拍确认契约（确定性高不问/不符才问/多可能列选/有瑕疵先点出） | `_EDIT_SYSTEM_PROMPT` 三拍四条 | 模型外（交互纪律） | test_llm_interactive |
| 会话持久化/多回合幂等 | state_persist（WAL）/pg_state 读穿透/出站闸幂等 | 工程+模型外 | test_state_persist, test_state_readthrough, test_pg_state, test_item_id_uniqueness |

## 11. 审计与披露（P0 防御纵深——模型化后**保留**为验收线）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 必去三分律 | request_coverage `missing_must_visits`/`ensure_must_disclosure`（save 前读闸 `_audit_must_coverage`） | 模型外验收线（unplaced_var 上线后双保险） | test_coverage_audit, test_plan_contract |
| 双在场清脏 | request_coverage `dedupe_unplaced_against_scheduled` | 模型外验收线 | test_coverage_audit, test_plan_contract |
| 入场闸读闸 | `enforce_entry_gate`（GET/save 前读闸+响应兜底） | 模型外验收线 | test_entry_gate_readgate |
| 「求解器未收敛」降级披露 | `_solver_degraded_assumption` | 退役（P3 验收线=归零，证书化披露替代） | test_plan_agent |
| 双语披露 | `_lang_directive`/`_with_lang`/cards lang 全链 | 模型外（叙述） | test_cards_lang_en, test_itin_lang_en, test_plan_lang_en, test_artifacts_lang_en, test_h5_i18n |
| 预订提示 | `_reservation_hint`/`_reservation_csv_row` | 模型外（装配） | test_reservation_seeds_en, test_refresh_reservation_rules |

## 12. 演出/夜游/晚档特则

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 场次窗 | solver `show_session_starts`/`effective_show_sessions`/`is_sessionless_show`/`_show_off_season` | 输入（场次=硬约束窗） | test_show_sessions, test_show_per_day |
| 每日一场/距离 | `_enforce_show_per_day`/`_day_show_taken`/`_min_show_dist_km` | 约束 | test_show_per_day, test_endpoint_show_distance |
| 演出晚档偏好 | show late preference 规则 | 目标（晚偏好项） | test_show_late_preference |
| 夜游豁免面（游船/夜市/不夜城） | 库 evening 属性（manual 回标 64 行）+`_hours_evening_only` | 输入+硬约束豁免 | test_evening_gate_outbound |

## 13. 酒店/住宿/预订

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 酒店锚/夜锚 | `_reanchor_nights_hook`/`_head_hotel_anchor`/set-hotel 端点 | 约束（住宿锚）+API | test_hotel_stays, test_api_hotels, test_tag_star_hotels |
| 预订/出行人/签证 | bookings/travelers/visa_check 模块 | 模型外（服务面不变） | test_bookings_service, test_travelers_api, test_visa_check |

## 14. 运行时契约（【工程】）

| 功能 | 现行实现 | 归宿 | 验收锚点 |
|---|---|---|---|
| 确定性 | `_deterministic_selection`；目标架构 num_workers=1+固定种子 | 工程（同输入同输出=红灯线） | test_perturbation_robustness, test_score_regression |
| 并发不冻循环 | to_thread 包裹（agent 8 处+api 20 处） | 工程（新引擎同样必须 to_thread 化） | test_plan_api + workspace/probe_concurrency.py |
| 求解预算 | 3s 预算不变 | 工程 | test_solver |
| 出站闸幂等/save 前审计 | `_audit_must_coverage`+读闸（save 前跑，fd29906/6dc89c3） | 模型外验收线 | test_coverage_audit, test_plan_contract, test_entry_gate_readgate |
| 持久化健壮 | WAL/busy_timeout（state_persist/task_queue/travelers/payments） | 工程 | test_sqlite_pragmas, test_task_queue |

---

## P3 切流硬门槛（对照流程）

1. 本清单 14 域逐项打勾：每项确认「现行实现」的语义已映射到 标注归宿 的位置（约束/目标/输入/模型外/退役替代）。
2. 黄金行程语料按域聚类扩场景（真实事故：慕田峪午饭/塔类晚闸/ZHUJIAZUI/重开保位/无交通全天/雨日/必去三病灶），影子对比新旧输出逐场景验收。
3. 「求解器未收敛」披露归零；CP-SAT assumptions 证书覆盖原降级场景的披露。
4. 现行关键测试集（上表验收锚点）在影子 harness 下全绿；test_plan_contract + test_coverage_audit 双闸继续全绿。
5. 任何「现在有、模型无」条目=切流阻塞项，回 P1 补核；不满足则停留在 P2 影子（现行链路零风险）。
6. **覆盖审计常设规则（2026-11-17 审计 A6 补）**：任何引擎函数未收录进 `cpsat_coverage_audit_2026-11-17.md` 的函数级映射=切流阻塞项，先补映射再评审。
