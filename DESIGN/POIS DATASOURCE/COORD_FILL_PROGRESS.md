# POIS 坐标/必要列补全进度（COORD_FILL_PROGRESS）

> 自动化任务每 2 分钟一轮，从本文件断点续跑。完成判定见文末。
> 创建：2026-10-30 首轮盘点。

## 全量盘点（2026-10-30 首轮）

### A. 应用侧 pois（PostgreSQL chinatrip，共 3998 行）

`location` 为空 **614 行**（wgs84 成对写，无单独缺口），按 source：amap 543 / 5a 47 / show 12 / baidu 10 / unesco 2。其中 city 也为空 42 行（B-2 专项，已全部回填 city）。

**回填工具**：`python ops/backfill_coords_driver.py [--limit N] [--extras]`（在 app.jobs.backfill_locations 之上的续跑包装：miss 台账 ops/backfill_coords_missed.txt 防止对死配额行烧配额；--extras 补 KNOWN_CITIES 池外行）。底层：地址优先走百度 geocode，无门址退一级城市+名字查询；检索链 amap>tencent>baidu 配额自动降级；fill-empty 不覆盖已有值。

**选行 bug 修正（2026-10-30）**：`backfill_locations.select_rows` 的非餐饮过滤 `~category.ilike(...)` 遇 NULL 类别求值为 NULL，把 553 行无类别骨架行整批误排除（选中数 2 → 修复后 485）。tests/test_backfill_locations.py 12 项全绿。

### B. CSV 审阅包侧（DESIGN/POIS DATASOURCE）

| 文件 | 缺口 | 处理方式 | 状态 |
|---|---|---|---|
| 01_国家级旅游休闲街区_全四批204.csv | city 空 150 行 | 从名字解析市+区（格式对齐第一批：直辖市只写区名；兵团行=师/市），204/204 补齐 | ✅ 完成 |
| 13_4A级旅游景区_官方汇编4674.csv | city 空 50 行（西藏+青海 4A 批） | 逐行映射属地（州/县短名，格式对齐文件既有行）；林则=工布江达县、象雄美朵=拉萨堆龙德庆区 经 WebSearch 核实，其余知识库+geocode 抽验，50/50 补齐 | ✅ 完成 |
| 04_演艺演出_主要旅游城市.csv | venue 空 2 行 | 唐宫乐宴=隋唐洛阳城·应天门；红秀《延安 延安》=枣园文化广场·东方红大剧院（WebSearch 核实，注意不是延安大剧院），2/2 补齐 | ✅ 完成 |
| 其余 CSV（02/03/04名胜区/05镇/05intl/06村/07国保/09预约） | 必要列无空值 | — | ✅ 无缺口 |

CSV 回填前备份：`_src/*.pre_coordfill_2026-10-30.backup.csv`（01/13/04 演艺三件）。

## 断点状态（2026-10-31 终态）

**TASK COMPLETE（2026-10-31）**

- DB：`location` 为空 614 → **97 行**（填了 517 行）。97 = 70 inactive（按设计不补）+ 27 active 已记 miss 台账（每行一次尝试+原因，见下）。
- DB 侧另修：`select_rows` NULL 类别选行 bug；42 行空 city 补齐（其中 ~15 行由此进入规划池被正常补全坐标）。
- CSV 侧：01 街区 city 150、13_4A 西藏青海 city 50、04 演艺 venue 2 —— 全部补齐并备份（见上表）。
- 测试：tests/test_backfill_locations.py + test_coords.py 共 30 项全绿；ruff check/format 绿。

### 渠道诊断（2026-10-31）
- baidu geocode：配额按日重置，正常（本轮主力，填了绝大多数行）。
- baidu/tencent search：当日配额极小/烧尽，只能零星命中。
- **amap search：HTTP 200 但返回阿里风控验证页（bixi.alicdn.com/punish HTML）——key 或出口 IP 被风控拦截，非配额问题，不会随日重置自愈**。需要到高德控制台核查 key/IP 后检索链才恢复；恢复后可清空 ops/backfill_coords_missed.txt 整体重试一轮，27 行 miss 里预计能捞回一部分。

### miss 台账（ops/backfill_coords_missed.txt，27 行）
每行格式 `source_poi_id 原因`。原因：geocode（含城市+名字退一级查询）未命中或不近城心，且检索链当时不可用（amap 风控 + tencent/baidu 配额尽）。按「同一失败行最多重试一次」原则不再自动重试。

### 复跑追记（2026-10-31 00:50，独立会话审计+修复轮）
- baidu geocode 当日配额重置后按文档预案清台账整体重试（台账备份 `ops/backfill_coords_missed.txt.bak-20261031`）：18 池行填 14 + 9 池外行填 9 + 手工异名 geocode 填 3（周口店北京人遗址公园←周口店遗址博物馆点位、阿拉善盟胡杨林←额济纳胡杨林旅游区、五大连池←五大连池风景区，均 level=旅游景点）。**active 空坐标 27 → 1**（唯一残留=木兰水镇 ct_武汉_129，geocode 仅城市级兜底拒填，已在台账记原因）。amap 检索仍风控（non-JSON body），未参与。
- 其余列修复：enrich_heuristics 补餐饮行名称护栏（_FOOD_NAME_MARKS，修「解放碑店→碑→attraction」误分类，20 项测试绿+2 行误分类已回滚）；indoor/rain_ok heuristic 层填 9、intro Wikidata 填 1；GLM 依赖项（name_en 23 / address_en 300 / indoor llm ~48 / intro llm 12）因 GLM 5 小时限额 02:23 重置，已排 02:35 自动化一轮。CSV 审阅包必要列复核无缺口。

### 复跑终态（2026-10-31 上午，本会话补记——与上方 00:50 独立会话轮衔接）

- 独立会话轮残留的唯一一行 **木兰水镇（ct_武汉_129）已由本会话 `ops/rescue_miss_coords.py` 名字直查补上**（114.424, 30.953，黄陂区木兰水镇，合理）。
- **pois 侧终态：`location` 为空 = 70 行，全部为 inactive 墓碑行（按设计不补）；active 行空坐标清零**（共填 544 行）。
- 著名点位坐标合理性抽查通过：崇圣寺三塔/白公馆/雨花台/三潭印月/深圳湾体育中心/周口店/额济纳胡杨林/五大连池/木兰水镇 均与期望偏差在景区范围内。
- **miss 台账已清空**（4 条记录对应行全部已有坐标，历史备份：独立会话的 `ops/backfill_coords_missed.txt.bak-20261031` + git）。
- 新增 ops 工具：`rescue_miss_coords.py`（miss 行 geocode 查询变体救援：名字直查/纯城市+名字/门址，命中校验拒收省级/城市级兜底，只作补链不替代检索链）。

### ⚠️ 并行会话提示
本轮存在**两个会话同时执行本任务**（本会话 + 00:50 独立审计会话），fill-empty 幂等语义下无数据损坏，但台账有写竞态。建议只保留一个会话/自动化跑此类任务；本会话的每 2 分钟调度已完成使命，可删除。

## 完成判定（达成 · 终）

- pois 侧：空坐标仅剩 70 inactive 墓碑行（按设计；如需启用某行，status 改回 active 后跑 `python ops/backfill_coords_driver.py` 即自动补坐标）✓
- CSV 侧：必要列无空值 ✓（含独立会话轮的 indoor/rain/intro/name_en 等列修复，见其追记）
- 测试 + ruff 绿 ✓
- **无需继续每 2 分钟调度**。amap 风控（punish 页）仍待高德控制台人工处理，属独立基建事项。
