# hours_en 回填未决项 · 关闭记录（2026-10-29）

对应 task1.docx「唯一未决项：hours_en 回填批次中途报一个 SQLAlchemy 错误待查」。
（task1.docx 本体已于 10-29 仓库重构中删除，本文件为其关闭记录。）

## 修复本体（10-25 已完成，8a4993f @ feat/v24-trip-center）

两个根因均已实锤复现并修复：

1. **迁移漏列**：0014 只给 pois 加了 opening_hours_en → 0016 补 restaurants 列、
   0017 两表升 TEXT（迁移链 w12_0015→0016→0017，后续 0018 扩 best_visit_time
   枚举与本项目无关）。
2. **列长溢出掀批**：zh ~400 字译 EN 超 VARCHAR(500) 抛 StringDataRightTruncation
   → 回填作业双层防护（写前按列长预检 `_fits` 超限拒收留空回退中文 +
   单行写库异常隔离，一行坏只计 errors 不再掀翻整批）。

同步链补漏：opening_hours_en 已入 export 白名单（×2 表）与 `_EN_COLS`
本地保留集（app/services/reference_sync.py:65/99/109，已核实在位）。

## 生产验证

- 夜作业（ChinaTrip\POI en nightly，04:10，schtasks Ready）：
  - 10-26 实跑：pois 500 目标 / 353 行 830 字段落库，errors=4（单行隔离生效，
    未掀批）；restaurants 段——即原 UndefinedColumn 崩溃路径——**正常完成**，
    484 行落库。
  - 10-27/28：`database unreachable`（PG 容器未起，非本项目错误）。
  - 10-29 实跑：pois 416 目标 / 242 行落库，errors=3；restaurants 489 行落库。
- 单测：tests/test_backfill_en_columns.py **10 passed**（2026-10-29 本机复跑）。

## 数据波折与现状（2026-10-29 深夜）

- **10-28 16:12 pois 全表被批量重写**（updated_at max 为证），hours_en 整列
  清零（其余 _en 列完好：name_en 1,133 / intro_en 1,059 / review_tags_en 3,816）。
  reference_sync 白名单无恙、导入/刷新作业均不触碰 _en 列——判定为重构期间
  一次性人为操作，非调度链常态行为，回填后不会被计划任务再清。
- **10-29 深夜模板段重填**：804/1,899 落库（零 token，确定性转换）；
  剩 1,074 条复杂残句走 LLM 路径。

## 环境修复（10-29 深夜，回填跑通的前提）

- Docker Desktop 未自启 → PG（chinatripcodes-db-1, postgis:16-3.4, pgdata 卷）
  已拉起 healthy；27/28 两晚夜作业的 database unreachable 即此因。
- uv 迁移半途清空 .venv（一度连 sqlalchemy 都没有）→ 先按 requirements.txt
  装回；期间并行会话以 `uv add -r requirements.txt` 完成迁移（00:08–00:16），
  pyproject.toml 现已含完整依赖清单，venv 重建后 `uv sync`/`uv add` 均可正常
  使用。
- .env 被删 → 已重建（GLM_API_KEY 自 ZCode/Claude 会话转录找回，智谱格式
  实锤；恢复用临时文件已即删）。**GLM 接口当前 429（配额/限流，非鉴权错，
  过 0 点未恢复）**。

## 后续（自动）

- 剩余残句：04:10 夜作业幂等续跑（每夜 500 上限）；GLM 充值/解限后也可手动
  `python -m app.jobs.backfill_en_columns --table pois`。

## 追加（2026-10-30 晨）

- 智谱报错原文核实：`code 1113 余额不足或无可用资源包，请充值`——残句 LLM
  路径只卡这一件事，充值即通（04:10 夜作业同样在等它）。
- **模板转换器扩词表**（app/jobs/backfill_en_columns.py，确定性零 token，
  数字零改动，含 CJK 安全网）：停止入园/检票/入馆、最晚进入、停止售票、
  全年/全天/开放家族、节假日、月日日期（缩写月）、关闭、以现场公示为准、
  全角标点归一。tests/test_backfill_en_columns.py 增 test_template_hours_en_
  extended_vocab，全套 **11 passed**。
- 效果：hours_en 804 → **1,429/1,899**（三批扩词表共 +625 条确定性落库；
  第三批：节日名（国庆/劳动/中秋/端午/清明/元旦/春节）、"具体营业状态以
  当天开放情况为准"/"具体开放时间以官方通知为准"两条固定话术、最晚售票；
  区间尾"16:30停止入园"正则修正并回修 2 行早写入）。
  剩 450 条残句走 LLM（模板路径已榨干，二次扫描零新增）。
- 已建 2 分钟定时巡检（automation-a8b9ebf0）：每轮探一次额度，恢复即自动
  续跑驱动至清零；清零后报告完成。夜间 04:10 夜作业并行兜底。

## 遗留提醒（非本项）

- register_schtasks.cmd 里 en-nightly/stats-nightly 两行注册命令仍未提交
  （工作区在途改动）。
