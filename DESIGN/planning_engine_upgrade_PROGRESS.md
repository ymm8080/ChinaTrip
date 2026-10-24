# 规划引擎升级 0009 — 开发进度交接（活文档）

> 用途：任何新会话读本文件即可无损接续开发。每完成一项立即更新。
> 计划：[planning_engine_upgrade_2026-10-24.md](planning_engine_upgrade_2026-10-24.md)（v1.3 已审查通过，用户指示"keep developing till complete + fan out subagents"）
> 分支：feat/v24-trip-center ｜ 工作区另有他人未提交 WIP（retime/weather/osm/tag_quality）——**不要动那些文件的既有改动，不要自行提交**

## 已完成 ✅

| # | 任务 | 产物 |
| --- | --- | --- |
| 1 | 迁移 0009 | `alembic/versions/0009_planning_engine_enrichment.py`（pois +14 列 / restaurants +12 列 / poi_reviews / poi_stats；注意 poi_reviews 的正文字段 DB 列名 `text`、ORM 属性名 `body`——避开 sqlalchemy.text 冲突） |
| 1 | models.py | Poi/Restaurant 新列 + PoiReview/PoiStat 两模型（models.py:214 起） |
| 2 | PoiDetailStore.upsert 扩签名 | 新 kwargs：rating/rating_source/rating_count（**刷新语义**）+ photos/phone/website/district/business_area/suggested_duration_min/duration_source/review_tags/review_tags_source/ticket_price_min/max/ticket_source（**只填空语义**） |
| 2 | PoiDetailStore.top_pois_in_city(city, limit=30, *, exclude_food=True) | 确定性排序 `rating × log2(1+rating_count) × 标签加成(unesco/5a/michelin/black_pearl ×1.5)`；返回 dict：source_poi_id/name/city/category/address/opening_hours/source/rating(float|None)/rating_count/tags/best_visit_time/suggested_duration_min/indoor/rain_ok/review_tags/intro(≤60字)/location(**(lon,lat) 元组**，注意与 amap 的 dict 形状不同)；DB 失败自动内存回退 |
| 2 | search_keyword rating 修复 | 原来恒 None，现返回 row.rating |
| — | 测试 | `pytest tests/test_poi_details.py tests/test_models.py tests/test_poi_seed.py tests/test_poi_backfill.py` 43 passed |

## 进行中 / 待做（按序）

- [ ] 3. refresh_pois 写回富化字段（A1-A3/B1）：`place_hours`/`search_hours` 返回值里已有 rating；把 amap v5 detail 的 photos/phone/website/district(从 adcode 或 business area 字段) 接进 upsert 调用
- [ ] 4. ctrip_hours 扩正则（A4/A5/A6/B3）：详情页同页解析 建议游玩时长/评分/点评数/点评标签 chips/门票价 → 新方法 `detail_fields_for(city,name)` 返回 dict，refresh_pois 消费
- [ ] 5-7. **引擎（agent 开发中）**：_collect_candidates 库优先 top_pois_in_city（库≥10 跳过 amap）、_select_pois listing 全字段+reason、_assemble_plan 餐厅 v0 插入（recommend_restaurants 已存在 restaurants.py:256 未接线）
- [x] 13. best_visit_time→开窗（8.2.1 完成 2026-10-24）：`_visit_spec` 按 `_BEST_VISIT_WINDOWS`（morning 08-12/afternoon 12-17/evening 17-21/sunset 16-19/sunrise 08-10:30）先于 PoiHours/pinned 收窄开窗，未知枚举按 any 不约束；test_solver.py +5 用例，solver/rules/time_slot 48 passed
- [ ] 14. **solver（agent 开发中）**：travel matrix（haversine×1.3÷80m/min）、poi_hours 传入
- [ ] 8. 互动端点：POST /plan/{sid}/items/{id}/vote（👍=poi_stats.thumbs_up，👎=trip_items unwanted 路径已有）、POST /trip-items/{id}/visit（visited 状态）、POST /pois/{id}/review（写 poi_reviews）
- [ ] 9. links/batch 批量导入（H5 侧为主）
- [ ] 10. aggregate_poi_stats 夜作业（trip_items GROUP BY 全量重建）+ ops cmd
- [ ] 11. backfill_indoor_rain（类别启发式层先做）
- [ ] 12. review_summary LLM 蒸馏（mock LLM 下跳过）
- [ ] 15. services/itinerary/geo.py 商圈/坐标聚类分日
- [ ] 16. 天气感知重排建议
- [ ] 17. H5 index.html：卡片反馈/打卡/点评卡/批量导入
- [ ] 18. 品类疲劳 + 计划级查全率（5A/UNESCO 白名单 vs 计划）
- [ ] 19. 约束回归测试（同店不重复/每天≤4/步行≤15km=铁律6）
- [ ] 20. 全量 pytest（`--cov=app --cov-fail-under=75`）+ ruff 通过

## 关键约定（新会话必读）

- Python：`.venv/Scripts/python`（Windows）；测试 `python -m pytest`；lint `python -m ruff check app tests`
- 注释/commit 中文；现有代码风格紧凑
- `poi_stats` 写入走 DB 失败静默（同 poi_details 模式）；dev 无 PG 时内存降级
- solver 契约：`solve_plan(plan, *, poi_hours, travel_minutes, time_budget_seconds)` 已支持 travel_minutes（AddCircuit 目标）——8.2.2 只需在 plan.py `_solve` 构矩阵传入
- 铁律 19：pinned 条目 solver 不动；餐厅插入只落用餐空窗（铁律 20，restaurants.meal_window/rank_by_detour 现成）
