# 预约与预订设计 — ChinaTrip（Booking Design）

日期：2026-10-25 ｜ 版本：v1.0 ｜ 状态：与代码同步（booking_auto.py 等已全量落地，1099 测绿）
关联：[规划引擎升级](planning_engine_upgrade_2026-10-24.md)（G1 源出 §14.3）、[系统设计 V2.5](travel_agent_system_design%20V2.5.md) §6.11 行动编排/铁律 22·23、[数据库设计](database_design.md)（action_handoffs/trip_items）
> 单档说明：客户速览已并入本文 §8（原 Booking for client.md 于 2026-10-25 合并删除，用户拍板只留一档）；核对留档见 reservation_seeds_核对 / visa_check_核对_2026-10-25.md

---

## 0. 结论摘要

- **铁律 22/23 是本域地基**：只做带参 deeplink 手off 不代客交易；无退改摘要禁止跳转；支付动作永远由用户在渠道侧完成。
- **预约自动化三档栈**（G1 落地升格）：L1 抢票日历+直达（零依赖恒可用）→ L2 渠道可订性（国内联盟主力，key 即插）→ L3 下单闭环（**非 ACP 主案**，全链已通）。档位由我们/客户自选（/select 端点），请求档不可用自动降级并注明（永不为空）。
- **两条语义纠偏**（用户 2026-10-25）：①中国票务库存不依赖 Klook/Trip.com——L2 主力=携程联盟/同程/美团，Klook/Trip.com 是外国人下单面；②预约制馆（故宫类免费票）配额在官方小程序，**任何联盟 API 查不到**→ L2 诚实返回 official_quota，商业 SKU 才查渠道。
- **外部通道现状**：支付宝支付 MCP=收单语义（未来订阅用）；飞猪 FlyAI=库存腿候选（资质待查）；Trip.com agentic 走 Mastercard 轨（2026-09 官宣）=观察项非依赖。

---

## 1. 域全景：从「想去」到「订好」

```
wishlist（行程中心）──→ 规划吸收为必去（_absorb_wishlist）
        │
        ▼
行程条目（VisitItem）──┬─→ 预约制馆 → G1 三档栈（本档 §2）
        │              └─→ 商业票/机/酒/火车 → 行动编排（§6.11 既有）
        ▼
action_handoffs（漏斗留痕）──→ 渠道支付（用户）──→ 回填三层管道（§3）
        │                                          ↓
        └──────────────────────────→ poi_reviews「抢到/没抢到」→ 自产热度飞轮
```

---

## 2. 预约自动化三档栈（G1 核心，2026-10-25 落地）

### 2.1 名单（数据层）

`services/reservation_seeds.py`——17 馆结构化 `{days, release, note}`：

| 字段 | 语义 | 例 |
| --- | --- | --- |
| days | 提前 N 天放票 | 故宫 7、恭王府 10、莫高窟 30、熊猫基地 14 |
| release | 放票时刻（"00:00"=未注明） | 故宫 20:00、国博 17:00、陕历博 17:00、三星堆 20:00 |
| note | 渠道提示（小程序名/护照可用性/外籍限制） | 「陕历博仅二代身份证，外籍需代订」 |

- 校订状态：4 家官方直核（2026-10-25）+ 巡检层三轮核对（恭王府 7→10 天、莫高窟 15→30 天等，来源见 DESIGN/reservation_seeds_核对_2026-10-25.md）；其余标注待核。
- **数据库优先**：pois.reservation_* 三列（迁移 0010，已在真库执行）；名单只在库列空时兜底；后续携程 sight 页「需预约」标识回源补量接管。
- 匹配：`_same_site` 容错（「故宫博物院」≈「故宫」）。

### 2.2 三档（服务层 services/booking_auto.py）

| 档 | 形态 | 现状 | 升级条件 |
| --- | --- | --- | --- |
| **L1 提醒+直达** | ①放票任务：开抢日 = 游玩日 − days（`build_reservation_tasks`，start_date 缺失则日期留空任务仍在）②联盟带参直达：`booking_link_for`（Trip.com 搜索模板 {keyword} 占位；alliance_id/sid **双非空才附加**——转链交易中心同款纪律） | ✅ 全功能，零依赖恒可用 | — |
| **L2 渠道可订性** | `Availability` 枚举：ok/low/sold_out/**official_quota**/unknown（五态；客户简报写四态系 official_quota 加入前快照）；`AvailabilityProvider` 协议+注册表（`register_provider` 插拔） | 框架就绪；无 key 诚实降级 L1 | **国内联盟 key 任一配好即活**（config：ctrip_union/tongcheng/meituan 五键任一判定）；Klook/Trip.com 仅外国人下单面 |
| **L3 下单闭环（非 ACP 主案）** | `OrderIntent`：预填 authorization_url + `requires_user_confirmation=True` 恒定 + `action_handoffs` 埋点（channel 按域名判 ctrip/klook/meituan/other，refund_summary=铁律 23 C 级）→ 用户渠道支付 → 粘贴回填 user_confirmed → 联盟对账 | ✅ 全链路通 | Mastercard-agentic/ACP 开放给第三方 agent 时换 channel 实现（OrderChannel 扩展位，架构不动） |

