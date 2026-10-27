# 仓库卫生登记 — 2026-10-27（审计轮）

> 来源：`git status` 全量未跟踪文件筛查（审计自动化每轮覆盖更新本文件）。
> **只登记不删除**——是否清理由用户裁决。未列出的 untracked 文件
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
