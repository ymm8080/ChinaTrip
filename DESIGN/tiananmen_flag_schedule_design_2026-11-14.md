# 天安门升（降）旗时刻模块设计（flag_schedule）

> 状态：**已落地**（2026-11-14 首版；2026 全年数据实测核对）。
> 范围：天安门广场站点「当日开始时间 = 升旗时刻」的全链路——官方公告页抓取、OCR 解析入库、DESIGN 本地快照、规划引擎打标与求解器锚定。
> 上游文档：[POIS_DATASOURCE.md](POIS_DATASOURCE.md)（站点底库口径）；[database_design.md](database_design.md)（缓存落库模式参照 `train_cache`）。
> 数据落位：`CHINATRIP CODES/app/services/flag_schedule.py`（单模块）；库 `CHINATRIP CODES/data/flag_cache.db`（gitignore）；种子随仓库分发 `CHINATRIP CODES/DESIGN/flag_schedule_seed_2026.csv`。

---

## 1. 目标与拍板记录

- **产品口径**：行程含天安门广场（北京）的日子，该站点开始时间 = 当日升旗仪式时刻（官方年度表为唯一事实源）；降旗时刻入表备用（当日闭场参考），不参与排程约束。
- **2026-11-14 三段式拍板**：① 一个模块，输入公告页 URL；② 转换为本地表格（year / date / rise_time / lower_time，按日期 + 类别 morning/evening 查询）；③ 每次规划天安门，开始时间从表取。
- **2026-11-14 存储拍板**：每次抓取**建表插入而非替换**——只追加不 UPDATE 不 DELETE，一次抓取 = 一个 `fetched_at` 批次，读取取每个 date 的最新批次（与 `train_cache`「留史只追加」同一口径）；本地文件落 **DESIGN 文件夹**。
- **铁律 19 不变**：用户自钉（pinned 且非 soft_pin）的时间权威优先，旗时锚跳过（plan 装配期与 solver 两侧双保险）。

## 2. 数据源

- 官方发布：北京市人民政府天安门地区管理委员会，每年 12 月发布次年全年表。
  2026 年版：<https://tamgw.beijing.gov.cn/sy/sjqsj/202512/t20251222_4356494.html>（2025-12-22 发布）。
- **关键形态**：正文表格是一张嵌入 PNG（TRS `W0*.png`），无文字版——解析必须走 OCR。
- 已知 OCR 坑（2026-11-14 官图实测，全在 `flag_schedule.py` 内消化）：
  1. 整幅跑检测器漏检上半区 → **纵向分带 OCR**（带高 55%、步进 45%、近距去重合并）；
  2. 月名误读率高（「一」漏检、「十」→「+」）→ **列定位改用表头 12 个「升/降」单元格**（按 x 升序 = 1-12 月），漏检列线性回归补位；
  3. 日号整格漏检（实测 5/25/26/27 四行）→ 行序=日序，「日号-行 y」**稳健回归**定日（迭代剔误读锚点，实测「26」→「2」拉平斜率事故）；
  4. 单格时刻误读（「6:01」→「10:9」）→ **单格修复**：相邻两日同字段都在且互差 ≤ 2×日漂移上限时取左邻补格，WARNING 披露；修不了整批拒收。

## 3. 模块结构（单模块三段式）

`app/services/flag_schedule.py` 一个模块含抓取、解析、落库、快照、查询、CLI。

### 3.1 抓取与解析（写路径）

```
fetch_and_store(url)  # 公告页 → 表图 URL → PNG → OCR → 校验 → 落库+快照
_parse_grid_cells     # 纯函数：OCR 单元格 → [{month, day, rise, lower}]
_validate_rows        # 校验闸门（见 §4）
insert_batch          # 只追加一个批次（OR IGNORE 幂等）
write_snapshot        # DESIGN/flag_schedule_snapshot_<date>.csv（同日重跑覆盖）
_ocr_image            # rapidocr 懒导入（查询路径零 OCR 依赖）
```

### 3.2 存储

| 介质 | 位置 | 口径 |
|---|---|---|
| SQLite 库表 `flag_schedule` | `data/flag_cache.db`（settings.flag_schedule_db_url） | 只追加批次；唯一约束 (date, rise, lower, fetched_at)；读取按 fetched_at 升序扫描后行覆盖行 = 每 date 最新批次 |
| 快照 CSV | `DESIGN/flag_schedule_snapshot_<日期>.csv` | 人读/审计副本，同日重跑幂等覆盖 |
| 种子 CSV | `DESIGN/flag_schedule_seed_2026.csv`（随仓库分发） | 2026 全年 365 行人工逐格核对值；表空自动灌入（source=seed，幂等跳过已有年份）；候选路径 DESIGN/ → data/ → 模块同目录 |

