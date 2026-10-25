# 天气流水线 + 华氏度 + 行程落 PG · 测试手册（2026-10-25）

> 覆盖 2026-10-24~25 交付：天气每日刷新流水线（三班 + 开站巡检）、C/F 双温标、
> 旧行程出发日期自愈、行程/心愿单落 PG（迁移 + 写穿）。
> 每个场景标注：**[AUTO]** 已有自动化（引用测试名，CI 可回归）｜**[MANUAL]** 需真人执行
> （H5 浏览器流 / 定时任务 / 真实外部服务）。
> 环境：`.venv/Scripts/python -m pytest`（全量 1165，唯一失败 `test_h5_static_gate`
> 为并行会话 i18n WIP，与本批无关）；H5 手工场景访问
> http://127.0.0.1:8000/ （手机 http://192.168.3.15:8000/ ，先 **Ctrl+F5** 清 PWA 缓存）。

---

## 场景一：天气每日刷新流水线（三班 + 开站兜底）

### 1.1 三班定时任务注册与运行 [MANUAL·已实测]
- **步骤**：PowerShell `Get-ScheduledTask -TaskPath '\ChinaTrip\' | ? TaskName -like 'Weather*'`
- **预期**：morning 08:10 / midday 11:10 / evening 18:10 三条，state=Ready；
  当日已到点的班次 LastRunTime=当天且 result=0
- **实测**（2026-10-25）：morning 08:10 result=0 ✓、midday 11:10 result=0 ✓（且已按
  行程城市自抓 11 城）

### 1.2 每班抓取范围 = 行程城市（高德）∪ 40 主要城市（Open-Meteo）[AUTO]
- **步骤**：`python -m app.jobs.fetch_weather`（默认无行程时高德跳过、OM 全量）
- **预期**：stats 里 amap 段 `cities` = 行程涉及城市数（trip_cities ∪ store_cities），
  `forecast14.cities`=40；行程为空时 amap 段 cities=0 不报错
- **自动化**：`test_weather.py::test_store_cities_merges_records_and_items` +
  `test_api_weather.py::test_sync_empty_cities_uses_trip_cities` /
  `test_sync_empty_cities_merges_store_cities`

### 1.3 fetched_at 每次刷新盖戳（防 7 天误删）[AUTO]
- **步骤**：upsert 一行 → 把 fetched_at 回拨 3 天 → 再 upsert
- **预期**：fetched_at 恢复到当前；`STALE_DAYS == 7`
- **自动化**：`test_weather.py::test_upsert_refreshes_fetched_at_on_update` +
  `test_purge_stale_deletes_old_rows`

### 1.4 开站巡检刷新（/api/weather/sync）[AUTO]
- **子用例**（`test_api_weather.py`）：
  - 新鲜城市跳过刷新：`test_sync_fresh_city_skips_refresh`
  - 过期城市内联刷新：`test_sync_stale_city_refreshes`
  - 未收录城市静默跳过：`test_sync_unknown_city_silently_skipped`
  - 空 cities 走行程城市并集：`test_sync_empty_cities_merges_store_cities`
- **实测**（2026-10-25 上午）：`POST /api/weather/sync {"cities":[]}` 返回 **11 个真实
  行程城市**（北京/上海/南京/苏州/杭州/厦门/广州/三亚/重庆/成都/西安），
  fetched_at 全为当天 = 午班作业已自抓，refreshed=False

### 1.5 开站巡检页面表现（toast + 天头重绘）[MANUAL]
- **前置**：把某行程城市 weather 行的 fetched_at 改成昨天（或等跨天）
- **步骤**：浏览器 **Ctrl+F5** 打开 http://127.0.0.1:8000/
- **预期**：右上 toast「🌤 天气已自动刷新 · HH:MM」；行程卡天头出现
  「图标 高温°/低温°C · F°/F°」；无需任何保存动作

### 1.6 双源新鲜度口径 [MANUAL·已实测]
- **步骤**：`GET /api/weather?city=110000`，对照 schtasks 班次时间
- **预期**：0-3 天走高德（跟班次走），4-14 天走 Open-Meteo（每次运行全量 40 城）；
  高德数据滞后一天属设计行为（行程为空时高德段跳过，省配额；有行程即自愈）
- **实测**：OM forecast14 fetched_at=当天 08:10；高德为昨日（当时无行程），当天
  11:10 午班起已有行程城市的高德新数据

---

## 场景二：华氏度（库 C/F 双存 + 页面双温标）

### 2.1 入库派生华氏（casts + live）[AUTO]
- **预期**：casts 补 `day_temp_f/night_temp_f`（17°C→63°F），live 补 `temperature_f`
  （18°C→64）；非数字留空不阻断
- **自动化**：`test_weather.py::test_upsert_adds_fahrenheit_to_casts_and_live` +
  `test_upsert_fahrenheit_skips_non_numeric` + `test_upsert_insert_then_update`（temperature_f 断言）

### 2.2 页面双温标渲染 [MANUAL]
- **步骤**：规划页打开任一行程（或重新规划一条），看天头
- **预期**：`☀️ 17°/10°C · 63°/50°F`；旧行（无 _f 字段）由前端现算兜底，显示一致
- **核对点**：sw VERSION ≥ v32（Ctrl+F5 后 source 看 `chinatrip-h5-vNN` 缓存名）

