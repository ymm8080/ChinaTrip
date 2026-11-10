# 旅行 AI 规划器对标调研 → 预定工作项（backlog）

日期：2026-11-10
性质：调研结论 + 预定要做的工作项清单。来源为业界大型旅行 AI 规划器设计调研（携程问道/TripGenie、马蜂窝、Google、Booking、Expedia、Kayak、Wanderlog、Mindtrip、Layla）与自家代码现状（`app/services/agent/plan.py`、`app/services/itinerary/*`）对照。

---

## 结论先行

业内公开可查的最成熟范式即我方现行架构：**LLM 管理解与选点、确定性引擎管可行性**（Google 2025 公开方案；TravelPlanner 基准上 GPT-4 纯 LLM 全约束通过率仅 0.6%）。不换范式，只补具体设计点。

## 已对齐、无需动的部分

- 分工哲学：LLM 选点、CP-SAT/插入式排时管可行性；LLM 从不直接写行程（`app/services/agent/plan.py` 头部 §6.2/§6.4）
- 结构化编辑：`pipeline.py` 的 `apply_diffs`/`mutate` + `DiffOp`，含钉保护（`validate_change_scope`/`validate_pinned`）
- 降级契约：solver 失败→LLM 自修 ≤3 轮→半成品带警示，按日降级不塌方（`solver.py` solve_plan）
- Grounding 层：高德/携程/百度/腾讯四源 enrich 管道 + 营业时间 + best_visit 时段窗 + 天气/雨备
- 候选池模型：想法池→按天分配，`PlanAlternative` 替补池已存在
- 质量测试面：到达日/leg gap/主题夜块/去重等数十个测试文件

## 预定工作项（按性价比排序）

### P1 跨天局部搜索（Google 两阶段求解的 stage-2）——✅ 已实施，无需动工（2026-11-10 复核更正）

- **复核结论**：调研漏看了既有实现。跨天优化层已存在且强于本提案：`app/services/agent/plan.py` `_global_resched`（生成路径 16802 接线，求解后自动触发）——评分驱动 LNS（单点跨天 move/swap/拆日重建 destroy-repair）+ ILS shake/SA 扰动 + 严格改进接受准则 + 防回退基线快照 + 返程日/场馆亲和硬闸 + pin/必去/餐锚/hotel 豁免。
- **验收形状已被现有锚测试覆盖**：`tests/test_global_resched.py`（9 passed，2026-11-10 实测）——`test_lns_repairs_untimed_show_and_blank_morning` 即「前日塞爆+次日空上午」错配修复且 pin 不动。
- 原文「天间无优化算子」不准确：`solve_plan` 逐天独立属实，但跨天层在 agent 层而非 solver 层——属设计分工，非缺口。
- 原文提案保留备查（已划线作废）：~~在 solve_plan 后加 stage-2：枚举相邻天对换 visit、insertion_schedule_day 验证、plan_score 比较~~。

### P2 LLM 重要性评分进目标函数（Google）——⚠️ 前提不成立，缓行（2026-11-10 复核）

- **复核结论**：前提错位。选点默认是确定性算法（`plan.py` 274 行 2026-10-28 用户拍板「规划=特定算法，非通用 LLM」，PLAN_SELECT_MODE 切换）——默认链路里没有选点 LLM 调用可顺带吐 importance；要拿 importance 得为每个候选加一次 LLM 通路（延迟+成本）。
- **收益也存疑**：LNS 接受准则是「总分严格改进且硬惩罚不加重」——无并列可比，tie-breaker 无处发力；静态 `_quality`/`_source_tier` 已覆盖挤出依据（低质卡先溢）。
- **裁定**：缓行。若未来 LLM 选点模式成为主路（PLAN_SELECT_MODE 翻默认），再让 LLM 顺带吐 importance 进 `plan_score`，届时无额外成本。
- 原文备查：~~选点 LLM 输出候选时顺带吐 0-1 importance 字段；进 plan_score 作 tie-breaker 与挤出依据~~。

### P3 排队/分时热度曲线（Google Popular Times 思路）

- **现状**：`CrowdProfile` 只是节奏系数带（0.6–1.2，`models.py`），非真实分时热度。
- **做法**：高德热力/携程实时人流按 POI×小时建拥挤曲线表，接到 `best_visit` 时段窗上（旺季/淡季、周末/工作日分曲线）。
- **依赖**：数据源可用性探测（新 enrich job）。

### P4 扰动鲁棒评测（TripTide 思路）——✅ 已交付（2026-11-10，tests/test_perturbation_robustness.py，7 passed + 1 xfailed）

