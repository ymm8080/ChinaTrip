# ChinaTrip 数据库设计（全库）
> 版本：v2.0 ｜ 生成日期：2026-11-13 ｜ 事实来源：生产 PostgreSQL `chinatrip` 实时 schema（information_schema）
> 覆盖 public schema 全部表 + 视图；重点展开 2026-11-13 落地的「行程头 / 明细 / 变更日志 / 心愿单」数据模型。

## 0. 总览
- 表 36 张，视图 3 个
- 迁移：alembic 管理（`alembic current` = 最新 head）；2026-11-13 行程域新增 `w12_0023`~`w12_0028`
- 关联主线：`itineraries.id` ← `itinerary_days/itinerary_items/itinerary_snapshots/itinerary_change_log`；`trip_items.itinerary_id` → `itineraries.id`（未保存的工作行程为空，业务号存 `itinerary_ref`）

## 1. 表清单
| 域 | 表 | 行数 | 一句话 |
| --- | --- | ---: | --- |
| 行程域 | `itineraries` | 8 | 行程头（TRIP HEADER） |
| 行程域 | `itinerary_days` | 20 | 行程逐日（第几天 / 宿城） |
| 行程域 | `itinerary_items` | 100 | 行程明细（日期·时段·点位·时长·备选） |
| 行程域 | `itinerary_snapshots` | 10 | 不可变版本快照 |
| 行程域 | `itinerary_change_log` | 1 | 保存时的变更日志 |
| 行程域 | `itinerary_imports` | 3904 | 导入的行程文件 |
| 行程域 | `intercity_transfers` | 0 | 城际交通段 |
| 行程域 | `execution_events` | 0 | 执行轨迹（按日/按月分区） |
| 行程域 | `execution_events_2026_10` | 0 |  |
| 心愿单域 | `trip_items` | 12 | 行程中心三态（心愿/排期/已订/不想去） |
| 地点参考域 | `pois` | 14374 | POI 主库 |
| 地点参考域 | `poi_hours` | 0 | 营业时间规则 |
| 地点参考域 | `poi_reviews` | 502 | 评论聚合 |
| 地点参考域 | `poi_stats` | 1 | 热度统计 |
| 地点参考域 | `restaurants` | 5088 | 餐厅库 |
| 交易域 | `action_handoffs` | 6 | 预订扶手 |
| 交易域 | `entitlements` | 0 | 权益 |
| 交易域 | `iap_transactions` | 0 | 内购 |
| 交易域 | `payments` | 0 | 支付 |
| 交易域 | `paywall_rules` | 0 | 付费墙规则 |
| 账号与画像 | `users` | 0 | 用户锚 |
| 账号与画像 | `user_profiles` | 0 | 画像 |
| 账号与画像 | `link_history` | 0 | 链接历史 |
| 天气与运维 | `weather_reports` | 745 | 天气 |
| 天气与运维 | `alembic_version` | 1 | 迁移版本 |
| 运维 / 备份 / 其他 | `pois_category_fix_bak_20261111` | 27 |  |
| 运维 / 备份 / 其他 | `pois_component_bak_20261108` | 3 |  |
| 运维 / 备份 / 其他 | `pois_curated_tag_bak_20261108` | 1 |  |
| 运维 / 备份 / 其他 | `pois_dupgate_bak_20261108` | 1 |  |
| 运维 / 备份 / 其他 | `pois_opera_reactivate_bak_20261111` | 45 |  |
| 运维 / 备份 / 其他 | `pois_shiershichen_geofix_bak_20261107` | 1 |  |
| 运维 / 备份 / 其他 | `pois_showpin_bak_20261108` | 2 |  |
| 运维 / 备份 / 其他 | `pois_street_sweep_bak_20261107` | 13 |  |
| 运维 / 备份 / 其他 | `pois_theater_sweep_bak_20261110` | 56 |  |
| 运维 / 备份 / 其他 | `pois_wrongpin_bak_20261107` | 4 |  |
| 运维 / 备份 / 其他 | `spatial_ref_sys` | 8500 |  |

## 2. 行程域数据模型（2026-11-13 拍板）

