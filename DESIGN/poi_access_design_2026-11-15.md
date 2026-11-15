# POI 到达方式（access_*）设计 2026-11-15

> 触发：用户口径「transportation——大多远郊景点会有景区转线大巴或者地铁或者火车，你需要查这些远郊景点的交通方式，例如慕田峪长城就有火车。POIS 是否要加一个 COLUMN TRANSPORTATION」。
> 结论：**要加，但不是一列自由文本**——落 `pois.access_*` 一组摘要列 + 可回填任务；精确接驳腿留二期。

---

## 1 问题（现状实测）

- 规划器市内腿**一律打车模型**：`itinerary/rules.taxi_leg_min` = 直线×1.3 ÷ 70km/h + 15 分钟叫车，≤1.5km 步行，封顶 180 分钟。慕田峪（城心直线 59km）算成 **81 分钟**。
- 实际公共交通：城心 → 慕田峪是「慕田峪长城景区直达车前门线」，百度 transit 实测 **128 分钟**、**首班 07:00 / 末班 12:00**、下车再走 2km —— 与打车模型差 47 分钟，且**末班 12:00 直接决定当天能不能去**，行程卡上此前一个字都没有（只有地址 + 营业时间 + 打车链接）。
- 规模：全库 >15km（城心口径）的观光候选 **3085 个**；北京 132、上海 124、杭州 197、成都 180、苏州 186、重庆 245、深圳 141、广州 137、南京 92。不是个别点的手工补丁。

## 2 口径：为什么不是单列 `transportation`

| 方案 | 问题 |
|---|---|
| `pois.transportation TEXT`（一句自由文本） | 一个点有 2–5 条方案（地铁/公交/景区专线/铁路/自驾），一列装不下；自由文本引擎读不了，无法参与排期 |
| 只在行程卡上写死文案 | 每个点手写，9889 行维护必烂；且无法按用户出行方式切换 |
| **摘要列 + 可回填（本设计）** | 一列一种机器可读信号（方式/时长/网关/接驳），一句人话供展示；数据由既有 transit 商链算出，手工只兜底例外 |

三点硬约束决定了「城心口径摘要」这个中间态：

1. **起点依赖**：同一 POI 从酒店/城心/上一站走法不同，精确路由必须现算（`/api/v1/nav/transit` 已有）；
2. **有时刻表**：景区直达车、市郊铁路有首末班与班距，末班过了就是去不了——必须落库才能进规划；
3. **可算**：`app/services/map_provider.build_client_chain(settings, "transit")`（baidu > amap）+ `transit_route` 已在本仓，无需新数据源。

## 3 字段（迁移 w12_0037）

| 列 | 型 | 语义 |
|---|---|---|
| `access_mode` | String(16) | metro / bus / train / shuttle / ferry / walk（主干那一段的方式） |
| `access_minutes` | Integer | 城心 → POI 门到门分钟（含步行、换乘） |
| `access_gateway` | String(100) | 最后一段车的**下车站**（火车/专线不停在景区门口） |
| `access_gateway_minutes` | Integer | 下车后步行分钟；**下车点离景区 ≥1.5km 时为 NULL**（不是步行，见 §5） |
| `access_note` / `access_note_en` | String(300) | 一句人话，含首末班；`仅 11:00 一班` 这类单班次单独措辞 |
| `access_source` | String(20) | `<vendor>-transit`（baidu/amap）或 manual |
| `access_updated_at` | TIMESTAMP | 回填时间；NULL = 未回填（只填空闸的判据） |

「主干那一段」= 时长最长的一段（缺时长按方式重要性兜底）：地铁 40 分钟 + 长途公交 2 小时报**公交**，不是报地铁。

## 4 回填管道

`python -m app.jobs.backfill_poi_access [--city 北京] [--limit 200] [--min-km 15] [--force] [--dry-run]`

1. 候选：`status active`、有坐标、类别非 hotel/food/transport/service、距城心 > `--min-km`（默认 15km，近点打车/步行就够，省配额），按距城心**由远到近**排序取前 N（限量时优先覆盖最需要的远郊件）；
2. 起点 = `weather_open_meteo.CITY_COORDS`（城心，缺锚城市跳过）；终点 = POI 经纬度；
3. `transit` 商链取最快方案 → `app.services.poi_access.summarize()` 归一（纯函数，10 条单测）；
4. **只填空**：`access_updated_at` 非空默认不动，`--force` 重算；每行独立事务，失败不写。

归一规则的坑（都踩过）：