**降级链**：`resolve_tier` 请求档不可用自动回落并注明（L3→L2→L1，永不为空；L1 恒可用）。
**AC P 观察**（非依赖）：Mastercard×Trip.com agentic（2026-09 官宣，UCP 阵营）、支付宝智能体交易（国内真正的 ACP 时刻大概率在此）、飞猪 FlyAI 资质——季度扫，任一落地评估 channel 升级。

### 2.3 端点（api/booking_auto.py）

| 端点 | 档 | 语义 |
| --- | --- | --- |
| GET `/api/v1/booking-auto/tiers` | — | 档位目录（available/fallback_note）——**客户选择器数据源** |
| POST `/tasks` | L1 | 行程 visits + start_date → 放票任务清单（行前抢票日历） |
| POST `/check` | L2 | 场馆可订性（名单命中→official_quota 短路；商业 SKU→provider；无 key→unknown） |
| POST `/order-intent` | L3 | 预填下单链接 + handoff 埋点 + **geo 分流**（XFF 首段→CN 段表判定：境内→美团模板 / 境外→Trip.com 模板；显式 booking_url 优先；返回 geo_channel/client_ip） |
| POST `/select` · GET `/selected` | — | **客户自选档位**（设备级记忆；登录态接入后随账号走） |

### 2.4 H5（sw v26）

- **行前抢票日历**：行程卡顶部金黄卡——每馆一行「📅 开抢日 时刻 开抢 · 馆名（提前 N 天，游 X 日）+ 直达→」；数据 = /tasks。
- 站点行「🎫 提示 + 抢票直达 →」→ /order-intent 开预填页；toast 引导「支付后回订单页粘贴确认」。
- 免签横幅（240h 校验，§3.6）同卡区。

### 2.5 测试与验收

test_booking_auto.py 12 用例（引擎评测集同日扩样 10→15 并抓出「餐厅被重排出餐窗」真回归——见简报）：降级链（无 key L2→L1）/日期数学（第 3 天游−7 天=开抢日）/联盟参数条件附加/official_quota 分流/支付永归用户（requires_user_confirmation 恒 True）/伪闭环（order-intent→handoff opened→回填管道可达）/档位自选 API。全量 1099 绿。

---

## 3. 订单回填三层管道（v2.4 既有，本域收口段）

1. **粘贴回填为主**：订单短信/截图 → `apply_paste_return`（正则锚点+金额解析，conf<0.8 进待确认）→ user_confirmed；
2. **返回询问为辅**；**手动标记兜底**（`apply_manual`）；均可撤销（undo）；
3. **联盟订单同步**（`alliance_sync`，签约后）→ alliance_verified → settled。

**三档栈的收口**：L3 的 order-intent 发起即 `HandoffStore.create`（opened）——与上管道无缝衔接（v2.4 状态机 opened→user_confirmed→alliance_verified→settled 不变）。**伪闭环=A CP 等价体验**：发起-支付-回传三段全通，只差联盟自动对账一段（签约即补）。

## 4. 退改签（铁律 23 承接）

- L3 埋点 refund_summary = 「人工渠道预订，退改以下单页为准（C 级）」；
- 渠道结构化退改（A 级）随联盟 API 接入补（action_handoffs.refund_policy JSONB 已有列）；
- 12306 火车票天然全可退（B 级官方梯次费率，v1.9.4 规则库设计不变）。

## 5. 数据飞轮（自产热度，独占）

- **poi_reviews**（poi_feedback store）：卡片 👍/👎/✅到了/✍️点评（标签含入境专属：外卡支付可用/英文菜单·服务/护照预订友好/免签适用）；
- **poi_stats** 夜聚合（aggregate_poi_stats，03:40）：trip_items 行为（wish/plan/visit/dislike）+ 反馈计数 + xhs_mentions；
- **远期（本域关键）**：点评卡增「抢到/没抢到」标签 → official_quota 场馆经验售罄规律（几点放票几分钟没）——预约配额不可查的唯一合规补法，渠道拿不到的独家数据；
- 排序公式消费：`top_pois_in_city` score × 自产热度（1+wish+plan）。