写入时机（运行时行为，不是只建表）：

| 操作 | 端点 | 库内动作 |
| --- | --- | --- |
| 保存行程 | `POST /api/v1/plan/{sid}/save` | UPDATE `itineraries`（头字段+最后变更+创建人）→ DELETE+INSERT `itinerary_days`/`itinerary_items`（snapshot_id IS NULL）→ INSERT `itinerary_change_log` |
| 打开行程 | `POST /api/v1/plan/from-itinerary/{id}` | 重建会话 + 看板对账（心愿单里已落排的翻已排期、行程里没有的回心愿单） |
| 删除行程 | `DELETE /api/v1/itineraries/{id}` | UPDATE `trip_items`（解绑 + scheduled→wishlist）→ UPDATE `itineraries.is_deleted=TRUE`（软删；明细/快照留审计） |
| 读详情 | `GET /api/v1/itineraries/{id}/detail` | 读 `itinerary_days` + `itinerary_items`（每天带城市、每个点位带日期/时段/时长/备选） |
| 读变更 | `GET /api/v1/itineraries/{id}/changes` | 读 `itinerary_change_log`（倒序 200 条） |
| 全量回填 | `python ops/backfill_trip_detail.py` | 存量行程补头字段与明细（不写 change log） |

## 3. 逐表字段

### 行程域（trip header / detail / snapshot / log）

#### `itineraries`  (8 行)
**TRIP HEADER**（2026-11-13 用户拍板）：一次行程一行。

- 身份：`id`（uuid5 代理键，由业务号 `it-xxxxxxxx` 派生）、`title`（trip name）
- 时间：`created_at`（创建日期）、`updated_at`、`last_changed_at`（最后变更，含日期+时刻）、
  `travel_start_date`（旅行开始日期）
- 人：`owner_device_id`（USER）、`owner_account_id`（登录账号）、`creator_name`（USER NAME）
- 路线：`cities[]`、`start_city`（起始城市）、`end_city`（结束城市）、
  `dest_city_1` / `dest_days_1`、`dest_city_2` / `dest_days_2`（旅行城市一/二 + 日期数）
- 删除：`is_deleted` + `deleted_at`（软删；读口按 `is_deleted` 过滤，明细与快照留审计）
- 正文：`plan` JSONB（ItineraryRecord 全量文档，含 snapshots）

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `user_id` | uuid | YES |  |
| `cities` | ARRAY | NO |  |
| `title` | character varying(200) | YES |  |
| `working_sync_version` | integer | NO | 1 |
| `active_snapshot_id` | uuid | YES |  |
| `status` | character varying(20) | YES | 'draft'::character varying |
| `created_at` | timestamp without time zone | YES | now() |
| `updated_at` | timestamp without time zone | YES | now() |
| `plan` | jsonb | YES |  |
| `owner_device_id` | text | YES |  |
| `owner_account_id` | text | YES |  |
| `share_enabled` | boolean | NO | false |
| `share_token` | text | YES |  |
| `is_deleted` | boolean | NO | false |
| `deleted_at` | timestamp with time zone | YES |  |
| `creator_name` | character varying(100) | YES |  |
| `last_changed_at` | timestamp with time zone | YES |  |
| `start_city` | character varying(50) | YES |  |
| `end_city` | character varying(50) | YES |  |
| `dest_city_1` | character varying(50) | YES |  |
| `dest_city_2` | character varying(50) | YES |  |
| `dest_days_1` | integer | YES |  |
| `dest_days_2` | integer | YES |  |
| `travel_start_date` | date | YES |  |

- 主键：`id`
- 外键：
  - `user_id` → `users.id`

- 索引：`itineraries_pkey`；`idx_itineraries_owner_device`；`idx_itineraries_owner_account`；`uq_itineraries_share_token`

#### `itinerary_days`  (20 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `itinerary_id` | uuid | YES |  |
| `snapshot_id` | uuid | YES |  |
| `day` | integer | NO |  |
| `base_city` | character varying(50) | NO |  |

- 主键：`id`
- 外键：
  - `itinerary_id` → `itineraries.id`
  - `snapshot_id` → `itinerary_snapshots.id`

