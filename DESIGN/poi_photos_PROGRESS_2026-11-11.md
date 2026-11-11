# POI 照片功能施工进度（2026-11-11，调度器每 2 分钟一拍）—— ✅ DONE

设计文档：`DESIGN/poi_photos_functional_design_2026-11-11.md`
分支：feat/v24-trip-center-uat（已 rebase 并推送，HEAD 8ce9b58）

| # | 任务 | 状态 | 提交 | 证据 |
|---|---|---|---|---|
| 1 | 迁移 0020 + models 两列 | ✅ | 5b09f28 | w12_0020 head；活库 upgrade 成功；ruff 过 |
| 2 | poi_photos 服务 + fetch/report-dead 端点 | ✅ | 0894e0c | 9 用例过；尝试即落戳/只填空/失败留日志全验 |
| 3 | backfill_photos 批量预热 job | ✅ | 0894e0c | 6 用例过；活库 --limit 10 真跑 9 命中 |
| 4 | F5 来源标注收口 | ✅ | 0894e0c | 悬空 1,452→0（amap 1,667 / ctrip 434）；backfill_intro 头注修正；12 用例过 |
| 5 | H5 找图按钮 + report-dead 接线 | ✅ | 8ce9b58 | JS 语法门 + H5 静态守门全过；sw v80 |
| 6 | 回归 + 覆盖率 + 择块提交 | ✅ | 5b09f28/0894e0c/8ce9b58 | 见下 |

## 回归与覆盖率

- 全量 pytest：**2,878 passed / 4 failed**——4 中 1 个（test_h5_static_gate）是我修掉的 v78 存量违例（`"　"`→`\u3000`，已过）；**其余 3 个（test_engine_constraints×1、test_plan_agent×2）为并行会话 WIP 域存量**：HEAD 本身自相矛盾（其已提交 plan.py 依赖未提交 itinerary/models.py 的 UnplacedCandidate），与照片链无关、零接触。
- 覆盖率：收口前 active 1,650/9,787=16.9% → 标注收口后 1,653/9,830=16.8% → 10 行真跑后 1,662/9,830=**16.9%**（预热 job 已就绪，上量跑 `python -m app.jobs.backfill_photos [--limit N] [--city X]` 即抬）。restaurants 0/5,088（设计非目标，另案）。
- 来源分布：amap 1,667 / ctrip 434 / wikimedia 258，悬空 0。

## 关键发现（给后续会话）

1. **盲标 amap 会误标**：悬空行域分布实测 amap 1,139 / ctrip 313+1——已按域名分两批 UPDATE。
2. **amap v3 `/place/text` 在本机 key 撞 WAF**（AmapPunishedError "bixi punish"）：按名搜路不可靠，v5 按 id 直查与 wikimedia 正常；链内已降级留痕不炸。
3. FastAPI 新版 `_IncludedRouter` 懒挂载：`app.routes` 探测不到子路由是假象，用 `router.routes` 核。
4. models.py/i18n.js 含并行会话 hunk——本次用过滤 patch（`git apply --cached`）只择自己的 hunks，并行 WIP 全程未动。

---

## 增补章节：餐厅照片回源 + 上量预热（2026-11-12，提交 31a2864 已推）

| 事项 | 结果 |
|---|---|
| pois 预热 500 行真跑 | 70 行填图（wikimedia 净增 79），active 有图率 16.9%→**17.6%**（1,732/9,830） |
| 餐厅回源能力 | restaurants 5,088 行**全部无 amap id、无 rating**——v5 按 id 路不存在；接入 v5 `place/around`（keywords+location 3km+名称匹配防错图，独立配额池/风控，text 被罚不影响）；新 job `app.jobs.backfill_restaurant_photos`（只填空+尝试即落戳+配额首撞停不落戳） |
| 真跑两 bug（已修） | ①坐标 WKT（ST_AsText `POINT(lon lat)`）解析缺壳→全 None；②`_Target` 字段名 `lonlat` ≠ 链读的 `location`，错位静默跌回被 WAF 罚的 v3 text——修后 47 照片套件全过 |
| 阻塞：amap 日配额尽 | `USER_DAILY_QUERY_OVER_LIMIT`（个人 key，多 job 共享）——餐厅 around 批量与 pois 无图行 v5 补图**明日重置后续跑**：`python -m app.jobs.backfill_restaurant_photos --limit 500` / `python -m app.jobs.backfill_photos --limit 500` |
| 探针结论 | **百度证伪**：place/v2 search+detail (scope=2) 只回 `detail_info.image_num`（计数）与 `detail_url`（网页），无图 URL 字段，第三链剔除；**腾讯未证实**：key 日配额尽（status 121），detail 零合法调用，探针脚本在 `_tmp_probe/`，次日重跑即可补证 |
| 明日待办 | ①餐厅批量（around 池）②pois 1,317 有 id 行 v5 补图 ③腾讯 detail 补探 ④text WAF 是否解封复查 |

本次并行会话 WIP（amap_client.py 人均消费链 27 行、plan.py 等）零接触；amap_client.py 保持未提交状态归其会话。
