# 仓库卫生登记 — 2026-10-27（审计轮）

> **状态更新（2026-10-28 01:00）：用户授权「全部办了」——A 节 42 项已全部删除、
> B 节已写入 .gitignore、C 节已随审计 commit 提交（见 G 节）。本文件转为备查档案。**
> 来源：`git status` 全量未跟踪文件筛查。未列出的 untracked 文件
> （POIS DATASOURCE CSV/`_src/`、各设计 docx/pdf、`CLIENT_DATA_REQUIREMENTS.md`、
> `fast_slow_lane_PROGRESS.md` 等）为待验收工作成果，不属于垃圾。

## A. 明确的临时/垃圾文件（建议清理）

| 位置 | 文件 | 判断依据 |
| --- | --- | --- |
| 根目录 | `.png`、`CHINATRIP.lnk`、`_tmp_grep1.txt` | 空扩展名/快捷方式/一次性 grep 输出 |
| 根目录 | `mic*.ps1`×5、`micenum/micfix/micreset/micecho/mictest2`、`micreset_result.txt`、`netfix.ps1`+`netfix_result.txt`、`tlsfix.ps1`+`tlsfix_result.txt`、`dualtest.ps1`、`epenum.ps1`、`run_hidden.vbs` | 一次性系统修复脚本（2026-10-19 前后麦克风/网络/TLS 排障），问题已结案 |
| CHINATRIP CODES/ | `_assess*.txt`×4、`_check1–5.txt`、`_dbg*.txt`×2、`_final.txt`、`_verify_art.txt`、`_audit_pois.json` | 前会话分析中间产物（`_` 前缀即临时约定） |
| CHINATRIP CODES/ | `tmp_t/`、`tmp_truff.txt` | 临时目录/临时文件 |
| CHINATRIP CODES/ | 乱码名文件（`鍀垫…`，GBK/UTF-8 双重编码损坏的文件名） | 文件名已损坏，内容不可考 |
| DESIGN/ | `baidu_pilot.log`、`debug.log`、`ctrip_enrich_full.log`、`heuristics_duration_fill_2026-10-25.log`、`llm_web_enrich_calib_2026-10-25.log`、`llm_web_enrich_smoke_2026-10-25.log` | 作业日志（结论文档已另行沉淀） |
| DESIGN/ | `~$ature_gap_and_dev_plan_2026-10-23.docx` | Office 锁文件残留（Word 非正常退出） |
| DESIGN/ | `备份属于 feature_gap_and_dev_plan_2026-10-23.wbk`、`POIS DATASOURCE/备份属于 README.wbk` | .wbk 自动备份（原件都在） |

## B. 应进 `.gitignore` 的工具目录

- `.zcode/`（仓库根）
- `CHINATRIP CODES/.claude/`

## C. 已删除待提交（`git rm` 生效需 commit，等用户验收）

- `DESIGN/task1.docx`、`task2.docx`、`task3.docx`（工作区已删，删除未提交）

## D. 审计核查结论（2026-10-27 轮 #2 · 终态）

- 三守门全绿（2026-10-27 23:54）：`ruff check` 0 错（plan.py I001 由并行会话自修）、
  `ruff format` 226 文件全格式化（本轮格式化 tests/test_translate_api.py，重跑 9 passed 无行为变化）、
  `node ops/check_h5_static.js` 全 ok（en 662 key）；pytest 全量 **1383 passed / 0 failed**。
- 设计文档同步（轮 #1 完成）：`database_design.md` 头部 v1.16、迁移史补 0009–0018、重复编号 v1.14→v1.16；
  `INDEX.md` 数据库设计条目 v1.1→v1.16、solver `best_visit_time`「待接线」→「已接线」。
- 2026-10-25 审计备查 B1–B5、A 已全部核销或标注（见 issues_design_vs_code_2026-10-25.md 核销注记；
  B1 因无 PG 连接标注待查，为本任务唯一遗留项）。
- **✅ 审计修复全部完成**：此后每轮只跑守门三件套确认，不再做任何改动。

## E. 追加（轮 #5，2026-10-28 00:10）

- 轮 #5 全量跑偶发 1 failed：`test_poi_details.py::test_db_down_latch_skips_subsequent_attempts`
  ——单跑即过、两文件 10-26 未动，判定为**测试自身时序竞窗**（0.05s 冷却窗内须完成
  第二次 get，满载进程调度/GC 抖动可击穿）。最小修复：冷却 patch 0.05→30s 留余量、
  过期路径改为直接回拨 `_db_down_until`（不赌真实睡眠）。修复后单文件 15 passed、
  全量复跑 **1383 passed / 0 failed**。服务实现（实例级闩）无任何改动。