- 索引：`itinerary_days_pkey`；`itinerary_days_itinerary_id_day_snapshot_id_key`

#### `itinerary_items`  (100 行)
**TRIP 明细**：每天每个时段一条（`snapshot_id IS NULL` = 当前工作副本）。

- 位置：`day`（第几天）、`position`（当天顺序）
- 时间：`schedule_date`（具体日期 = 出发日 + day-1）、`start_time` / `end_time`、`duration_minutes`
- 点位：`name`、`city`、`category`、`address`、`poi_ref`（POI 业务号）、`item_ref`（plan item_id）
- 种类：`kind`（attraction / food / hotel / entertainment / transfer）
- 城际段：`from_city` / `to_city` / `transport_no`（航班号/车次；这类行没有 name）
- 备选：`alt1` / `alt2` / `alt3`（名称投影）+ `alternatives` JSONB（全量：类别/档位/坐标）

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `itinerary_id` | uuid | YES |  |
| `snapshot_id` | uuid | YES |  |
| `day` | integer | NO |  |
| `poi_id` | uuid | YES |  |
| `position` | double precision | NO |  |
| `start_time` | time without time zone | YES |  |
| `end_time` | time without time zone | YES |  |
| `draft` | boolean | YES | true |
| `name` | character varying(200) | YES |  |
| `city` | character varying(50) | YES |  |
| `category` | character varying(40) | YES |  |
| `address` | character varying(200) | YES |  |
| `alternatives` | jsonb | YES |  |
| `duration_minutes` | integer | YES |  |
| `schedule_date` | date | YES |  |
| `alt1` | character varying(200) | YES |  |
| `alt2` | character varying(200) | YES |  |
| `alt3` | character varying(200) | YES |  |
| `item_ref` | character varying(64) | YES |  |
| `poi_ref` | character varying(64) | YES |  |
| `kind` | character varying(20) | YES |  |
| `from_city` | character varying(50) | YES |  |
| `to_city` | character varying(50) | YES |  |
| `transport_no` | character varying(32) | YES |  |

- 主键：`id`
- 外键：
  - `itinerary_id` → `itineraries.id`
  - `snapshot_id` → `itinerary_snapshots.id`
  - `poi_id` → `pois.id`

- 索引：`itinerary_items_pkey`

#### `itinerary_snapshots`  (10 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `itinerary_id` | uuid | YES |  |
| `name` | character varying(100) | YES |  |
| `note` | text | YES |  |
| `sync_version` | integer | NO |  |
| `created_at` | timestamp without time zone | YES | now() |
| `plan` | jsonb | YES |  |

- 主键：`id`
- 外键：
  - `itinerary_id` → `itineraries.id`

- 索引：`itinerary_snapshots_pkey`

#### `itinerary_change_log`  (1 行)
**变更日志**：每次点「💾 保存行程」一行。

- 人：`owner_device_id`（USER）、`owner_account_id`、`actor_name`（USER NAME）
- 时：`changed_at`、`sync_version`（第几次保存）
- 事：`summary`（人读摘要，如「变时 1：大雁塔」）、`changes` JSONB（逐条 diff：
  `{"op": "add|remove|move|retime", "name": …, "day": …}`）、`snapshot_id`

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `itinerary_id` | uuid | YES |  |
| `itinerary_ref` | character varying(64) | YES |  |
| `owner_device_id` | character varying(100) | YES |  |
| `owner_account_id` | character varying(100) | YES |  |
| `actor_name` | character varying(100) | YES |  |
| `changed_at` | timestamp with time zone | NO | now() |
| `sync_version` | integer | YES |  |
| `summary` | text | YES |  |
| `changes` | jsonb | YES |  |
| `snapshot_id` | character varying(64) | YES |  |

- 主键：`id`
- 外键：
  - `itinerary_id` → `itineraries.id`

- 索引：`itinerary_change_log_pkey`；`ix_itinerary_change_log_itinerary_id`