### 2.3 E2E 真实抓取含华氏 [MANUAL·已实测]
- **步骤**：`python -m app.jobs.fetch_weather --city 110000` → `GET /api/weather?city=110000`
- **实测**（2026-10-24）：live `14°C→57°F`、cast `17°C→63°F` 全部落库

---

## 场景三：旧行程打开 = 日期 + 天气立现

### 3.1 start_date 链路持久化 [AUTO]
- **预期**：`plan/start` 收 start_date → PlanSession → ItineraryPlan 随快照落库 →
  from-itinerary 重开带回
- **自动化**：`test_plan_agent.py::test_start_date_flows_into_plan` /
  `test_start_date_defaults_to_none` + `test_plan_api.py::test_from_itinerary_opens_ready_session_and_round_trips_save`
  （含保存→重开 start_date 往返断言）

### 3.2 旧行程打开缺省今天（H5）[MANUAL]
- **前置**：一条 2026-10-25 之前保存的行程（无 start_date，实测 315/320 条）
- **步骤**：「行程」页 ✏️ 修改打开
- **预期**：出发日期输入框自动填今天（北京时间）；行程卡每天有「第 N 天（日期）」；
  天头天气正常显示；💾 保存一次后 start_date 永久落库
- **注意**：PWA 缓存——不 Ctrl+F5 会一直看到旧行为

---

## 场景四：行程/心愿单落 PG（写穿 + 迁移）

### 4.1 PG schema（alembic 0015，链到 0017 head）[MANUAL·已实测]
- **步骤**：`alembic current` + information_schema 查列
- **预期**：head=w12_0017；itineraries 有 plan/owner_device_id/owner_account_id/
  share_enabled/share_token；snapshots.plan；trip_items.payload
- **实测**（2026-10-25）：5 列全 OK

### 4.2 数据迁移幂等 [MANUAL·已实测]
- **步骤**：`.venv\Scripts\python.exe ops\migrate_h5_state_to_pg.py`（可重复执行）
- **预期**：`migrated: 320 itineraries (0 skipped), 11 trip items`；
  PG 计数 itineraries=320 / trip_items=13（11 迁移 + 2 既有）；重跑只更新不堆行
- **关键数据**：317/320 条是历史短 id（`it-xxxxxxxx`）——uuid5 确定性代理键落 PG PK，
  业务 id 原样在 plan 文档；自动化 `test_pg_state.py::test_pg_uuid_loose_deterministic_for_legacy_ids`

### 4.3 写穿映射纯函数 [AUTO]
- **自动化**（`tests/test_pg_state.py`，CI 无 PG 全过）：
  `test_record_to_row_values_and_boot_round_trip`（plan 文档往返喂 boot-load）/
  `test_snapshot_to_row_values_freezes_plan` /
  `test_item_to_row_values_keeps_free_string_ids_in_payload`（高德 poi_id 不硬转 FK）/
  `test_pg_uuid_prefix_and_bare_hex` / `test_pg_uuid_rejects_free_strings`

### 4.4 PG 不可达熔断降级 [AUTO]
- **预期**：boot-load 连不上 PG → `_pg_ok=False`，store/service 行为等同纯内存，
  API 不炸；恢复靠重启进程
- **自动化**：`test_itinerary_store_degrades_to_memory_without_pg` /
  `test_trip_items_degrade_to_memory_without_pg` / `test_import_item_memory_fallback_without_pg`

### 4.5 设备行程可见性（迁移后服务重启）[MANUAL·已实测]
- **步骤**：迁移后 `dev_server.cmd restart` → `GET /api/v1/itineraries`（带设备头）
- **实测**（2026-10-25）：dev-yte3rfdh 返回 17 条
- **注意**：**迁移必须在服务启动前完成**（boot-load 只读 PG）；服务先起后迁的话
  再重启一次即可

### 4.6 分享开关写穿 PG [MANUAL·已实测]
- **步骤**：`POST /api/v1/itineraries/{id}/share {"enabled":true}` → 查 PG 行 → 关闭再查
- **实测**：legacy id it-87b03b49 开分享 → PG `share_enabled=true, share_token` 落库；
  关闭 → PG token 清空
- **自动化兜底**：既有 `tests/test_itineraries_api.py` / share 套件（InMemory 注入）全绿

### 4.7 天气巡检看到真实行程城市（迁移终态）[MANUAL·已实测]
- **步骤**：`POST /api/weather/sync {"cities":[]}`
- **预期**：cities 非空（= 真实行程城市并集）且 fetched_at 为当天
- **实测**：11 城 ✓——此前 PG 三表 0 行导致巡检恒空的缺陷已闭环

---

## 已知边界（不是 bug，但验收时要心里有数）

1. **高德只抓行程城市**（配额 ~100 次/日）：行程为空时高德段整段跳过，数据老化到
   7 天被清理；有行程后开站巡检/下一班自动补齐
2. **plan_sessions / accounts 仍在 SQLite**（本期范围外）；SQLite h5_state.db 已停写，
   仅作迁移前数据备份，别手工往里写
3. **trip-items 无 device 隔离**（遗留）：任何设备可见全部心愿单，多用户上线前必须补
4. `test_h5_static_gate` 当前红：并行会话 i18n WIP（zh-CN 词典缺 103 词条），与天气/PG 无关
5. 回滚路径：`get_store()/get_trip_item_service()` 两处 revert 即回 SQLite 写穿；
   PG 新列 additive 无害；迁移脚本可对 SQLite 重复执行
