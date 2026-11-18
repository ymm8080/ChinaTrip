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
| **P1-D** | C-09 meal anchors, C-10 lunch-before-visit, C-11 shows, C-12 family/day, C-13 hotel anchors, **C-14 coverage-before-fill**, **C-15 remote-departure ban**, C-16 diversity caps + F-22 remote lunch + F-23 lexicographic objectives | `trip_solver/model/c09_c16.py`, `objectives.py` | **X** | 1–1.5 | G-01 D2: 梵高-type filler can never outrank 颐和园; remote lunch nests at site or post-visit (needs **Q4**) — **✅ 2026-11-18**: schema v2 + corpus 13 同步迁移；远郊晚饭 19:30 拍板落地；coverage 层 fill-free projection 保任 g11 Q3；`shadow/2026-11-18/p1d-unified/` gates 6过/0败/2挂（收敛/确定性/not-worse 全 1.0）；trip-solver 97 passed + 1 skipped |
| **P1-E** | F-24 budgeted solve (workers=1, fixed seed, hints), F-25 slack ladder, F-26 infeasibility certificates, F-41 determinism guard | `trip_solver/model/{solve,slack,certificate}.py` + `disclosure_templates.json` | **M–X** | 1 | same snapshot → byte-identical plan; infeasible case returns named rule set, never a sequential fallback — **✅ 2026-11-18**: hint warm-start (`hint_used`/`n_vars`/`n_cons` on Solution, F-36 blanks filled); slack ladder = cumulative `SlackFlags` rebuild (fills→diversity→时段偏好→天气→远郊独占, 永不放松 C-01/C-02/C-04/C-08/F-20); certificates = 7 static reason codes on `unplaced[rid]` + terminal INFEASIBLE, 双语模板 100% 覆盖测试; `determinism_guard`+`canonical_solution` red line; tests `test_trip_solver_model_e.py` 17 例, trip_solver 全套 125 passed + 1 skipped |
| **P1-F** | Assembly F-30 plan materialisation, F-31 meal anchors, F-32 chips, F-33 bilingual disclosures, F-34 trip-center sync + **G-01 golden pass end-to-end** | `trip_solver/assembly/*.py` | **M** | 1 | **G-01 green**: 颐和园 timed or disclosed-unplaced, no unrequested filler before musts, lunch at 慕田峪 site, card≡leg; P0 gates vacuously green — **✅ 2026-11-18**: `assembly/{materialize,meals,chips,disclosures,sync}.py`; G-01 golden green（5 必去全排、E-1 形态、card≡leg+同址午餐锚、回城独立卡、validate_plan 全过=P0 空绿、装配确定性）；entry `SolveOutcome.plan` 可服务物就位（serving_ready 翻真，TRIP_SOLVER 默认 legacy 零行为变化）；trip_solver 全套 139 passed + 1 skipped |
| **P2-A** | Shadow harness F-60/F-61: run old cascade and new model on the same snapshot, diff report (relative criteria), convergence metrics F-62 | `trip_solver/shadow/*.py` | **M** | 1 | diff report on corpus v1 (G-01 + this week's fixed incidents) — **✅ 2026-11-18**: harness (`shadow/{views,asserts,violations,corpus,compare,metrics}` + CLI), corpus v1 = g01 + g02 tower-late-gate/g03 third-cluster/g04 endpoint-transit + G-01 recorded baseline (`tests/golden/legacy/`), first report in `shadow/2026-11-18/` (model 0 violations, legacy baseline detects B-01×1/B-02×2/B-03a×1/B-03c×1); legacy side = recorded runs (M6 offline batch); in-process cascade replay + determinism calibration deferred to P2-B corpus regeneration |
| **P2-B** | Corpus expansion + gap burn-down: scenario families (remote days, endpoint days, rain, towers, reopen, typo…) each as JSON + expected shapes; every gap becomes a scenario **before** fixing | `tests/golden/*.json`, report iterations | **X** | 1–3 | all corpus scenarios not-worse-than-legacy + bug classes eliminated + convergence within budget (**Q3** proven) — **P2-B1 ✅ 2026-11-18**: corpus 4→13（g05 rain / g06 reopen-pins / g07 name-variant / g08 remote-exclusive / g09 duration-clamp(Q1) / g10 multi-city(C-07) / g11 trip-scale(Q3) / g12 closed-weekday(C-01) / g13 content-twin，`build_corpus_v2.py` 可再生）；进程内级联回放 落地（`shadow/replay.py`：快照桩库+BoomLLM 哨兵+天气双窗映射，M6 离线批）→ 12 份 legacy 记录再生（g01 手录不覆盖）+ 双跑确定性校准 12/12；新断言 remote_day_purity / span_cap / city_coherence；报告 `shadow/2026-11-18/p2b-corpus-v2/`：gates 6过/0败/2挂——corpus 13/12 ✅、收敛率 1.0（g11 全趟规模 270ms ≪ 3s，Q3 语料级实证）、确定性 1.0、not-worse 13/13、B 类新引擎全 0、legacy 未收敛披露 0（plan-score Δ 与 14 域 parity 仍挂 P1-D/F）。烧录续档：g04 端点日回放违例（day_start_floor/day_end_ceiling ❌）、g06 钉回放缺位（v1 不回放 pin，断言诚实失败）、g09 回放侧 span>240 —— 全部随 P1-D/E/F 落地逐轮迭代报告 **P2-B2 ✅ 2026-11-18 收口**：同步 P1-D/E/F 后全量 142 测绿；两个 F-62 gate 由挂起转**实测**——plan_score_delta **4/12 within −2%**（同一打分器两侧：回放打分真级联计划、F-30 物化打分模型计划，Q5 常量保真；差距归因=**模型欠补点**：legacy 8–22 卡/程 vs 模型 fill 0–4，空上午/日均衡/零娱乐软罚主导——P1-D 补点权重迭代烧录项，逐场景 Δ 已量化）；parity_domains_14 **13/14**（编辑与会话生命周期=P4 未落=切换阻塞项非影子阻塞项）。P2-B 验收线本身全绿：not-worse 13/13 + 新引擎 B 类全 0 + Q3 收敛 1.0（g11 270ms）；。**P2-B3-iter1 ✅ 2026-11-18**：①晚闸对齐——F-12 无窗豁免收窄到街区语义行（citywalk/街名；其余无窗行按 2026-11-17 晚闸拍板吃 16:30/15:30），晚场违例 −600 清零（g01/g03/g06/g07 显著回升，g06 反超 legacy +14%）；②分层推进加固——TIER_DETERMINISTIC_BUDGET 0.2→0.4（cap 变更扩大搜索面后 preference 层曾超时回退 tier① 任意解，E-1 09:30 班恢复）；plan_score gate **4/12→6/12**（g03 差 0.2pp），全套 142 过 1 跳。**iter2 待办（证据已录）**：打车叫车缓冲（矩阵纯车程 vs 审计 车程+30）、午餐卡→下点行进缝、下午单大点闸——。**P2-B3-iter2 ✅ 2026-11-18**：三条铁律 7/审计对齐约束落地——①C-03 走行缝=审计精确式 max(矩阵, taxi(km))（taxi=车程+30 叫车；同址 ≤0.5km 免隔腿）；②C-09 餐缝地板 30（宿主嵌套/远郊 F-22 豁免）；③C-12b 下午单大点 ≤1/日（2026-11-04 拍板口径）；E-1 单测改条件正典断言（同优合法形状两种：升旗锚当日/故宫晨锚换日，语料 g03 正典仍钉）。**iter1 更正**：plan_score gate 实为 4/12→**5**/12（前报 6 系误计）。iter2 后 gate 2/12（g12 持平/g13 胜）——**证据：gate 与约束刚度强耦合，单旋钮不可 调**（矩阵+30 变体=5/12 但过度约束；审计精确式=2/12）；**iter3 联动项**=步行 15km/日上限 + deviation 4→1 + g03/g04/g11 回归烧录 + 回城卡被审计计为大点的装配伪影 |
| **P3** | Flag-gated switch: one small entry diff + rollback switch; P0 gates as acceptance; quiet-window precondition | `api/plan.py` (few lines) | **S (code) / gated** | 0.5–1 | contract/audit suites green; 「求解器未收敛」 disclosures = 0; rollback verified — **P3 ◐ 2026-11-18 代码先行**：`trip_solver/{entry,telemetry}.py` 落地 F-35 契约（`TRIP_SOLVER`=legacy\|shadow\|cpsat，默认 legacy=零行为变化；cpsat 未就绪（P1-F 装配缺失）或异常 → F-36 遥测 + 现行引擎兜底 + 双语披露 = M8 回滚形状；测试模式 fail_loud）+ F-36 结构化遥测（slack_level/n_vars/n_cons 留 P1-E 诚实空位）+ M6 shadow 采样闸（should_sample 确定性 5% 桶）；回滚已验（测试级：cpsat→legacy 翻旗后零模型调用；11 测绿+trip_solver 套件 72 过 1 跳）。**切换未发生**：api/plan.py 入口缝与真切换随 P1-F 落地（届时才有可服务物），闸门仍=P2-B 全绿（plan-score Δ+14 域 parity）+ 全量套件 + 静默窗。**P3 缝完备 2026-11-18（01c835b）**：`live.py` 活快照（F-03/F-10：必去绑定+骨架兜底绝 不静默丢、池卫生、AccessServiceStore→F-14 档案绑必去+池、天气双语）+ /plan/start 旗标门（F-42 to_thread，默认 legacy 零行为变化，异常回落+披露=M8）；7 新测绿。**切换唯余**：静默窗 + plan_score gate（tier② 对齐设计迭代，证据全录 p2b3-iter2 报告）——**R5 后全绿就绪**：plan_score 12/12 ✅ 收敛 1.0 ✅ parity 14/14 ✅，全量套件绿；唯余静默窗翻旗（TRIP_SOLVER=cpsat，M8 一键回滚）。**二期·消息轮换 2026-11-18**：R7（0599b7f）换局纯路线声明走引擎（新 ts- 会话，班次/语言/时刻透传）+ start 缝形状闸 seam_plain_shape（复杂开局留 legacy）；R8（91fef5f）_generate_v0 偏好重排钩子（replan_seam_shape 形状闸 + seam_attempted ContextVar 防双跑，preferences 入快照=池 boost+tier② 偏好奖励+钉卡折必去）；R8-点名（6ac8e97）换局**点名长句也走引擎**——_restart_named_musts 离线读「必去」类短语进 musts，快照绑定链精确名→文本匹配→骨架兜底（缝不吞点、B-01）；「想去」=心愿软语义与无标记偏好残渣留 legacy（R8 钩子/会话内重排承接）。live 实证：换城必去灵隐寺→新 ts-+engine=cpsat+落卡；换城必去西湖边上的楼外楼→新 ts-+楼外楼落卡（库外点名绑定链合并最近已知点）；同城点名/偏好→会话内重排不换局（new_trip_brief 换目的地判据不变）。**R8 全量切 2026-11-18（拍板「everything should go to cp-sat including 复杂形态」；交互层零改动——GLM 理解/确认轮/行前卡全保留）**：S1（67682c1）start 缝形状闸收窄——城际方式 train/flight→TripRequest mode 透传（C-05 缓冲已载）、确认卡 days/班次 override=用户选边折算直连（days_override 同时作废分城天数，legacy 同口径）、行前卡标志透传；行前日期只接默认端点（到达=首日/离开=末日），中途转移日留 legacy（_apply_intake_times 语义）。S2（d75322b）分城天数建模 **C-17**=legacy _split_days 模型镜像（口径 A：城市块连续+请求城市序+末位真实目的地吃满到 days；出发城/闭合尾城不占活动窗；候选锁窗、缺省零约束零漂移）——TripRequest.city_days 入快照与 hash，start/replan 两缝透传，语料 g14+回放录件。S2b（c4ab747）餐类必去建模——C-09 真餐厅 **any-槽**（模型自选午/晚、每放置日恰绑一槽、另一槽照常出系统餐卡=不双餐；legacy 同口径不锁槽），live 绑定 category=food→meal_slot=any，extract 带 bound_cid，装配侧餐厅**顶餐卡**（命名卡带 POI 坐标）+materialize 去重不双渲染，replan 闸放行餐类必去，语料 g15+回放录件。S3 replan 闸随 S2/S2b 落地——唯余自造点（created_sites，快照无底库行，下一轮建模）留 legacy。剩余 legacy 面=brief/带图读点确认轮（交互层）、中途转移日行前日期、自造点；引擎任一失败回落 legacy+双语披露（M8 形状）不变。**S4 live 实证热修（同日）**：①live 池按行程形状配额（总量≈days×7、城市窗/均分分配、出发城有分城时不取数）——修 3 城×30=90 候选 all-fill 空排（模型 4×g11 规模 tier② UNKNOWN 保空前缀）；②R4 贪心种子两修：挂点 index==1 在 tier② Solve 后=毒化 ③④ 的死代码（移到 tier① 证毕）+ 同变量双重提示 MODEL_INVALID（单字典合并+同日光标推进避让已排项）；③池>20 通道 tier② 专属 dtime 定标 ×n/20（上限 4×；其余层维持 R5 口径 g11 墙钟不爆）；④换局点名裂词修复：整名精确命中底库（福和慧含「和」）不裂开、单字碎片弃（宁 legacy 不出垃圾卡）。live 实证：分城单/城际+override 单/换局点名餐类全 ts- 引擎。 |
| **P4** | Edit re-solve with hints F-50/F-51 (move/retime/duration/delete/pin) | `trip_solver/edit.py` | **M** | 1 | edit scenarios re-solve deterministically; reopen preserve-pinned green — **P4 ✅ 2026-11-18**：`trip_solver/edit.py`（F-50 DiffOp：move/retime/pin/duration/delete——retime/pin 升格一等 C-04 用户钉+晚闸豁免；F-51 user_pins 出处记录；Q7 800ms 信封超时保现计划+双语「重排中」披露；hint 重解确定性）；8 测全绿（钉不可动/重开保位/信封内全趟规模等）；**parity 14/14 ✅**（a70bdaf） |

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