#### `itinerary_imports`  (3904 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `itinerary_id` | uuid | YES |  |
| `file_name` | character varying(255) | YES |  |
| `ext` | character varying(20) | YES |  |
| `size_bytes` | integer | YES |  |
| `text_chars` | integer | YES |  |
| `status` | character varying(20) | NO | 'previewed'::character varying |
| `error` | text | YES |  |
| `text_preview` | text | YES |  |
| `owner_device_id` | text | YES |  |
| `owner_account_id` | text | YES |  |
| `created_at` | timestamp without time zone | YES | now() |
| `confirmed_at` | timestamp without time zone | YES |  |

- 主键：`id`
- 外键：
  - `itinerary_id` → `itineraries.id`

- 索引：`itinerary_imports_pkey`；`idx_itinerary_imports_owner_device`；`idx_itinerary_imports_itinerary`

#### `intercity_transfers`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `itinerary_id` | uuid | YES |  |
| `snapshot_id` | uuid | YES |  |
| `day` | integer | NO |  |
| `seq` | integer | NO | 1 |
| `from_city` | character varying(50) | YES |  |
| `to_city` | character varying(50) | YES |  |
| `mode` | character varying(20) | YES |  |

- 主键：`id`
- 外键：
  - `itinerary_id` → `itineraries.id`
  - `snapshot_id` → `itinerary_snapshots.id`

- 索引：`intercity_transfers_pkey`；`intercity_transfers_itinerary_id_day_seq_snapshot_id_key`

#### `execution_events`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `itinerary_id` | uuid | YES |  |
| `ts` | timestamp without time zone | NO |  |
| `type` | character varying(40) | NO |  |
| `payload` | jsonb | YES |  |

- 主键：`id, ts`
- 外键：
  - `itinerary_id` → `itineraries.id`
  - `itinerary_id` → `itineraries.id`
  - `itinerary_id` → `itineraries.id`
  - `itinerary_id` → `itineraries.id`

- 索引：`execution_events_pkey`

#### `execution_events_2026_10`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `itinerary_id` | uuid | YES |  |
| `ts` | timestamp without time zone | NO |  |
| `type` | character varying(40) | NO |  |
| `payload` | jsonb | YES |  |

- 主键：`id, ts`
- 外键：
  - `itinerary_id` → `itineraries.id`
  - `itinerary_id` → `itineraries.id`
  - `itinerary_id` → `itineraries.id`
  - `itinerary_id` → `itineraries.id`

- 索引：`execution_events_2026_10_pkey`

### 心愿单域（trip_items + 只读视图）

#### `trip_items`  (12 行)
**行程中心三态**（铁律 0：手动 / 对话 / 粘贴写同一张表）。

- 归属：`owner_device_id`（按设备隔离，别的浏览器/冒烟不改写你的行）、`created_by`
- 行程：`itinerary_ref`（业务号，恒可读）+ `itinerary_id`（uuid 外键，未保存的工作行程没有行时为空）
- 状态：`status` = wishlist / scheduled / booked / unwanted；`day`、`position`、`booking_id`
- 口径：`arranged`（有具体日期时刻才算已排）、`exclusion_flag`（不想去）、
  `deletion_flag` / `deletion_date` / `deletion_time` / `deleted_by`（软删留档）
