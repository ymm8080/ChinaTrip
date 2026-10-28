# 一键切图商收口（2026-10-28）

分支：feat/v24-trip-center ／ 前置：2026-10-27 高德技术费转百度（`map_provider`
工厂 + `BaiduClient` 同构实现，`MAP_PROVIDER=baidu` 已在 .env 生效）。

## 1. 开关

```ini
MAP_PROVIDER=amap   # amap | baidu
BAIDU_AK=...
BAIDU_BASE_URL=https://api.map.baidu.com
```

`app/services/map_provider.py::build_map_client(settings)` 是唯一分派点；
两客户端方法同构（鸭子类型）、共用 `AmapError/AmapTimeoutError` 异常体系，
API 层错误码（amap_timeout 等）零改动。

## 2. 本轮收口（此前仍硬编高德的接触点）

| 接触点 | 处理 |
| --- | --- |
| deeplinks（amapuri:// 打车/自驾 handoff） | `compose_deeplink(provider=)`；百度 `baidumap://map/direction`（lat,lng、coord_type=gcj02）；百度无公开打车 scheme，taxi 档用驾车承接；调用方传 `settings.map_provider` |
| `leg_source` 硬编 "amap" | 客户端加 `vendor` 属性，规划器按注入客户端标注（wire Literal 加 "baidu"；trip_export 与前端标签改图商中性「地图实测」） |
| 前端步行外链（uri.amap.com 硬编） | 新增 `GET /api/v1/amap/provider`；H5 启动预取 → 百度落 marker 页 |
| `jobs/import_chinatravel` 定位 | 改走工厂（`map_ready` 闸） |
| `jobs/fetch_weather` | weather 源轴 `--src` 缺省本就 = `map_provider`；补 `map_ready` 闸（双轴设计不变） |
| .env.example(.intl) | 补 MAP_PROVIDER/BAIDU_AK/BAIDU_BASE_URL 样例 |

## 3. 仍有意直连 AmapClient（不随开关切换）

`refresh_pois` / `enrich_amap_detail` / `poi_backfill`——POI 库
`source/amap_id` 列语义绑定高德；百度切换时的下一片迁移
（`BaiduClient.uid → source_poi_id`）。清单见 `map_provider.py` 模块注释。

## 4. 同批修的相邻缺陷（心愿单定城，用户拍板「心愿单条目尽量带城市」）

西湖漏进重庆行程事故（2026-10-28 晨）根因链：
①心愿单存在 `city=null` 的测试遗留「西湖」行 → `_absorb_wishlist` 空城过滤
放行 → 注入必去；②`_collect_candidates` 高德定位杭州（行程外）后**落穿**
「按名称占位」支，被排除的西湖以占位名混进 day1；③后续名称匹配还把普洱
思茅区同名小 POI 粘到占位上。

修复：
- `_absorb_wishlist` 空城专名行先 `_resolve_wish_city` 定城：行程外→写回
  城市并跳过（行自愈）；品类愿望保持空城就近落实（2026-10-24 拍板）；
  `CATEGORY_SEARCH_KEYWORDS` 补 博物馆/博物馆人文（避免模糊写回宜昌错城）。
- `_collect_candidates`：必去专名真身确在行程外（`_same_site`）→ 真排除＋
  心愿单定城回填；模糊错配（junk→NTT 香港）保留用户原词占位（既有拍板）。
- `_resolve_wish_city` 库名双向包含同城唯一兜底（不依赖高德配额）；
  `WISH_CITY_HINTS` 补 西湖→杭州。
- 新增 `_backfill_wish_city`：只补空城行、best-effort。

数据修复：PG trip_items 西湖空城行（已自愈为杭州）＋ 删除 URL 垃圾行 1 条。

## 5. 门禁

ruff 全绿；pytest 全量 1397 passed——唯一失败
`test_plan_api.py::test_refresh_legs_backfills_missing_locations` 属并行会话
未完成的 TDD 用例（实测腿回填坐标特性未实现），与本批无关。
