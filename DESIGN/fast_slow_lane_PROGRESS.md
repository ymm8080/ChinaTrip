# 快慢双车道（§6.12）落地进度 — ✅ 全部完成（2026-10-27）

依据 `DESIGN/travel_agent_system_design V2.5.md` §6.12「延迟与并发治理（快慢双车道）」
与配套缓存机制，agent 运行时间缩减机制已全部落地 `CHINATRIP CODES/`。
终态守门：**pytest 1383 passed / 0 failed；ruff check app tests 全绿**。

## 检查单核销（六项）

| # | 项 | 状态 | 落点 |
|---|---|---|---|
| 1 | 分类闸门三级（规则→意图缓存→Flash 兜底，失败 escalate→main） | ✅ | `app/services/gate.py`（既有实现 + 本轮补 `poi_hours`/`wishlist` 两条 fast 规则） |
| 2 | 意图缓存（归一化键 + TTL + 容量逐出，escalate 不缓存） | ✅ | `gate.py` 既有（TTL/容量走 settings） |
| 3 | 快车道：高频意图确定性直答，不进 agent loop | ✅ | `app/services/fast_lane.py`（`poi_hours`/`wishlist`/`translate`/`restaurant`；答不出回主车道，宁缺毋错）+ `app/api/plan.py` message 分流 |
| 4 | 慢车道：异步队列 + 「已受理」+ 状态端点 + H5 轮询 | ✅ | `app/services/task_queue.py`（SQLite 队列 + asyncio worker + `bulk_extract`/`replan` 处理器 + 崩溃恢复 requeue）+ `app/api/tasks.py`（POST 202 / GET 状态 / 列表）+ `main.py` lifespan worker + H5 `planPollSlowTask`（3s×40 轮询，done 渲染 / failed 提示 / 超时降级） |
| 5 | 指标：lane + TTFT 记录 + 聚合端点 | ✅ | `app/services/lane_metrics.py`（lane 计数 / off_main_share / p95 窗口 / 目标与 met 布尔）+ `app/api/metrics.py`（GET `/api/v1/metrics/lanes` = gate.stats + lanes.aggregates） |
| 6 | 测试 + 全绿 + ruff | ✅ | 新增 `tests/test_task_queue.py`(14) `test_fast_lane.py`(14) `test_lane_api.py`(8) `test_lane_metrics.py`(7) `test_llm_model_pin.py`(2)；`tests/test_plan_api.py`/`test_time_slot_integrity.py` 补双车道依赖覆写（防进程级单例污染）；全套 1383 绿；新文件 ruff 干净 |

## 附加拍板（用户 2026-10-27）

- **LLM 始终 glm-5.3-flash**：`config.py` 两级模型默认值、`.env` `GLM_MODEL`/`GLM_MODEL_FLASH`
  均钉死；`tests/test_llm_model_pin.py` 锁定（主力与 Flash 同模型，分级靠闸门分流 + 温度/长度）。

## 设计取舍（备查）

- **Redis → SQLite**：设计书写 Redis 异步队列；本仓库 MVP 无 Redis。
  `TaskStore` 照 `call_store`/`state_persist` 模式落 SQLite
  （`settings.task_db_url`，默认 `data/tasks.db`，测试传 `:memory:`），
  进程内 asyncio worker 轮询消化；状态落库、重启可见（worker 启动
  `requeue_running()` 把崩溃遗留 running 拉回 queued）。将来上
  Redis/PG worker：换 TaskStore 实现，TaskWorker 协议与端点不变。
- **任务表不走 alembic**：与 payments/call 侧库同哲学（独立 SQLite DSN +
  `CREATE TABLE IF NOT EXISTS`），PG 主库零新表。
- **replan 慢车道语义**：闸门判 slow 的消息立即回「已受理」（含 task_id
  截短引用），后台 handler 跑完整 `agent.message` 管线并落库会话；
  结果带 `reply/state/plan/violations`（与 /message 响应同构），
  H5 轮询 done 后用 `planRenderSafe` 直渲染。
- **指标口径**：main lane 记录的是整轮时长（非流式 TTFT 近似口径），
  真流式 TTFT 待 v0 生成流式化（§6.12 ④ 既有悬案）；off_main_share
  目标 ≥0.8、fast p95 <1s、slow 受理 <3s，端点直接给 met 布尔。

## 接线图（快速回溯）

```
H5 planSend → POST /plan/{sid}/message
  └─ RequestGate.classify(text)                # 规则→意图缓存→Flash
      ├─ fast  → FastLane.answer(session,text,intent)   # poi_details/trip_items/TranslationService(+短语缓存)
      │           ├─ 命中 → history 落库 + lane=fast 直答（答案缓存 60s）
      │           └─ None → 落主车道（不虚构）
      ├─ slow  → TaskStore.enqueue("replan") + lane=slow「已受理」（H5 拿 task_id 轮询）
      └─ main  → agent.message 完整管线（原行为）
lifespan: TaskWorker.run_forever()（bulk_extract / replan；崩溃恢复）
metrics: 每回合 lane_metrics.record(lane, ttft, intent, source)
```

## 并行会话协调注意（重要）

工作区有多个并行定时会话同时改本仓库（travelers/百度迁移/审计），
`app/api/plan.py` 曾被并行会话从旧快照重写导致本功能接线丢失（已复回，
当前 `get_fast_lane` 由并行会话改为 translate 走 Depends 注入的形态，
与本功能兼容）。后续任何会话动 plan.py/gate.py 请保留：
`get_request_gate`/`get_fast_lane`/message 双车道分流/lane 指标埋点/
`get_task_store` 依赖；丢失时按上文接线图最小复回。

## 收尾轮次记录

### 2026-10-27 调度轮 1（自动化 bccfde9a）——✅ 收官

- ✅ **回退核查**：整批已由并行会话提交 `28e098c feat(plan): §6.12 快慢双车道落地`（含本会话此前两处修复：replan model_dump、fast_lane translate Depends 注入）；未提交 WIP 为 weather/POI 数据源批次（他人工作，未触碰）
- ✅ **收尾 a（INDEX.md）**：决策速查新增第 12 条「§6.12 快慢双车道落地」——闸门三级/快车道直答/SQLite 队列取舍/指标口径/模型钉死 glm-5.3-flash
- ✅ **收尾 b（travelers/H5 冒烟）**：pytest test_travelers_api + test_h5_static = 10 passed；TestClient 四步全链路 PASS——新增 201（响应即脱敏形 `E1234**78` / `+1202*****23`）→ 列表无明文 → export 唯一明文出口 1 行 → DELETE 204 → 删后列表空（物理删除）
- ✅ **收尾 c（指标口径实测）**：TestClient 真规则闸门 + 真快车道打混合请求 5 条 → lane 分布 `['fast','fast','main','main','slow']` 三车道路由全对；`GET /api/v1/metrics/lanes`：
  - `off_main_share = 0.6`（目标 0.8，met=false）——**样本过小所致**（5 条中 2 条为刻意的未命中 main 样例；真实分布需上线后观察，非系统缺陷，参数不改不阻塞）
  - `fast_ttft p95 = 0ms`（目标 <1000ms，**met=true**）——快车道确定性直答不触 LLM，口径成立
  - `slow_accept p95 = 0ms`（目标 <3000ms，**met=true**）——入队即回，受理达标
  - 备注：`gate.stats.total=0` 为 TestClient override 覆盖了进程级 gate 单例的脚本 artifact，生产路径 gate 统计正常（test_gate 覆盖）
- 🏁 **终态**：六项检查单 ✅ + 三项收尾 ✅ → **本功能开发完成，进度文档收官**
