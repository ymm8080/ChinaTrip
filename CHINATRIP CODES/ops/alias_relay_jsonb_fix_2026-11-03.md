# 别名接力收口 + JSONB 空值根修（2026-11-03）

> 背景：`enrich_llm_web` 别名/时长接力（R1–R6）在 11-01 第四轮中途死亡，
> 11-03 07:21 由并行会话手工重启（PID 2540 / worker 8048，`--limit 5000
> --concurrency 2`）。本轮做三件事：JSONB `'null'` 脏值全表清洗、ORM 层根修、
> 接力自动化补位（此前无任何定时任务会拉起该作业）。

## 1. 覆盖率快照（DB 为唯一真值，不读时回源）

| 指标 | 值 |
| --- | --- |
| active POI | 15,102 |
| `name_aliases` 已填（`jsonb_typeof='array'`） | 2,258 → 2,259 |
| 覆盖率 | 15.0% |
| `suggested_duration_min` 已填 | 12,374 → 12,375 |
| 其中 `duration_source='llm_web'` | 288 |

口径说明：`is not null` 不可用——JSONB 里的 JSON `'null'` 标量既不是 SQL NULL
也不等于空数组，必须用 `jsonb_typeof(col)='array'` 才算真正填过。池子在两次会话
之间从 12,863 涨到 15,102（并行会话灌入 4A/国保/名村/演出等新批次），所以百分比
不涨属正常，绝对量在涨。

## 2. 现象：JSONB 列出现 JSON `'null'` 标量

`jsonb_typeof` 扫描发现大量列取值为 JSON `'null'`（不是 SQL NULL，也不是 `[]`）：

- `pois`：tags 3,749 / review_tags 3,328 / review_tags_en 3,372 / name_aliases 3
- `restaurants`：tags 4,544 / review_tags 5,080 / signature_dishes 5,080 /
  meal_periods 5,080 / review_tags_en 5,080 / signature_dishes_en 5,080

危害：读路径上 `if row.tags:` 判定为假没事，但 `jsonb_array_length(tags)`、
`tags @> '[...]'`、`array_length` 类聚合会直接报错（标量无长度）；且 `is not null`
统计会把它们误算成"已填"，污染覆盖率报表与补数调度。

## 3. 根因：SQLAlchemy JSONB 默认把 Python `None` 写成 JSON `'null'`

写路径统一走 ORM，`mapped_column(JSONB)` 在序列化 `None` 时写入 JSON `'null'`，
而不是 SQL NULL。这也解释了为什么清洗后过一阵又冒出新脏值——不是存量遗留，是
每条 `INSERT/UPDATE` 的 ORM 默认行为在持续生产。逐个 writer 打补丁不收敛，
所以在模型层统一修。

修复：`app/models.py` 27 处 `mapped_column(JSONB)` →
`mapped_column(JSONB(none_as_null=True))`（SQLAlchemy 2.1.6 已验证
`JSONB(none_as_null=True)` 属性生效）。存量脏值用 `jsonb_typeof` 判定后
`SET NULL` 清洗，脚本幂等可重跑，清洗后全表取值只剩 `array` 或 SQL NULL。

## 4. 接力自动化：补一个带守卫的每日低峰驱动

此前 20 个 `ChinaTrip\*` 定时任务里**没有任何一个**会拉起 `enrich_llm_web`
（11-03 07:21 那次是并行会话手拉），接力全靠有人守着——这是上一轮断档的直接
原因。新增：

- `ops/poi_alias_llm_daily.cmd`：`--limit 1000 --concurrency 2`，日志
  `devlogs/poi_alias_llm.log`，作业本身只填空列、按评分优先，天然可续跑。
- `ops/poi_alias_llm_guard.ps1`：检测 `python*` 进程命令行含
  `app.jobs.enrich_llm_web`，存在则 `exit 1` 让驱动走 skip 分支。
- `D:\CHINATRIP\poi_alias_llm_daily.cmd`：无空格壳（`schtasks /TR` 遇
  `CHINATRIP CODES` 里的空格会截断成 `D:\CHINATRIP\CHINATRIP`，这是既有坑）。
- 任务：`ChinaTrip\POI alias llm daily` @ 05:20（错开 02:00 refresh /
  03:40 stats / 03:55 hours+rating / 04:10 en / 06:30 osm）。

**并发红线**：GLM 是共享账号、还服务线上 planner，所以并发固定 2，且守卫保证
同一时刻只有一份 `enrich_llm_web`——当前手工实例在跑时，05:20 的驱动会打印
`skip: enrich_llm_web already running` 并退出（已实测）。

## 5. 验证

- `ruff check app/models.py` / `ruff format --check`：全绿（两处行尾注释改为
  独立注释行以满足 E501）。
- `pytest tests/test_models.py tests/test_import_museum_grades.py
  tests/test_import_shows.py tests/test_import_intl_platforms.py
  tests/test_poi_seed.py`：52 passed。
- 活性探针 150s：aliases 2,257 → 2,258、worker CPU +3s，确认手工实例在真干活
  （账户争用下实测 ~24–60 行/时，不是卡死）。
- 守卫整链：`guard exitcode=1` → 驱动 `wrapper exitcode=0` → 日志写入 skip。
- 质量抽检：莫高窟→千佛洞/敦煌石窟/敦煌莫高窟；拙政园→补园/归田园居 +
  `Humble Administrator's Garden`；東望洋燈塔→松山灯塔/东望洋炮台及灯塔 +
  `Guia Lighthouse`——俗称/古称/英译命中，正是别名层的目标价值。个别行返回空
  数组（如沈阳东陵公园）属模型保守，可后续按 city+category 提示词再调。

## 6. 未做 / 依赖外部

- `enrich_baidu_map` / `enrich_tencent_map` 需个人开发者认证；
  `enrich_amap_detail` + business_area 需高德企业档。均需用户侧资质，非脚本可控。
- 别名质量未做全量人工复核，只抽检 18 行；如需可扩成按 category 分层的抽检脚本。
- 覆盖率百分比会被并行会话的新灌批次稀释，看绝对量更有意义；如需真实进度，
  应按 `category` 分开统计（hotel/restaurant 与景区别名策略不同）。

## 7. 复现命令

```powershell
# 在 D:\CHINATRIP\CHINATRIP CODES 下
.\.venv\Scripts\python.exe ..\tmp_t\alias_count.py       # 覆盖率 + jsonb_typeof 分布
.\.venv\Scripts\python.exe ..\tmp_t\jsonnull_fix.py      # 存量 'null' → SQL NULL（幂等）
.\.venv\Scripts\python.exe ..\tmp_t\alias_quality_sample.py  # 别名抽检
cmd /c "D:\CHINATRIP\poi_alias_llm_daily.cmd"            # 驱动（在跑则 skip）
```