## 6. 渠道矩阵（本域视角，衔接主文档 §3.5）

**booking 按钮 geo 分流（2026-10-25 用户拍板，已落地）**：境外 IP→Trip.com、国内 IP→美团。实现 = `services/geo_split.py` 纯函数（XFF 首段优先 → APNIC CN 委派段表 `data/cn_ip_ranges.txt` 8,797 段判定，mtime 热更零第三方库）；私网/回环/未知/段表缺失 → **境外侧默认**（主要客户是外国人，宁绕国际站不错推国内站）；前端零判断（服务端选好成品 URL）。

| 用途 | 主力 | 备注 |
| --- | --- | --- |
| L2 国内库存 | **携程联盟（u.ctrip.com，个人可申请）/ 同程 / 美团** | 任一 key 配好 L2 即活 |
| L2 库存候选（远期） | **飞猪 FlyAI**（全品类 AI 接入，资质待查，与携程联盟同批申请） | 角色=后端库存 API |
| L1/L3 外国人下单面 | **Trip.com**（护照+外卡+英文；即携程国际版同一库存）/ **Klook**（亚洲 SKU 强） | 不作库存主源 |
| 官方配额（预约制馆） | 官方微信小程序（无 API） | L1 提醒+代抢直达是唯一解；售罄兜底=护照窗口购票 |
| 收款（未来订阅/自营） | 支付宝支付 MCP Server /「AI付」（收单语义，需企业主体+商户号） | 非代客支付 |

## 变更记录

| 版本 | 内容 |
| --- | --- |
| v1.1 | 2026-10-25 geo 分流落地：geo_split.py（XFF→APNIC CN 段表 8797 段/mtime 热更/安全侧默认）+ order-intent 接线（返回 geo_channel）+ 3 测；§2.3/§6 更新 |
| v1.0 | 2026-10-25 初版（与代码同步）：三档栈定稿（非 ACP 主案）、两条语义纠偏、名单/端点/H5/测试全清单、回填管道收口、渠道矩阵、数据飞轮 |

---

## 7. 文档关系（2026-10-25 定稿）

- 原 `Booking for client.md`（客户简报）已合并进本文 §8 并删除——**本域只此一档**；
- 主文档 planning_engine_upgrade §14.7 为指针指向本文；PROGRESS 活文档记录实现批次；
- 巡检层后续客户向更新一律写本文 §8（不再重建简报文件）。

---

## 8. 客户速览（原 Booking for client.md 精华合并，2026-10-25 起单档）

### 8.1 能力速览（给客户/老板的 5 分钟版）

**针对入境游客第一实操痛点——「故宫类门票微信小程序提前 N 天放票秒光、外国手机号常预约失败」——建成三档可选拍档，档位由您自选，不可用时自动降级并注明（L3→L2→L1，永不为空）：**

| 档位 | 能力 | 说明 |
| --- | --- | --- |
| **L1 提醒直达** | 放票任务 + 带参直达链接 | 提前 N 天 × 放票时刻（如故宫 20:00）生成抢票提醒，一键直达官方渠道 |
| **L2 库存感知** | + 渠道可订性 | ok / low / sold_out / official_quota / unknown 五态；联盟 key 未配时诚实降级，不编造 |
| **L3 下单闭环** | + 预填下单链接与回填收口 | 生成带参授权链接、`requires_user_confirmation=True`——支付动作始终由用户在渠道侧完成 |

**同日配套**：240h 过境免签权威校验（确定性规则引擎、65 口岸全表、24 省勘误、行程页红/黄/绿横幅）；雨天对调建议；互动闭环（👍/👎/打卡/点评/批量导入）；数据补全真跑（点评摘要蒸馏 + 露天/室内属性约 1400 条入库；poi_stats 夜聚合每日 03:40）。

**质量状态**：全量测试 1105 通过、lint 干净；引擎常识约束评测集（对照 TravelPlanner 基准的 P0 硬闸门）扩样 10→15 并借此抓出「餐厅被重排出餐窗」真回归；双层监控每 2 分钟巡检保绿。

### 8.2 边界与诚实声明（恒挂）

- L3 不代支付：生成下单意图链接，用户确认后跳转渠道完成（铁律 22；协议接入前这是唯一诚实形态）。
- 库存态依赖联盟 key：未配置时显示 unknown/official_quota 而非猜测；预约制馆（故宫类免费票）配额在官方小程序，任何联盟 API 查不到——L1 提醒+代抢直达是唯一解。
- 名单类事实（预约规则/免签口岸）均来自官方源逐项核对，留档可审计：reservation_seeds_核对 / visa_check_核对_2026-10-25.md。
