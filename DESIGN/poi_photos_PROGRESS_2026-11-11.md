# POI 照片功能施工进度（2026-11-11，调度器每 2 分钟一拍）

设计文档：`DESIGN/poi_photos_functional_design_2026-11-11.md`
分支：feat/v24-trip-center-uat ｜ 锁：`CHINATRIP CODES/.poi_photos_lock`

| # | 任务 | 状态 | 证据 |
|---|---|---|---|
| 1 | 迁移 0020 + models 两列 | ✅ 完成 | `alembic/versions/0020_poi_photos_fetch.py`（w12_0020，`alembic current`=head）；`app/models.py` Poi/Restaurant 各加 photos_fetched_at/photos_fetch_fail；ruff check+format 过；活库 upgrade 成功 |
| 2 | poi_photos 服务 + fetch/report-dead 端点 | ✅ 完成 | `app/services/poi_photos.py`（链序：amap v5 id → amap v3 按名搜 → wikimedia P18；normalize_photos ≤8 去重 http(s)；COOLDOWN 24h）；`app/api/pois.py` 两端点（尝试即落戳、只填空、失败 logger.warning）；`tests/test_api_poi_photos.py` 9 用例 + 既有 16 用例全过（25 passed） |
| 3 | backfill_photos 批量预热 job | ⬜ 未开始 | 复用 enrich_amap_detail 骨架 + source_tier.SOURCE_PRIORITY |
| 4 | F5 来源标注收口 | ⬜ 未开始 | enrich_amap_detail 补 photos_source='amap'；历史 1,449 行先抽 20 核域名再 UPDATE；backfill_intro 头注删改 |
| 5 | H5 找图按钮 + report-dead 接线 | ⬜ 未开始 | index.html / i18n.js / sw.js v79→v80 |
| 6 | 测试收口 + 全量回归 + 择块提交 | ⬜ 未开始 | 三提交：迁移+模型 / 端点+job+测试 / H5+文档 |

## 备注

- `app/models.py` 已不在并行 WIP 名单（并行会话已提交），本拍改动是干净 hunk；`i18n.js` 仍在 WIP 名单，#5 时须择 hunk。
- FastAPI 新版 `_IncludedRouter` 懒挂载：`app.routes` 探测不到 pois 路由是假象，`router.routes` 已确认四条齐。
- 百度/腾讯 place_hours 代码路径均无 photos 解析，未入链；待实测探针确认厂商响应真含图再补（记入设计 §2 注记）。
- 迁移已应用到活库（alembic upgrade head 成功）。
