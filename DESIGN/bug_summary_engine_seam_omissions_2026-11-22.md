# Bug Summary：R8 切引擎后「引擎缝相比 legacy 的功能遗漏」

- **日期**：2026-11-22
- **范围**：非心愿单主题（心愿单的 F1/F2/F3 已单独查完并修复）
- **状态**：**#1 #2 已修复并补回归测试**（详见文末「实施记录」）；#3 核实为设计边界，未改代码
- **证据级别**：静态代码审计 + 只读探针；#1 #2 已用回归测试坐实并转绿（测试名带 `r13p`）

---

## 背景

项目 R8「全量切引擎」后，规划请求优先走 CP-SAT 引擎缝（cpsat，会话 `ts-` 前缀），legacy 路径（`_generate_v0`）作为回退保留。这类 bug 的统一模式是：**legacy 路径落地/处理了某个功能，引擎缝漏做了，导致走新引擎时该功能静默失效**。

已修的同型 bug：心愿单（F1/F2）和天气（R13j）。本次审计排查其它功能。

---

## Bug #1 — 引擎缝会话未落地班次号/分城天数/中途转移日（重排时静默丢失）

**严重度：中高（最确证）**

- **现象**：开局时带班次号/分城天数 → 首屏正确；同一会话发"重排" → 这些约束静默变空、无披露地回退。
- **根因**：legacy 在 `start_nlu.start()`（`app/services/trip_orchestrator/start_nlu.py:78-108`）把 `arrival_no / departure_no / city_days / arrival_date / departure_date` 存进会话；引擎缝会话由 `generate_session_via_trip_solver` 在 `app/services/trip_solver/live.py:626-637` **直接构造，只存了到达/离开时刻，上述约束字段一个都没落地**。
- **消费端**：重排 `_session_snapshot`（`live.py:857-875`）偏偏从会话读这些字段，其 docstring（`live.py:820`）还写着"全参数随缝"。读取落空即丢约束。
- **触发链已确认**：`app/services/agent/plan.py:21285` 调 `replan_session_via_trip_solver` → `_session_snapshot`；形状闸 `app/services/trip_solver/entry.py:151+` 的 `replan_seam_shape` **只检查 cities/days，全放行** → 带约束的 ts- 会话重排确实会走引擎缝，触发得到。
- **探针**：以 `arrival_no='G123' / departure_no='G456' / city_days={上海:1,杭州:1} / intercity_mode='train'` 调 generate，返回会话上这些字段读到的是默认值/缺失——传入值未落地。
- **修复（已做，R13p）**：`generate_session_via_trip_solver` 新增 `arrival_date/departure_date` 形参并在会话构造时落地全部约束字段（`arrival_no/departure_no/arrival_date/departure_date/intercity_mode/city_days/comment_day_start`）；`_session_snapshot` 补传 `intercity_mode`（此前连读都没读）；API start 缝补传 `request.arrival_date/departure_date`。回归测试：`test_generator_lands_intake_constraints_on_session`、`test_session_snapshot_reads_intake_constraints`、`test_start_seam_forwards_intake_constraints_to_engine`。

## Bug #2 — 首日出发时刻（"LEAVE HOTEL ON 11AM"）在引擎首屏整链缺失

**严重度：中**

- **现象**：简报里写了首日离店时刻（引擎建模 C-04 地板会消费它），走引擎时静默失效。
- **根因**：legacy 在 `start_nlu.start()`（`start_nlu.py:218-222`）从简报正则解析 `comment_day_start` 并存进会话；引擎缝 `generate_session_via_trip_solver` 的签名（`live.py:507-527`）**根本没有 day1_start 参数**，首屏 snapshot 构造（`live.py:588-606`）未传，会话也未落地 `comment_day_start`。
- **触发条件**：简报为空但有 preferences 时不触发形状闸退回（形状闸只看 cities/days），会走引擎 → 首日出发时刻丢失。
- **旁证**：`tests/test_trip_solver_live.py:663` 有 `test_replan_honors_comment_day_start_floor`，说明 replan 侧认这个字段，但首屏会话落地这一环缺失。
- **修复（已做，R13p）**：引擎缝内部从 `preferences` 用同一 `_parse_text_day_start`（零 LLM）解析 `day1_start`，同时喂给首屏快照（C-04 地板）和会话 `comment_day_start`（重排复用）。brief 非空时已被形状闸退回 legacy，故只需处理 preferences。回归测试：`test_generator_parses_day1_start_from_preferences`。

