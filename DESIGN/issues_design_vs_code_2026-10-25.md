# Design vs Code Issue List — 2026-10-25 15:06

> 依据：`DESIGN/` 设计文档（language_dual_system v1.4、paid_call_service v1.2 等）与
> `CHINATRIP CODES/` 实际代码全量比对（分支 `feat/v24-trip-center`）。
> 产出方式：全量 pytest + `ops/check_h5_static.js` 守门 + 关键文件逐一核对。
> 本文件为备查记录，不构成设计版本变更（「不采纳不立版本」）。

---

## 0. 会话内已执行的动作（披露）

1. **已回退** `app/jobs/backfill_en_columns.py` 至已提交的 "Mon–Sun" 星期缩写映射（详见 B1），其 9 个测试转绿。
2. **已删除** automation `automation-878900e2`（"Reactivate conversation every 2 minutes"）——其任务正是 EN i18n 迁移，双写者有掀翻 `index.html` 的风险（见 A）。
3. 分析用临时脚本 `ops/tmp_inventory.js` 已创建并删除，工作区无残留。

---

## A. 阻塞项：H5 静态守门未过 —— 且并行会话正在编辑同一批文件

`tests/test_h5_static.py` 失败，`ops/check_h5_static.js` 于 15:06 报告：

- **en 词典缺 236 个词条**（`data-i18n`/`I18N.t`/`tf`/`callT` 合并口径）——40 分钟前为 244，正在收敛。
- **`index.html` 脚本块 #1 有 208 处（显示上限 40）裸中文串未包 `tf()`**——覆盖规划看板、导航地图、预订/转链卡、付款、行程中心、链接历史、订单回填、通话记录。

`index.html`（15:05:04）与 `i18n.js`（15:05:23）在采样前 20 秒刚被修改——**有活跃会话正在迁移中**。

**建议**：让其收口，随后 `node ops/check_h5_static.js` +
`pytest tests/test_h5_static.py tests/test_h5_i18n.py` 复核。期间勿从其它会话打开同一批文件——
paid_call 进度文档 T6 记录过并行编辑写坏 `index.html` 引号、整页 JS 瘫痪的先例。

## B. 设计与代码的偏差（已核实）

1. **`hours_en` 星期写法冲突（曾打挂 3 个测试）。** 14:20 的并行改动把模板映射切成全称
   （"Monday–Sunday"），理由「用户定案：不用简写」未记录于任何设计文档；而设计文档
   （language_dual_system §5.2）、已提交代码、`test_backfill_en_columns`、`test_reference_sync`
   全部用缩写 "Mon–Sun"。已还原为已提交映射。
   **1 分钟跟进项**：若 14:20–14:26 间真有回填作业跑过全称版，部分 `pois.hours_en` 行会存
   "Monday–Sunday" 与全库口径不一——PG 上
   `SELECT count(*) FROM pois WHERE hours_en LIKE '%Monday%'` 可定论
   （夜间作业 04:10 跑，大概率 0 行受影响）。
2. **paid_call 设计 §12 承诺的 call 表 alembic 草案不存在。** 设计原文「call_store 表结构同时
   维护一份 alembic 草案（预留 0013）」；实际 `0013` 已被 `en_columns_2` 占用，链已到 `0017`，
   无任何迁移或 `models.py` 定义 `call_orders`/`call_sessions`/`call_minutes_entries`。
   SQLite 为唯一事实源期间无害，但设计承诺未兑现且「预留槽位」注释已过期。
3. **过期的 2 分钟 automation 仍在跳。** `automation-5452734a`（PG 迁移 B 期续跑）每 2 分钟
   激活一次，但其交付物（迁移 `0015_itinerary_pg_state` + 写穿 store）已随 `9ca9f60` 提交。
   其 prompt 无自删条款，将永久跳下去——建议删除。
4. **完整已验收的功能整体未提交。** 真人通话咨询全套（call_store/call_service/api/agent.html +
   20 个测试，进度文档 11:40 标 ALL COMPLETE：1148 测试全绿 + 真实 HTTP E2E 12/12）以
   untracked 状态躺在 `feat/v24-trip-center`，按纪律等用户验收 commit。这是当前仓库最大的
   工作丢失风险——一次误操作 `git clean` 即清零。
5. **仓库卫生漂移。** 根目录：`tmp_t/`、`tmp_truff.txt`、`CHINATRIP CODES/` 内乱码名文件、
   `.png`、`CHINATRIP.lnk`、约 10 个一次性 `mic*/net*/tls*` 修复脚本与日志。
   `DESIGN/`：`baidu_pilot.log`、`debug.log`、`ctrip_enrich_full.log`、`task1–3.docx`、
   `.wbk` 备份、已修改未提交的 `planning_engine_upgrade_2026-10-24.pdf`。
   另有 untracked `.zcode/` 与 `CHINATRIP CODES/.claude/` 工具目录——应进 `.gitignore`。

## C. 核实无误——无需动作

- **通话咨询实现与设计一致**（§5–§8）：轮询惰性强结状态机、原子 `try_consume`、
  `provider_ref` 幂等、alipay/stripe 诚实 503 stub、X-Agent-Key 护门（未配 503/错键 401）。
  测试覆盖充分。
- **alembic 链完整单调** `0001…0017`，含双语设计的 EN 列全套（0011/0013/0014/0016/0017）。
- **8 个新 `enrich_*` 作业为独立脚本**（API 路径不 import）——符合 jobs-as-ops-scripts 模式；
  明早 9 点的百度/腾讯配额 automation 为有意安排且熔断门控正确。
- **测试基线**：14:10 全量 1164 passed / 3 failed；B1 回退后仅剩 A 项守门失败。

---

*结论：一个真阻塞（A，并行会话正在收敛）、一个潜在数据一致性核查（B1 跟进项）、
一个轻微未兑现的设计承诺（B2）、卫生/automation 清理（B3–B5）。*

---

## 核销注记（2026-10-27 审计轮追加）

- **B1**：✅ **已核销（2026-10-28）**。PG 连接可用后实测：pois opening_hours_en 共 1886 行，
  其中缩写行 **674**（"Mon–Sun …" 等，口径定案前夜间作业产物，只填空语义导致从未被统一）。
  修复：复用 `backfill_en_columns.template_hours_en` 同源模板定向重生成 711 行 +
  缩写→全称定向替换 67 行 + 词边界补齐 3 行；模板出不了全称的 38 行（原列已是英文/
  复杂 LLM 文本，如苏州博物馆分段公告）正确跳过不覆盖。**终态：缩写行 0 / 1886，
  全称行 1416**。中文原列 opening_hours 全程未动，可再推导。 restaurants 表 EN 行为 0，无涉及。
- **B2**：核销——call_orders / call_sessions / call_minutes_entries 三表按设计 v1.2
  只存 SQLite 侧库 `app/services/call_store.py`；原「预留 0013」槽位注释早已过期
  （链现至 w12_0018），alembic 不再补 call 表迁移，该承诺不再追踪。
- **B3**：核销——过期 automation `automation-5452734a` 已不存在。
- **B4**：核销——真人通话咨询全套已提交入库（app/api/call.py 等均为 tracked）。
- **B5**：卫生清单移交 [audit_hygiene_2026-10-27.md](audit_hygiene_2026-10-27.md)
  持续登记，删除与否待用户裁决（本审计铁律：只登记不删除）。
- **A（H5 守门）**：核销——2026-10-27 23:42 复查 `ops/check_h5_static.js` 全 ok
  （en 词典 662 key 全覆盖），pytest 全量 1383 passed / 0 failed。