- **交付**：纯新增测试夹具，驱动真实修订入口 `pipeline.py:186 mutate()`（与 PUT /itineraries/{id} 同一函数，零 mock），覆盖返程航班延误 2h（retime）与 POI 临时闭馆（remove+add 替换）两场景，断言 validate_plan/pin 不丢/范围不越界三不变量。
- **摸底产出的真实缺口**（评测的价值所在；GAP-2/GAP-4 已于当日修复，84345d3）：
  - GAP-1 铁律 10 `from_day` 范围闸全库无生产调用方——死参数（接线改线上行为，留待产品拍板）；
  - ~~GAP-2 钉住点闭馆=铁律 2 与铁律 19 双闸死锁，引擎只拒不升级~~【已修】mutate 对「铁律 2 打在钉住卡上」追加 rule_id=19 warning（中英解钉指引，不污染 ok 口径）；
  - GAP-3 DiffOp 无"改交通时长"操作，延误+改签（航程也变长）表达不了（编辑面产品决策，留待拍板）；
  - ~~GAP-4 `validate_change_scope` 整对象相等比较（rules.py:608）被 mutate 出口 annotate_legs 腿标注漂移误报铁律 10~~【已修】`_scope_key` 对三个腿标注字段归一化后比较，xfail 转 pass。

### P5 交付前双模型质检（马蜂窝"质检员"思路）

- **现状**：校验全为规则，拦不住 POI 改名/闭馆/张冠李戴类语义错误。
- **做法**：交付前一次廉价 LLM 校验（比对候选快照：名称-类别-城市一致性），不合格回退 `PlanAlternative` 替补。
- **约束**：单次调用、超时即跳过（不阻塞主流程）；只校验不改写。

### P6 外部 benchmark 对齐（TravelPlanner / 成对偏好）

- **做法**：
  1. 将 `rules.py` 校验器包一层 TravelPlanner 式 checker 形态（query→约束清单→自动通过率）；
  2. 建几十题固定评测集（真实 query），算法改动跑出可比数字；
  3. 线上北极星改用**用户编辑距离/采纳率**（对 AI 行程的删改量），挂在 `lane_metrics` 旁。
- **涉及**：`app/services/itinerary/rules.py`、`lane_metrics.py`、ops 评测脚本。

### P7 小项两个

- **数据快照冻结**：生成时冻结营业时间/价格快照进行程实体，diff 与评测可复现。
- **证据链**：每个推荐卡片挂 UGC/review 来源（`review_summary` 已 enrich，只差透出）。

## 明确不抄

- TripIt 式预订凭证聚合模型（无 Day/Slot，场景不同）
- Kayak 对话+库存双通道（无预订库存）
- 纯垂直大模型路线（携程问道，成本不匹配）

## 评测/摸底附产：首轮 must_visits 心愿抽取链缺口（2026-11-10 调查）

P4 评测夹具建造期间对 `start()` 首轮心愿抽取链的独立调查（改动面之外，
留案备查）：

- **缺口 1（结构性）**：首轮 `start()` 无确定性心愿抽取通道——用户偏好
  文本中的「想看兵马俑」类表达在 trip_items=None 时
  `_absorb_wishlist` 恒返回空，心愿靠 later 轮的意图识别补，首轮池内
  无心愿约束。修复方案已备好（复用 `_WISH_VERB_RE`/`_wish_pure_core`
  plan.py:2176-2220 的动词抽取 + 3053-3090 排除谓词 + 3091 grounding
  闸 + 11192-11219 池绑定；接入点 `_bind_wish_poi` 11752-11791）。
  **⚠️ 属引擎行为变更、影响全部用户，待用户批准再动工**
  （先例：CP-SAT 影子分支呈而未批）。
- **缺口 2（已修，同日）**：候选收集同名跳过判据
  （plan.py:11023 一带）对同城往返 `["北京","北京"]` 把唯一目的地当
  回程尾跳过 → 静默空池。修复：仅当同名项在末位且 len>2 才按尾城跳过。
  锚：tests/test_plan_candidates_require_location.py 两新测。
  **实证（2026-11-10 活库 A/B）**：杭州/重庆/南京同城往返池
  32/33/35（旧逻辑 0）；hz-3d-westlake 单跑 A/B——旧逻辑假设行无池
  内容，新逻辑流出真实池（品类上限/白名单披露齐全）、行程仍全绿。
  注：评测集 visit 数不变（1/天）系行程级品类上限既有规则所致，
  与本修复无关，不属本项承诺范围。

## 关键来源

- Google Research: Optimizing LLM-based trip planning — https://research.google/blog/optimizing-llm-based-trip-planning
- Google Trips TSP（Christofides）— https://research.google/blog/the-280-year-old-algorithm-inside-google-trips
- TravelPlanner（ICML'24）— https://osu-nlp-group.github.io/TravelPlanner
- OpenAI × Booking.com 案例 — https://openai.com/index/booking-com
- 马蜂窝双模型架构 — https://www.qbitai.com/2025/04/278095.html
- Uber DeepETA — https://www.uber.com/us/en/blog/deepeta-how-uber-predicts-arrival-times
- Layla agents 分层记忆 — https://www.layla-network.ai/post/deep-dive-into-layla-agents
- Kayak Ask AI — https://www.kayak.com/news/ask-ai
