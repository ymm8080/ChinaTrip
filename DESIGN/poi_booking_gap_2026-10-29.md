# 旅游点主功能 × 预约情况对照（2026-10-29）

> 命题「compare the main function of tourist site especially the booking
> situation」的对照留档：旅游点主功能在 规划/详情/行程/预订 四个触点的
> 现状盘点，以及本日据此落地的读侧改进。关联：booking_design_2026-10-25
> （三档栈定稿）、POIS DATASOURCE/README（09 预约 CSV → reservation_seeds）、
> reservation_seeds_核对_2026-10-25（官方口径）。

## 1. 主功能对照（文档 / 代码 / H5 三层）

| 主功能 | 数据与代码 | 触达用户的触点 | 状态 |
| --- | --- | --- | --- |
| 搜索/候选 | `search_keyword` / `top_pois_in_city`（tier 优先 + 自产热度） | 规划候选（内部消费） | ✅（无 HTTP 搜索端点——H5 无独立搜索诉求） |
| 详情富化 | `GET /api/pois/detail`（intro/首图/徽标/电话，字段级来源） | 站点名点击气泡 | ✅ v2.5 |
| 层级徽章 | 读侧 `hit_tier`/`apply_tier_tag`（2026-10-28 接线） | 气泡 🏷 徽标 | ✅ |
| 开放时间 | `opening_hours` 扁平串 + `poi_hours` 结构化 | 气泡 🕐 / solver 硬窗 | ✅ |
| 票价 | `ticket_price_min/max/source`（ctrip 回源链回填） | **无任何出参** | ❌ → ✅ 本日接详情出参 |
| 预约要求 | `reservation_required/advance_days/booking_url` 三列 + `RESERVATION_V0` 名单（28 键，17 正馆每周日 21:00 周检回写库列） | 规划时 `reservation_hint` / 行程卡 🎫 行 / 抢票日历 | **详情触点断链** → 本日接通 |
| 预订动作 | `/api/v1/booking-auto` L1/L2/L3 + geo 分流（境外 Trip.com/境内美团） | 行程卡「抢票直达」/ 订单页回填 | ✅ |

断链定位：预约信息此前只在「规划/行程」触点可见（plan 侧 `_reservation_hint`
库列优先名单兜底、行程卡 🎫 行、L1 放票日历），但用户点开站点简介气泡
（`enrichBrief` → `/api/pois/detail`）反而什么预约信息都看不到——详情出参
从未携带 `reservation_*`/`booking_url`/票价字段，是预约链路唯一断点。

## 2. 本日改进（读侧接线，随 batch 落库）

1. **`/api/pois/detail` 出参 +11 字段**：`reservation_required` /
   `reservation_advance_days` / `reservation_release_time` /
   `reservation_note(+_en)` / `foreigner_tip(+_en)` / `booking_url` +
   `ticket_price_min/max/source`。库列优先（refresh_reservation_rules 周检
   回写 / ctrip 票价链），`RESERVATION_V0` 名单兜底——与
   `plan._reservation_hint` 同语义（库列有值不出名单提示；release 时刻无
   库列恒由名单补，名单口径 "00:00"=未注明 → 出参 null；互含容错同
   `_same_site`，「故宫博物院」⊂ 名单键「故宫」）。
2. **H5 站点简介气泡预约块**（`enrichBrief`）：琥珀色块（行程卡同款
   #b26a00）——🎫 需预约 · 提前 N 天（days=0 显「当日票」）· 每日 HH:MM
   放票 +「抢票直达 →」+ 名单渠道提示 ⓘ + 🛂 外籍提示（双语走
   `I18N.pick`）；票价行（¥ 区间 + 来源小字）。直达链接与行程卡共用抽取出的
   `bookDirect`（气泡挂在 flow-plan 对话流、不在卡容器内，卡上委托监听
   收不到 → onclick 直绑；order-intent L3 路径与埋点零变化）。
3. **i18n**：en 词典 +6 键（`brief.reserve*`），`check_h5_static` 守门通过
   （661 在用 key 全覆盖）。
4. **测试**：`test_api_pois` +5（非预约馆全 null / 名单兜底 / 库列优先 /
   名单互含容错 / 票价透出）；全量 **1524 passed**，覆盖 79.88%，ruff 绿。

## 3. 剩余缺口（未做，按优先级）

- **Ctrip「需预约」标识回源接管 `reservation_required`**（POIS DATASOURCE
  README 既有口径）——`ctrip_hours` 解析器现无该字段，需实页核实标记 DOM
  后再接线（写侧，本批未动）。
- **预约名单覆盖面**：28 键（17 正馆 + 别名/扩充），均为头部场馆；4A/景区
  级预约要求无源——等 09 CSV 扩量或携程标识回源补量。
- `/api/pois/detail` 仍未出：`address_en`/`opening_hours_en`/
  `review_summary(_en)`/`rating_count`/`indoor`/`rain_ok`——气泡目前只消费
  intro/tags/phone/photo，先放行也无人用；随 H5 消费扩再逐字段放行。
- `poi_hours` 结构化时段未直达 H5（气泡只显示扁平 opening_hours 串）；
  `wgs84_location` 仍无消费方（海外地图 Phase 2）。