## Bug #3 — 班次号写入交通腿 train_no / flight_no（确证，但属设计边界，不修）

**严重度：低（展示信息，不影响排程）**

- legacy 用 `_pin_intake_leg` 把用户填的班次号贴进行程交通腿；引擎模式按 R11（`start_nlu.py:260-271`）**故意跳过 `_apply_intake_times`**。
- **已确证是真遗漏**：`assembly/materialize.py:535-580` 装配转场腿时不填 `train_no/flight_no`，其注释称"班次号经既有 `/transfers/{item_id}/tno` 端点回填"，但**该后端端点根本不存在**（全仓搜索只有这句注释；前端只有手动补号的 `/transfers/{id}/number` 按钮）。所以引擎模式下用户表单填的班次号确实丢失。
- **为何不修**：引擎只在**城际转场日**生成交通腿，首日/末日没有"到达首城/离开末城"的腿；要让单城/端点行程也体现班次号，必须**合成**到达/离开腿——正是 R11 明令禁止的"二次改写引擎计划"。只贴已有腿则覆盖不到最常见的单城场景，等于没修。
- **建议**：需产品先拍板是否允许引擎模式合成端点接驳腿（推翻 R11 部分约束），再实施；否则保持现状——前端行程卡上有「🔢 班次」手动补号入口，功能不至于完全不可达。

---

## 已核为合法、不需改动的项

| 项 | 结论 |
|---|---|
| 天气 weather_lookup | 两侧齐（R13j 已在 `plan.py:885` 给引擎缝补上） |
| 升旗锚 / 入场闸 / 必去覆盖审计 / 通勤腿 | 引擎缝尾后处理（`plan.py:982/990`）两侧齐 |
| 图片 / brief 读取 | 确认轮合法退回 legacy，非遗漏 |
| 换局缝不带旧班次/日期 | fresh-start 语义，合法 |
| 形状闸退回 | 退回时披露完整，是设计 |

---

## 实施记录（2026-11-22，用户令「implement the fixing」）

**已改文件**
- `app/services/trip_solver/live.py`：`generate_session_via_trip_solver` 新增 `arrival_date/departure_date` 形参；内部解析 `day1_start` 并喂快照；会话构造落地 `arrival_no/departure_no/arrival_date/departure_date/intercity_mode/city_days/comment_day_start`；`_session_snapshot` 补传 `intercity_mode`。
- `app/api/plan.py`：start 缝补传 `request.arrival_date/departure_date`。
- `tests/test_trip_solver_live.py`：新增 3 个回归测试（会话落地 / 重排快照读回 / preferences 解析首日出发）。
- `tests/test_plan_api.py`：新增 1 个 API 缝传参回归测试。

**未改**：#3（理由见上，属 R11 设计边界，需产品决策）。

**验证**：`test_trip_solver_live.py` 37 passed；`test_plan_api.py` 130 passed；ruff check/format 全过；全量见提交说明。

## 建议的下一步

1. **#1 #2 已完成**（含回归测试），可随本次提交入库。
2. **#3 待产品拍板**：是否允许引擎模式为单城/端点行程合成到达/离开接驳腿。若允许，再实施并补测试。
3. 后续若再改引擎缝会话字段，务必检查 `_session_snapshot` 的读取口径是否同步——这正是 #1 的成因（会话存了、快照没读，或反之）。

## 边界

#1 #2 有回归测试坐实；#3 为静态审计 + 代码实证结论（端点不存在已用全仓搜索确认）。最终业务表现以线上真实会话与合同/核定为据。
