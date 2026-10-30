# POI 功能标签批打（2026-10-29）

> 命题「I want to label the objects of the city so that it can be proposed
> precisely, such as putting show for city show」的落地留档。用户当日逐条
> 拍板词表与判定源（见 §2 拍板记录）；关联：[show_booking_design
> §S5 晚间档](show_booking_design_2026-10-26.md)、[POIS DATASOURCE
> README](POIS%20DATASOURCE/README.md)、planning_engine_upgrade（tier 链）。

## 1. 设计

**source 是「出身」，标签是「玩法」。** 现有 proposal 链按 source/tier 选
点（_source_tier），但用户愿望是玩法词——「看演出」「citywalk」「逛古镇」。
愿望落实先查 POIS 底库（2026-10-24 拍板），而底库 LIKE 只打
name/category：《驼铃传奇》秀 名称无「演出」二字、「思南公馆街区」无
「citywalk」内核，泛称愿望落不到对的点上。故给 `pois.tags` 追加**受控
功能标签**（多值），读侧愿望词 → 标签检索。

### 1.1 词表（受控，v1）

| 标签 | 玩法 | 判定源（依次全过） | 主数据 |
|---|---|---|---|
| `show` | 城市演出 | source=show → tags show → category=entertainment → best_visit_time=show → 名称内核词¹ | 04_演艺演出（50 行） |
| `citywalk` | 街区漫步 | source=street → tags 含「街区」 | 01_国家级旅游休闲街区（204 行） |
| `historical_town` | 古镇名镇 | source=histown → tags 含「名镇/名城」 | 05_中国历史文化名镇（312 行；名城体系入库后同键覆盖） |
| `unesco` | 世界遗产 | source=unesco → tags 含 unesco/「世界遗产」 | 08_UNESCO（61 行） |
| `5a` | 5A 景区 | source=5a → tags 含 5a | 02_5A（359 行） |

¹ show 名称内核：演出/剧场/剧院/演艺/马戏/杂技/歌剧院/实景秀/情景剧/
千古情/长恨歌/变脸/川剧；护栏：博物馆/博物院/纪念馆/陈列馆/美术馆/故居/
书院/景区/旅游区/度假区/风景区/公园——川剧博物馆≠演出、宋城·千古情
景区≠千古情演出。

### 1.2 铁律

- **一行可多标签**（用户拍板）：规则依次全过、并集落 tags——华清宫
  《长恨歌》演出 并入 5a 行 → `show`+`5a` 双标。
- **只增不删、幂等**：词表外标签不动，重跑零变化；tags_source='labels'
  后写留痕（import 作业同惯例，既有 mct/mohurd/show 等溯源被本轮覆盖）。
- **打标不搬 source**：source/enrich/tier/refresh 活链零变化；读侧
  hit_tier/_TIER_BOOST 语义不动（unesco/5a 标签与既有 tier 读法同口径，
  只是持久化）。
- **inactive 行跳过**；dry-run 只统计。

### 1.3 读侧接线

| 触点 | 改动 |
|---|---|
| `poi_details.search_keyword` | tokens 对 name/category LIKE 之外，愿望词按 `_LABEL_TOKENS`（演出→show、citywalk、古镇→historical_town、世界遗产→unesco、5a）打 tags（DB：`cast(tags AS VARCHAR) LIKE '%"show"%'`；内存回退同语义）；命中行返回 `tags` 字段；标签命中在「精确名」之后、「有坐标/类别」之前参与排序 |
| `plan.CATEGORY_SEARCH_KEYWORDS` | +看演出/演出/看秀/show→演出、城市漫步/citywalk/city walk/压马路→步行街、逛古镇/古镇→古镇 |
| `plan.KEYWORD_LABEL_TOKENS` | 检索词→标签内核（演出→[show]、步行街→[citywalk]、古镇→[historical_town]）；`_poi_library_lookup` 把标签并进底库检索 tokens |
| `plan._cand_is_show`（新，收口） | 演出候选判定唯一入口：category=entertainment ∨ bvt=show ∨ source=show ∨ tags 含 show——`_source_tier` tier 5 与 `_deterministic_selection` 晚间档共用；amap 源川剧院（标签补判行）从此按末日演出档收尾，不占白天池 |
| V0 LLM 提示词 | 「晚间演出类」判定说明同步 tags 口径 |

### 1.4 落地与用法

- 作业：`python -m app.jobs.label_pois [--dry-run]`（幂等，可入每日链）。
- 愿景链路：用户「晚上想看场演出」→ 愿望词「看演出」→ 检索词「演出」
  +标签 show → 底库吃 04 源/标签行（名称缺内核词也命中）→ 确定性选点
  按末日演出档收尾 → 行程卡演出直达（既有 P0 链）。
- 测试：`tests/test_label_pois.py` 10 项（词表判定/多标签并集/幂等/
  inactive 跳过/溯源覆盖）+ `test_poi_details` 2 项（标签检索/排序）+
  `test_algo_v0` 2 项（标签行晚间档/tier 同档）+ `test_plan_agent` 2 项
  （玩法词/标签 tokens）；变脸专名愿望不吃品类词的既有拍板回归保持。

## 2. 拍板记录（2026-10-29，用户逐条指令）

1. 城市对象打标使提案精准（「PUTTING SHOW FOR CITY SHOW」）。
2. 01 国家级旅游休闲街区 → `citywalk`。
3. 05 中国历史文化名镇/名城体系（source=histown）→ `historical_town`。
4. UNESCO 来源 → `unesco`；5A 来源 → `5a`。
5. **一行可多标签**（ONE SITE CAN BE MARKED FOR MULTIPLE LABELS）。
6. 每 2 分钟调度推进直至完成（自动化已在任务全绿后自删）。

## 3. 后续（未做）

- `show` 词表扩类型（音乐会/演唱会/脱口秀）按 04 CSV 扩量再议；
- H5 气泡/详情出参展示玩法标签徽章（tags 已随 detail 出参，前端消费待排）；
- `citywalk` 线路级（多点位串联）标签与 12 小红书 citywalk 路线行的联动；
- 名城（国家级历史文化名城，城市级）体系如入库，`historical_town` 键值
  复用（判定已含「名城」tags 痕）。