- 只读视图 `wish_items`：13 列扁平口径（trip_id / wish_id / wish_name / created_on /
  created_by / trip_name / arranged / source / deletion_flag / deletion_date /
  deletion_time / deleted_by / exclusion_flag）

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `itinerary_id` | uuid | YES |  |
| `user_id` | uuid | YES |  |
| `name` | character varying(200) | NO |  |
| `city` | character varying(50) | YES |  |
| `note` | text | YES |  |
| `status` | character varying(20) | NO | 'wishlist'::character varying |
| `source` | character varying(20) | NO |  |
| `poi_id` | uuid | YES |  |
| `day` | integer | YES |  |
| `position` | double precision | YES |  |
| `booking_id` | uuid | YES |  |
| `created_at` | timestamp without time zone | YES | now() |
| `updated_at` | timestamp without time zone | YES | now() |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(200) | YES |  |
| `payload` | jsonb | YES |  |
| `owner_device_id` | character varying(64) | YES |  |
| `itinerary_ref` | character varying(64) | YES |  |
| `created_by` | character varying(64) | YES |  |
| `arranged` | boolean | NO | false |
| `exclusion_flag` | boolean | NO | false |
| `deletion_flag` | boolean | NO | false |
| `deletion_date` | date | YES |  |
| `deletion_time` | time without time zone | YES |  |
| `deleted_by` | character varying(64) | YES |  |
| `kind` | character varying(20) | YES |  |
| `duration_minutes` | integer | YES |  |
| `must_visit` | boolean | NO | false |
| `pinned` | boolean | NO | false |
| `tier` | smallint | YES |  |
| `site_rank` | smallint | YES |  |
| `latitude` | double precision | YES |  |
| `longitude` | double precision | YES |  |
| `planned_date` | date | YES |  |
| `start_time` | time without time zone | YES |  |
| `end_time` | time without time zone | YES |  |
| `raw_command` | character varying(1000) | YES |  |
| `arranged_at` | timestamp without time zone | YES |  |

- 主键：`id`
- 外键：
  - `itinerary_id` → `itineraries.id`
  - `user_id` → `users.id`
  - `poi_id` → `pois.id`
  - `booking_id` → `action_handoffs.id`

- 索引：`trip_items_pkey`；`ix_trip_items_owner_device_id`；`ix_trip_items_itinerary_ref`；`ix_trip_items_deletion_flag`；`ix_trip_items_arranged`

### 地点参考域（POI / 营业时间 / 餐饮）

#### `pois`  (14374 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `source` | character varying(20) | NO |  |
| `source_poi_id` | character varying(100) | NO |  |
| `city` | character varying(50) | NO |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES | 'active'::character varying |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES | now() |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | NO | 'any'::character varying |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |
| `photos_fetched_at` | timestamp without time zone | YES |  |
| `photos_fetch_fail` | integer | NO | 0 |
| `user_family` | character varying(50) | YES |  |
| `user_groups` | jsonb | YES |  |

- 主键：`id`
- 索引：`pois_pkey`；`pois_source_source_poi_id_key`；`idx_pois_location`；`idx_pois_city`；`idx_pois_city_business`；`idx_pois_user_family`

#### `poi_hours`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `poi_id` | uuid | YES |  |
| `rule_type` | character varying(20) | NO |  |
| `payload` | jsonb | NO |  |

- 主键：`id`
- 外键：
  - `poi_id` → `pois.id`

- 索引：`poi_hours_pkey`

#### `poi_reviews`  (502 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `poi_id` | uuid | NO |  |
| `user_id` | uuid | YES |  |
| `device_id` | character varying(64) | YES |  |
| `rating` | smallint | YES |  |
| `tags` | jsonb | YES |  |
| `text` | text | YES |  |
| `visited_at` | timestamp without time zone | YES |  |
| `source` | character varying(20) | YES |  |
| `created_at` | timestamp without time zone | YES | now() |

- 主键：`id`
- 外键：
  - `poi_id` → `pois.id`
  - `user_id` → `users.id`

- 索引：`pk_poi_reviews`；`idx_poi_reviews_poi`；`idx_poi_reviews_user`

#### `poi_stats`  (1 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `poi_id` | uuid | NO |  |
| `wish_count` | integer | NO | 0 |
| `plan_count` | integer | NO | 0 |
| `visit_count` | integer | NO | 0 |
| `dislike_count` | integer | NO | 0 |
| `thumbs_up` | integer | NO | 0 |
| `xhs_mentions` | integer | NO | 0 |
| `updated_at` | timestamp without time zone | YES | now() |

- 主键：`poi_id`
- 外键：
  - `poi_id` → `pois.id`

- 索引：`pk_poi_stats`