## F. 扩围审计（用户指令：全项目代码 vs 全部设计文件，轮 #8–#9）

- **README.md API 表补齐**：三向 diff 证实 ~74 条路由未记载（auth/asr/weather/visa/
  feedback/booking-auto/payments/call/travelers/tasks/metrics/plan 条目操作/share/pois detail/
  amap regeo·ip），已按原表风格补 16 行 + 域服务行 + 头部版本 v2.0→v2.5。
- **铁律 0–23 落点核验**：14/15/16/19/22/23 + 成本闸门 + §6.8 付费墙规则引擎全部有
  代码实证；铁律 21 一处登记性张力（H5 冒烟页 asr 走智谱云——测试面例外，产品正解
  =原生端侧引擎，M1.5 未到期）。
- **database_design.md** 表清单 18→21（补 poi_reviews/poi_stats/payments）+ 迁移史
  0009–0018 + v1.17 补录行。
- **language_dual_system_design.md** v1.5：hours_en 星期口径定案回写（全称，2026-10-25
  用户拍板，代码/测试早已实现而文档未记）；§5.1 表分类 23→21 + payments 补录。
- **planning_engine_upgrade「已到手在丢」指控失效**：rating/photos（poi_backfill.py 只填空
  +溯源）与携程时长/点评数/点评标签（ctrip_hours.py）均已解析落库。
- **pytest 503 五连败**（轮 #8）：并行会话 map provider 重构中间态，其自行修复，
  轮 #9 复跑全绿 1383/0。
- **show_booking S1–S5 分期核验（轮 #10）**：P0 五件全实证（04 CSV 入库 import_shows /
  迁移 0018 'show' 枚举 / S5 solver `_SHOW_STARTS` 场演窗 / 路径 A 预填卡 booking_url 透传 /
  S1 放票任务复用 build_reservation_tasks）；S4 档期守护=既有 hours 24h stale 刷新链；
  S2 实名托管=P1、S3 回流蹲守=P2——外部前置（联盟 key / 商务签约）未到期，非缺口。
  **五份子设计核验至此全部通过**。
- **✅ 扩围审计（全项目代码 vs 全部设计文件）核验面完成**：主设计铁律 0–23、五份子设计、
  计划/提案两份、README API 表、数据库表清单——均已核验并同步。剩余两项外部阻塞：
  B1 需 PG 凭据（查 hours_en 缩写行残留）；baidu_client.py 两处风格项属并行会话
  活跃 WIP 不代改。pytest 稳定 1383/0，H5 守门全绿。

## G. 收尾执行（2026-10-28 01:00，用户授权「全部办了」）

- **A 节清理已执行**：42 项全部删除（根目录 16 + CODES 临时产物 15 + tmp_t/ 目录 +
  DESIGN 日志 6 + Office 锁/.wbk 3 + 乱码名文件 1）。真实工作成果（POIS CSV、设计
  docx/pdf、进度 md）一概未动。
- **B 节已执行**：`.gitignore` 追加 `.zcode/`、`CHINATRIP CODES/.claude/`、
  一次性运维脚本模式（mic*/netfix*/tlsfix* 等）。
- **风格项收口**：baidu_client.py E501（adcode 三元拆行）+ 格式化——ruff check/format
  **全树清零**（226 文件）；test_baidu/poi_details/translate 38 测全过。该文件仍归并行
  会话所有，未纳入本审计 commit。
- **B1**：~~仍待 PG 凭据~~ → **✅ 已核销（2026-10-28，用户启动 PG 后实测）**：
  缩写行 674 → 模板同源重生成 711 + 定向替换 70 → **终态 0 / 1886**（38 行原列已是
  英文/复杂文本正确跳过）；中文原列未动。唯一外部阻塞清零，审计任务全部闭环。
- **通话记录测试时序偶发（轮 #84，2026-10-28 04:07）**：
  `test_call_api.py::test_records_show_start_end_duration_and_minutes` 单跑即过、
  文件 10-25 未动——answer→end 两次请求的真实墙钟间隔满载可超 60s，击穿「≈0 用时
  整分钟退回」前提。最小修复：测试内冻结 call_service 时钟（monkeypatch 模块级
  datetime），consumed=0 成为确定性前提。单文件 9 passed、全量 1386/0（commit b1604d9）。
- **PG 启用引发的 44 连败（环境性，非代码回归）**：PG 可达后部分存储走 PG 路径
  （0015 行程状态落 PG 设计），而该 PG schema 不全（pois 有数据但 trip_items 等缺失
  ——历史 stamp 未跑全迁移）；按 runbook `alembic upgrade head` 补全 21 表后
  163 个受影响测试全过、全量复绿。守门基线自此含真实 PG。