- **百度真实响应是「段数组的数组」**，步上带 `trans_type`（-1 乘车 / 0、4 步行 / 1、3 换乘）与 `vehicle_info.detail`（线路名/上下车站/首末班/`shuttle_time_table`），旧 `_normalize_transit_steps` 按文档猜的扁平形状解析 → `segments` 恒空（导航页只有「N 分钟」没有换乘细节）。本次一并修好，兼容两种形状（`tests/test_baidu.py::test_transit_route_real_nested_shape_with_vehicle_detail`）。
- 百度地铁 `vehicle type=1`、景区直达车 `type=10`，其余不可靠 → 方式先按**线路名词表**判（地铁/号线 → metro；景区直达/专线/接驳 → shuttle；铁路/市郊/城际 → train），`kind` 兜底。
- 城心到点 4 小时、下车再「步行 166 分钟」= 13km 山路（龙门涧实录）——不是步行。规则：下车段 ≥1.5km 改口「下车点距景区约 X km，末段建议打车/接驳」，`access_gateway_minutes` 置 NULL。

## 5 展示

- `GET /api/pois/detail` 出参并出 `access_*`（H5 站点气泡与悬停浮层共用）；
- H5：简介气泡与悬停浮层各加一行「🚌 怎么去：…」（i18n `brief.access`，sw v98）。
  例：`🚌 怎么去：乘 慕田峪长城景区直达车前门线：前门站 → 慕田峪长城站（首班 07:00 / 末班 12:00），全程约 2 小时 8 分`
- 顺手修 `apply_tier_tag` 同名徽标去重（5A 行的层级牌与来源牌都叫 `5a`，旧码挂两次 → `['5a','5a']`）。

## 6 二期（未做，按此顺序）

1. `poi_access` 明细表（POI × 方案 × 顺序：mode/line/from/to/duration/walk/transfers/headway/first/last/ticket/source）——现在只存了最快一条的摘要；
2. 用户级出行方式偏好（自驾 / 公共交通优先 / 只走路+地铁）——现在全程默认打车；
3. 引擎接驳腿：`access_mode ∈ {train, shuttle, ferry}` 的点，腿拆成「酒店 → 枢纽 →(班次)→ 景区门口」，按首末班钉时刻，排不下换天/换点，而不是把 2 小时压成 81 分钟硬塞（`TransferItem` 目前只服务城际，需要 local 语义）；
4. 数据面补齐：15km 内点、缺城心锚的城市、自驾口径（高德 driving 时长另存一列）。

## 7 已知边界

- 城心口径 ≠ 行程内实际走法（后者由导航端点现算）；`access_minutes` 只用于展示与「远郊/需班次」粗判；
- 百度 transit 的步行段时长偶有不合理（2km 报 8 分钟），本设计只做「是否可步行」的距离闸，不修正图商时长；
- 夜间/当日末班之后的可用性未建模（首末班只进文案）；
- 脏行 `八达岭慕田峪长城旅游区`（5A 名录行，坐标落在八达岭）保留：它是官方 5A 复合实体，非重复行。

## 8 引擎接驳腿（2026-11-15 二拍「一般是 TAXI + 引擎接驳腿」）

口径：市内腿**默认仍是打车模型**（`rules.taxi_leg_min`，70km/h + 15 分钟叫车）；
命中 `access_mode ∈ {train, shuttle, ferry}`（景区专线 / 市郊铁路 / 轮渡）的点，
这条腿改走**接驳链**：

```
打车(上一站 → 乘车点) + 候车 + 车上 + 落客接驳 = 门到门
```

数据（w12_0038）：`access_boarding` / `_lon` / `_lat`（首段乘车点）、
`access_service_minutes`（车上）、`access_wait_minutes`（候车/换乘）、
`access_last_mile_minutes`（落客点 → 景区门口：可步行=步行，否则打车估算）。
站点坐标来自 transit 归一：高德 `buslines[].x_stop.location`、百度
`vehicle_info.detail.start_info/end_info`（BD09 → GCJ-02）。

链路：`VisitItem` 带 `access_*`；`rules.access_chain_minutes` 出链值，
`travel_gap_needed` 命中即用；`_travel_matrix` 先 `attach_access` 再建矩阵，且
不再用打车值盖掉更长的链值（旧码 `max(needed, taxi)` 会把 143 分钟压回 81）。

**口径一致性**：矩阵只覆盖 solver；心愿快路径 / 兜底重排 / 单点加卡都不经过
矩阵，所以 `poi_access.profile_for(city, name)` 提供城市级档案缓存（TTL 10 分钟，
由 PlanningAgent 初始化时 `configure_profiles(store)` 显式注入——规则层不自动读
库，避免测试/离线调用被 DB 口径污染）。

实测（真机，2026-11-15）：北京 2 天 + 心愿「我要去慕田峪长城」——慕田峪落
第 2 天，其后一条腿按 143 分钟计（打车口径 81 分钟），下一站被顺延到 16:47。

**已知边界（下一步）**：当天的**首件**是班次点时，头部锚点仍是 30 分钟默认值
——酒店卡只有名字没有坐标，`hotel_stays` 的「最早 8:30 离店」也算不出
「06:37 出门才赶得上 09:00 的专线」。要修这条，需要给酒店卡落坐标（或退到
城心锚）后把链值接进头部锚点。