#### `restaurants`  (5088 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `source` | character varying(20) | NO |  |
| `source_poi_id` | character varying(100) | NO |  |
| `city` | character varying(50) | NO |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `cuisine` | character varying(50) | YES |  |
| `status` | character varying(20) | YES | 'active'::character varying |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `avg_cost` | numeric | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `origin` | character varying(20) | YES |  |
| `updated_at` | timestamp without time zone | YES | now() |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `signature_dishes` | jsonb | YES |  |
| `taste_score` | numeric | YES |  |
| `env_score` | numeric | YES |  |
| `service_score` | numeric | YES |  |
| `price_level` | character varying(10) | YES |  |
| `meal_periods` | jsonb | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `cuisine_en` | character varying(50) | YES |  |
| `signature_dishes_en` | jsonb | YES |  |
| `opening_hours_en` | text | YES |  |
| `photos_fetched_at` | timestamp without time zone | YES |  |
| `photos_fetch_fail` | integer | NO | 0 |
| `cuisine_family` | character varying(50) | YES |  |
| `cuisine_group` | character varying(50) | YES |  |

- 主键：`id`
- 索引：`pk_restaurants`；`uq_restaurants_source`；`idx_restaurants_location`；`idx_restaurants_city`；`idx_restaurants_cuisine_group`

### 交易域（预订 / 权益 / 支付）

#### `action_handoffs`  (6 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `user_id` | uuid | YES |  |
| `itinerary_id` | uuid | YES |  |
| `action_type` | character varying(20) | NO |  |
| `channel` | character varying(20) | NO |  |
| `deeplink` | text | NO |  |
| `h5_fallback` | text | YES |  |
| `status` | character varying(20) | YES | 'opened'::character varying |
| `order_ref` | character varying(100) | YES |  |
| `refund_policy` | jsonb | YES |  |
| `refund_deadline` | timestamp with time zone | YES |  |
| `created_at` | timestamp without time zone | YES | now() |
| `updated_at` | timestamp without time zone | YES | now() |
| `source_channel` | character varying(20) | YES |  |

- 主键：`id`
- 外键：
  - `user_id` → `users.id`
  - `itinerary_id` → `itineraries.id`

- 索引：`action_handoffs_pkey`

#### `entitlements`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `user_id` | uuid | YES |  |
| `itinerary_id` | uuid | YES |  |
| `product_id` | character varying(50) | NO |  |
| `status` | character varying(20) | NO |  |
| `source` | character varying(20) | NO |  |
| `created_at` | timestamp without time zone | YES | now() |
| `updated_at` | timestamp without time zone | YES | now() |

- 主键：`id`
- 外键：
  - `user_id` → `users.id`
  - `itinerary_id` → `itineraries.id`

- 索引：`entitlements_pkey`

#### `iap_transactions`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `entitlement_id` | uuid | YES |  |
| `platform` | character varying(10) | NO |  |
| `transaction_id` | character varying(100) | NO |  |
| `receipt_payload` | jsonb | YES |  |
| `verified_at` | timestamp without time zone | YES | now() |

- 主键：`id`
- 外键：
  - `entitlement_id` → `entitlements.id`

- 索引：`iap_transactions_pkey`；`iap_transactions_transaction_id_key`

#### `payments`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | character varying(40) | NO |  |
| `device_id` | character varying(100) | NO |  |
| `username` | character varying(100) | YES |  |
| `kind` | character varying(20) | NO |  |
| `amount_yuan` | numeric | YES |  |
| `currency` | character varying(8) | NO | 'cny'::character varying |
| `description` | text | YES |  |
| `email` | character varying(254) | YES |  |
| `refund_summary` | text | YES |  |
| `status` | character varying(20) | NO | 'pending'::character varying |
| `provider` | character varying(20) | NO | 'mock'::character varying |
| `provider_ref` | character varying(255) | YES |  |
| `charge_ref` | character varying(255) | YES |  |
| `customer_ref` | character varying(255) | YES |  |
| `payment_method_ref` | character varying(255) | YES |  |
| `saved_method_label` | character varying(60) | YES |  |
| `handoff_id` | character varying(128) | YES |  |
| `trip_item_id` | character varying(128) | YES |  |
| `created_at` | timestamp with time zone | YES | now() |
| `updated_at` | timestamp with time zone | YES | now() |
| `paid_at` | timestamp with time zone | YES |  |

- 主键：`id`
- 索引：`payments_pkey`；`idx_payments_device`