配置（`app/config.py`）：`flag_schedule_enabled`（False = 查询恒 None 零 IO）、`flag_schedule_source_url`、`flag_schedule_timeout_seconds`、`flag_schedule_db_url`、`flag_schedule_snapshot_dir`。

### 3.3 查询（读路径）

```
get_flag_time(date_iso, category) -> time | None
# category：morning/升旗 → rise；evening/降旗 → lower
# 降级契约：查不到/关开关/坏行恒 None，绝不抛——规划侧按默认日始排
```

## 4. 校验闸门（不合格不落库，旧批次继续服务）

1. 12 个月齐全，每月天数与日历一致（短月空格按日历裁决）；
2. 时刻可解析且在年内极值区间：升旗 4:00-8:00、降旗 15:30-20:30；
3. 相邻两天漂移 ≤ 3 分钟（真表 ≤ 2 分钟/天）；
4. 总行数 = 全年天数。

## 5. 规划引擎接线（三段式第③步）

| 环节 | 位置 | 语义 |
|---|---|---|
| 数据载体 | `VisitItem.fixed_sessions: list[time] \| None`（itinerary/models.py） | 展示层不读；solver 专用精确锚 |
| 装配期打标 | `plan._apply_flag_schedule`，由 `_plan_poi_hours` 调用（所有排程路径的单点 choke） | 天安门广场 + 北京 + `start_date+日序` 查表 → `fixed_sessions=[升旗]`；幂等 |
| solver 锚 | `solver._visit_spec` 尾部：`lo = hi = 旗时分钟` 点域 | CP 与最廉插入双路同语义（插入路 `spec.lo==spec.hi` 直进 occupied 锚块）；**可破 8:30 日始**（镜像「晚二场可破日终」） |
| 晨点豁免 | `solver._is_morning_site` + 兜底游标 12 点跳闸 | 旗时是客观时刻不是引擎节奏——与用户钉同一豁免面，旗后上午继续排点（故宫 8:30 跟进实测） |
| 兜底路径 | `plan._fallback_sequence_times` | `fixed_sessions` 走场次点通道（`sessions=[旗时]`），只落旗时点 |

跳过面：无 `start_date`、查表落空、非「天安门+广场」名（纪念堂/城楼不锚）、非北京、用户自钉。

## 6. 运维

- 每年 12 月官方发新表后跑一次：`python -m app.services.flag_schedule [url]`（默认官方页）；
- 可挂 Windows 计划任务（照 `ops/fetch_weather` 的 `.cmd` 模式，尚未配置）；
- OCR 依赖：`rapidocr-onnxruntime`（requirements.txt 已加；onnxruntime 环境已有）。

## 7. 验证记录（2026-11-14）

- 官方页实测抓取：OCR 结果 vs 人工核对种子 **743/744 逐格一致**；唯一差异 = 披露的修复格 2026-09-21 升旗 ← 左邻 6:00（真值 6:01，差 1 分钟，WARNING 已记录）；
- 端到端：`start_date=2026-11-14` 出行 → 天安门卡片 6:58 开始、故宫 8:30 跟进（插入/CP/兜底三路径一致）；
- 测试：`tests/test_flag_schedule.py` 15 用例全绿（种子查询、只追加批次最新胜出、网格还原全量对种子、校验闸门、URL 提取、离线抓取全链、solver 双路锚定、铁律 19 跳过、装配期打标跳过面）；
- 既有回归：`test_head_slot_rule` 3 处、`test_plan_agent` 3 处失败为分支在途改动（`DAY_START_MINUTES` 9:00→8:30）所致，与本模块无关（本模块 diff 纯增量）。

## 8. 遗留与路线

- 年度刷新尚未挂计划任务（§6）；2027 年表发布后首跑需盯一次 WARNING（OCR 坑形态可能随版式变化）；
- 降旗时刻暂只入表展示备用，未做「广场闭场后不排天安门」约束（当前产品无此诉求）；
- 若官方未来改用文字表格/接口发布，`fetch_and_store` 解析层可换、存储与引擎接线不动。