#### `paywall_rules`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `name` | character varying(100) | NO |  |
| `enabled` | boolean | YES | false |
| `priority` | integer | YES | 100 |
| `trigger_event` | character varying(40) | NO |  |
| `conditions` | jsonb | YES |  |
| `offer` | jsonb | NO |  |
| `caps` | jsonb | YES |  |
| `created_at` | timestamp without time zone | YES | now() |
| `updated_at` | timestamp without time zone | YES | now() |

- 主键：`id`
- 索引：`paywall_rules_pkey`

### 账号与画像

#### `users`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `region` | character varying(10) | NO |  |
| `created_at` | timestamp without time zone | YES | now() |
| `updated_at` | timestamp without time zone | YES | now() |

- 主键：`id`
- 索引：`users_pkey`

#### `user_profiles`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `user_id` | uuid | NO |  |
| `profile` | jsonb | NO |  |
| `embedding` | jsonb | YES |  |
| `updated_at` | timestamp without time zone | YES | now() |

- 主键：`user_id`
- 外键：
  - `user_id` → `users.id`

- 索引：`user_profiles_pkey`

#### `link_history`  (0 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `user_id` | uuid | YES |  |
| `url` | text | NO |  |
| `source` | character varying(20) | NO |  |
| `origin` | character varying(20) | YES |  |
| `itinerary_id` | uuid | YES |  |
| `extract_id` | uuid | YES |  |
| `status` | character varying(20) | YES | 'pending'::character varying |
| `created_at` | timestamp without time zone | YES | now() |

- 主键：`id`
- 外键：
  - `user_id` → `users.id`
  - `itinerary_id` → `itineraries.id`

- 索引：`link_history_pkey`

### 天气与运维

#### `weather_reports`  (745 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | NO |  |
| `source` | character varying(20) | NO |  |
| `adcode` | character varying(10) | NO |  |
| `city` | character varying(50) | NO |  |
| `kind` | character varying(10) | NO |  |
| `report_time` | timestamp without time zone | YES |  |
| `payload` | jsonb | YES |  |
| `fetched_at` | timestamp without time zone | YES | now() |

- 主键：`id`
- 索引：`pk_weather_reports`；`uq_weather_reports_key`；`idx_weather_reports_city`

#### `alembic_version`  (1 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `version_num` | character varying(32) | NO |  |

- 主键：`version_num`
- 索引：`alembic_version_pkc`

### 运维 / 备份 / 其他

#### `pois_category_fix_bak_20261111`  (27 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `opening_hours` | character varying(500) | YES |  |

#### `pois_component_bak_20261108`  (3 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `source` | character varying(20) | YES |  |
| `source_poi_id` | character varying(100) | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | YES |  |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |

#### `pois_curated_tag_bak_20261108`  (1 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `source` | character varying(20) | YES |  |
| `source_poi_id` | character varying(100) | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | YES |  |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |

#### `pois_dupgate_bak_20261108`  (1 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `source` | character varying(20) | YES |  |
| `source_poi_id` | character varying(100) | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | YES |  |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |

#### `pois_opera_reactivate_bak_20261111`  (45 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `source` | character varying(20) | YES |  |
| `source_poi_id` | character varying(100) | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | YES |  |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |

#### `pois_shiershichen_geofix_bak_20261107`  (1 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `source` | character varying(20) | YES |  |
| `source_poi_id` | character varying(100) | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | YES |  |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |

#### `pois_showpin_bak_20261108`  (2 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `source` | character varying(20) | YES |  |
| `source_poi_id` | character varying(100) | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | YES |  |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |

#### `pois_street_sweep_bak_20261107`  (13 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `source` | character varying(20) | YES |  |
| `source_poi_id` | character varying(100) | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | YES |  |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |

#### `pois_theater_sweep_bak_20261110`  (56 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `source` | character varying(20) | YES |  |
| `source_poi_id` | character varying(100) | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | YES |  |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |

#### `pois_wrongpin_bak_20261107`  (4 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `id` | uuid | YES |  |
| `source` | character varying(20) | YES |  |
| `source_poi_id` | character varying(100) | YES |  |
| `city` | character varying(50) | YES |  |
| `name_zh` | character varying(200) | YES |  |
| `name_en` | character varying(200) | YES |  |
| `category` | character varying(50) | YES |  |
| `status` | character varying(20) | YES |  |
| `location` | USER-DEFINED | YES |  |
| `wgs84_location` | USER-DEFINED | YES |  |
| `updated_at` | timestamp without time zone | YES |  |
| `address` | character varying(200) | YES |  |
| `opening_hours` | character varying(500) | YES |  |
| `hours_source` | character varying(20) | YES |  |
| `hours_updated_at` | timestamp without time zone | YES |  |
| `phone` | character varying(50) | YES |  |
| `website` | character varying(300) | YES |  |
| `rating` | numeric | YES |  |
| `rating_source` | character varying(20) | YES |  |
| `tags` | jsonb | YES |  |
| `tags_source` | character varying(20) | YES |  |
| `intro` | text | YES |  |
| `intro_source` | character varying(20) | YES |  |
| `photos` | jsonb | YES |  |
| `photos_source` | character varying(20) | YES |  |
| `best_visit_time` | character varying(10) | YES |  |
| `best_visit_time_source` | character varying(20) | YES |  |
| `suggested_duration_min` | integer | YES |  |
| `origin` | character varying(20) | YES |  |
| `rating_count` | integer | YES |  |
| `review_tags` | jsonb | YES |  |
| `review_tags_source` | character varying(20) | YES |  |
| `ticket_price_min` | integer | YES |  |
| `ticket_price_max` | integer | YES |  |
| `ticket_source` | character varying(20) | YES |  |
| `district` | character varying(50) | YES |  |
| `business_area` | character varying(50) | YES |  |
| `indoor` | character varying(10) | YES |  |
| `rain_ok` | character varying(10) | YES |  |
| `name_aliases` | jsonb | YES |  |
| `duration_source` | character varying(20) | YES |  |
| `review_summary` | text | YES |  |
| `review_summary_source` | character varying(20) | YES |  |
| `reservation_required` | boolean | YES |  |
| `reservation_advance_days` | integer | YES |  |
| `booking_url` | character varying(500) | YES |  |
| `intro_en` | text | YES |  |
| `address_en` | character varying(200) | YES |  |
| `review_tags_en` | jsonb | YES |  |
| `review_summary_en` | text | YES |  |
| `opening_hours_en` | text | YES |  |

#### `spatial_ref_sys`  (8500 行)

| 列 | 类型 | 空 | 默认 |
| --- | --- | --- | --- |
| `srid` | integer | NO |  |
| `auth_name` | character varying(256) | YES |  |
| `auth_srid` | integer | YES |  |
| `srtext` | character varying(2048) | YES |  |
| `proj4text` | character varying(2048) | YES |  |

- 主键：`srid`
- 索引：`spatial_ref_sys_pkey`

## 4. 视图

### `geography_columns`

列：`f_table_catalog`, `f_table_schema`, `f_table_name`, `f_geography_column`, `coord_dimension`, `srid`, `type`

### `geometry_columns`

列：`f_table_catalog`, `f_table_schema`, `f_table_name`, `f_geometry_column`, `coord_dimension`, `srid`, `type`

### `wish_items`

列：`trip_id`, `wish_id`, `wish_name`, `created_on`, `created_by`, `trip_name`, `arranged`, `source`, `deletion_flag`, `deletion_date`, `deletion_time`, `deleted_by`, `exclusion_flag`, `kind`, `duration_minutes`, `must_visit`, `pinned`, `tier`, `site_rank`, `latitude`, `longitude`, `planned_date`, `start_time`, `end_time`, `raw_command`, `arranged_at`

## 5. 本机 SQLite 状态库（data/h5_state.db，单机 write-through）
| 表 | 说明 |
| --- | --- |
| `plan_sessions` | 规划会话（payload JSON：session + plan） |
| `itineraries` | 行程记录镜像（payload JSON） |
| `trip_items` | 心愿单镜像（payload JSON） |
| `accounts` / `email_codes` / `email_code_log` | 账号与邮箱验证码 |
