# 规划引擎升级与底库富化设计 — ChinaTrip

日期：2026-10-24
基准：本仓库代码现状（feat/v24-trip-center, c1a7dfd + 未提交 WIP）× 11 家竞品调研（Wanderlog / Trip Planner AI / Layla / TripAdvisor / 携程问道 / 马蜂窝 AI / 小红书点点 / Instagram / TREK / AdventureLog / LetsFG / 圆周旅迹）+ 本仓代码核查（哪些数据已到手在丢）
状态：**待用户审查**（v1.4 二轮外部对照完成；P0 已实施中——以 [PROGRESS 活文档](planning_engine_upgrade_PROGRESS.md) 为准，本文档不再同步逐项状态）

开发量标尺（单人开发）：S ≤ 2 天；M ≤ 1 周；L > 1 周。
重要度：高 = 直接决定推荐质量 / 规划可用性 / 用户信任；中 = 体验增强；低 = 锦上添花或依赖远期条件。
关联：[系统设计 V2.5](travel_agent_system_design%20V2.5.md) §6.9/§6.2、[数据库设计](database_design.md) §6、[功能缺口与开发计划 2026-10-23](feature_gap_and_dev_plan_2026-10-23.md) §4.2/§5

---

## 1. 结论摘要

- 竞品拆解结论：**没有一家靠"LLM 更聪明"赢**——TripAdvisor 靠评论库 grounding，Wanderlog 靠 Google Places 全量卡片，马蜂窝/携程靠自有语料与库存，Layla 靠创作者视频（2026-07 被 Expedia 收购）。我们引擎弱在**候选层**（每城高德 `"景点"` 搜索仅 8 条，`plan.py:73-74`）与**信号层**（LLM 只见 `名称（城市｜类目）`，`plan.py:2290`）；v2.5 建好的 pois 24 列 / restaurants 表**一个富化字段都没进选点链路**；solver 裸跑（`_solve` 传 `poi_hours=[]`、无 travel matrix）。
- 代码核查最大发现：**三个数据源已经到手、每次回源都在返回，但落库时被丢弃**（§3.1 A 组）——这是全案成本最低、收益最直接的部分。
- 评论问题的答案分两半：**外部评论**只有携程 sight 页 + 高德评分 + TripAdvisor（审批中）三个合法源；**自产评论**（四层互动闭环，§4）才是个性化与热度的长期来源——`trip_items` 每天产生的行为本身就是评论数据，缺的只是聚合表。
- 小红书**没有官方内容 API 可走**；圆周旅迹的"小红书能力"= 贴链接解析（与本仓管线同构），其可吸收点是**批量导入**与**行程地图**，不存在要追的"数据通道"。
- 地理规划器：TREK 是地图为中心的**手动**规划器（无自动地理引擎）；我们的正确姿势是做**自动版**——商圈聚类分日 + 地图增强（gap #C 原计划）+ 拖拽联动。

---

## 2. 现状问题定位（引擎三层拆解，附代码证据）

| 层 | 现状 | 代码证据 | 后果 |
| --- | --- | --- | --- |
| 候选层 | 每城一次高德 text 搜索 `"景点"` 取前 8；amap 失败落占位假 POI；底库（pois 表）不参与主候选池（只用于心愿落实、备选补足、营业时间） | `_collect_candidates`（plan.py:2125）、`POI_KEYWORD`/`POI_CANDIDATES_PER_CITY=8`（plan.py:73-74） | 候选池小、无品类多样性、无质量信号 |
| 选点层 | LLM 单轮从候选清单挑选；清单行 = `名称（城市｜类目）`+距餐饮锚点距离；duration 由 LLM 拍（兜底 60） | `_select_pois`（plan.py:2275-2331）、`_coerce_v0_items` | LLM 盲选名字；评分/时长/标签/简介全看不见 |
| 排期层 | CP-SAT 已建好但喂不饱：`poi_hours=[]`（营业时间事后 enrich 不进约束）、无 travel matrix（目标退化为 makespan）、固定 08:00–21:00 窗、best_visit_time 不消费（设计文档挂账）；餐厅只在用户链接锚点时进计划，`recommend_restaurants`（restaurants.py:256）已写好未接线 | `_solve`、`solver.py:31-33`、`_assemble_plan` | 一天横穿城三趟、夜景排上午、饭点空洞 |

---

## 3. 底库表/字段补全清单（核心）

> 分四组：A = 已到手在丢（成本≈0）；B = 回源可得需新列；C = restaurants 专属；D = 评论域新表。
> 铁律不变：外部源仅骨架，时间敏感字段只信高德/携程回源链；每个富化字段带 `*_source` 溯源列。

### 3.1 A 组：已到手在丢（P0，一个迁移 + 现有作业扩字段）

| # | 字段 | 表 | 数据源（可得性） | 消费方 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | `rating` 写回（列已有） | pois/restaurants | 高德 v5 detail `business.rating`，回源链**每次都返回**（amap_client.py:554-580），refresh_pois 只写 address/hours | 选点排序、卡片、备选排序 | **高** | S | refresh_pois 与 `PoiDetailStore.upsert` 扩签名各一处；`rating_source=amap` |
| A2 | `photos` 写回（列已有） | 同上 | v5 detail `photos`（`_normalize_photos` 已写好，amap_client.py:99） | 站点气泡、灵感卡 | 中 | S | wikimedia 照片优先不覆盖（只填空），`photos_source` 区分 |
| A3 | `phone`/`website` 写回（列已有） | 同上 | v5 detail `tel`/`website` | 详情页、导航辅助 | 低 | S | 只填空，顺 A1 一起接 |
| A4 | `suggested_duration_min` 回源（列已有） | pois | **携程 sight 页同页「建议游玩」字段**——CtripHoursReader 已在抓该页，只正则了开放时间（ctrip_hours.py:61） | solver 时长、选点 duration 兜底（替代拍 60） | **高** | S | `duration_source=ctrip`；LLM 兜底已有（backfill_best_visit 同模式） |
| A5 | `rating_count`（**新列** INT） | pois/restaurants | 携程 sight 页点评数（同页） | 热度分母：rating 4.9×3 人评 ≠ 好店；排序公式核心输入 | **高** | S | 与 A4 同一次页面解析 |
| A6 | `review_tags`（**新列** JSONB）+ `review_tags_source` | 同上 | 携程 sight 页点评标签 chips（亲子/拍照出片/人太多…）+ LLM 常识兜底 | 选点解释、天气/人群匹配、推荐理由 | **高** | M | 页面 chips 解析 S；LLM 兜底批跑搭 backfill_best_visit 周期 |

### 3.2 B 组：回源可得需新增列（P0–P1，随 0009 迁移）

| # | 字段（新列） | 表 | 数据源 | 消费方 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | `district`（行政区）+ `business_area`（商圈） | pois/restaurants | 高德 v5 detail adcode/business area；regeo 兜底 | **地理规划器地基**（§6 聚类分日） | **高** | S | 索引 `(city, business_area)`；随 A1 写回 |
| B2 | `indoor` / `rain_ok`（enum-ish：yes/no/partial） | pois | 无现成源 → 三层回填（类别启发式【博物馆=室内/广场=露天】→ LLM 批量 → 回源校验），复用 backfill_best_visit 模式 | **天气感知重排**：weather_reports 已三班抓（高德+Open-Meteo 14 天），当前零字段消费 | **高** | M | 回填作业本体 M；排程消费 S |
| B3 | `ticket_price_min/max` + `ticket_source` | pois | 携程 sight 页门票价（主源）；高德 `cost` 对景点不可靠不采 | 预算估算（gap #6）、门票 deeplink 预填 | 中 | S-M | 与 A4/A5 同页；免费景点显式 0/0 |
| B4 | `name_aliases`（JSONB） | pois/restaurants | 自产：`_same_site` 运行时命中即回写；携程页别名 | 匹配命中率（"大足石刻景区"≈"大足石刻"） | 中 | S | 回写点在 `_record_link_sites`/`_merge_must_visits` 判重处 |
| B5 | `duration_source`（VARCHAR 20） | pois | 溯源列 | 铁律 2 合规 | 低 | S | ctrip/llm/default |

### 3.3 C 组：restaurants 专属（P1–P2，随 0009 迁移）

| # | 字段（新列） | 数据源 | 消费方 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | `signature_dishes`（JSONB） | 携程美食页推荐菜；高德 food 详情 | 餐厅卡"招牌菜"、点菜翻译场景 | 中 | M | 美团/点评不可直连（判例），只走回源 |
| C2 | `taste/env/service_score`（NUMERIC 3,1 ×3） | 高德 v5 深度信息 | 餐厅排序细分（现只有总分） | 低 | M | 个人 key 字段可得性待控制台实测，实测前不排 |
| C3 | `price_level`（派生） | `avg_cost` 派生（≤50/50-100/100-200/200+） | "平价必比登优先"产品口径 | 低 | S | 纯派生列，应用层算即可，可不落库 |
| C4 | `meal_periods`（JSONB：早茶/正餐/夜宵） | `opening_hours` 规则派生 + LLM 兜底 | solver 餐窗匹配（MEAL_WINDOWS 固定窗→按店匹配） | 中 | M | 早茶城市（广佛）体验差异明显 |

### 3.4 D 组：评论域新表（P0 建表，消费随互动闭环分期）

| # | 对象 | 内容 | 数据源 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | **`poi_reviews` 新表** | poi_id/user_id/device_id/rating(1-5)/tags[]/text/visited_at/source(post_visit\|card_thumbs\|chat)/created_at | **100% 自产** | **高** | S | 建表+写入端点 S；展示随 §4 |
| D2 | **`poi_stats` 新表** + 夜聚合作业 | poi_id PK/wish_count/plan_count/visit_count/dislike_count/thumbs_up/xhs_mentions/updated_at | **100% 自产**：`trip_items` GROUP BY（wishlist=add、scheduled=plan、unwanted=dislike）——行为每天都在产生，现在全部挥发 | **高** | S | 夜作业 03:40 全量重建（量小幂等）；**这是竞品拿不到的自有热度源** |
| D3 | `review_summary` + `review_summary_source`（pois 新列） | 一句话点评摘要 | LLM 蒸馏自合法源并集（携程点评标签+自产评论+米其林/黑珍珠评语） | 中 | M | 五关校验复用 backfill_intro_llm 模式；source=llm 如实标注 |

### 3.5 数据源连通性总矩阵（五档分类，2026-10-24 逐家查证）

> 按门槛分档：A = 无 key 已在用；B = **注册/申请即可连（个人能办）**；C = 需企业主体/真实流量；D = 申请也基本连不上；E = 无通道（爬虫判例区）。
> 评论域口径衔接：携程 sight 页与高德评分 = A 档已在手（§3.1 A 组，同页扩字段即可）；TripAdvisor 评论 = C 档（下表）；点评/美团/马蜂窝/Google/小红书的**评论本体** = D/E 档一律不做，只做行为计数（§4-②、§5.3）。

| 档 | 源 | 怎么连 | 能拿到什么 | 评论 |
| --- | --- | --- | --- | --- |
| A 已在用 | 高德（个人 key）/ 智谱 GLM / 12306 / Wikidata·维基 / OSM planet 小时增量 / 米其林 GitHub CSV / 5A 名录 / UNESCO / Open-Meteo / 黑珍珠人工导出 | 无 key 或已有 | 现管线全部 | 零动作 |
| **B 申请即连** | **FSQ OS Places** | [Places Portal](https://docs.foursquare.com/data-products/docs/access-fsq-os-places) 自助注册→生成 token；免费档（新 Pro 结构约 500 次/月，另有 HuggingFace 数据集走批量不经 API） | 全球 POI/餐厅骨架，补餐厅密度 | **现在就能办**；数据库设计已排 L2 月更 20 日（delta 文件契合 DIFF UPDATE） |
| **B 申请即连** | **携程开放平台/联盟** | [u.ctrip.com](http://u.ctrip.com) 个人身份证实名即可（2020 年起对 KOC/小 B 开放）；注册→资质认证→媒体/推广位 | 转链 + 商品库（酒店/门票/火车票），佣金结算通道 | **现在就能办**；API 结构化权限注册后按媒体分级再升 |
| **B 申请即连（有前置）** | **淘宝联盟→飞猪** | [pub.alimama.com](https://pub.alimama.com) 个人推客可注册；**API 调用需媒体备案**（网站型：域名+ICP 备案，约 1 天审过）→推广位 PID→appkey→API 权限 | 飞猪商品转链/订单/佣金（酒店机票门票） | 我们 H5 有域名即可办网站型备案；飞猪"问一问"为 2025 国内 AI 助手评测第一，商品覆盖值得接 |
| **B 申请即连** | **美团联盟（推客层）** | [media.meituan.com](https://media.meituan.com) 个人：身份证+实名、18-60 岁 | 美团系转链（外卖/酒店/门票） | **注意**：推客转链个人可用，**API/媒体接口层需企业营业执照**（设计 v1.9 判据仍成立）；先注册占位，API 等主体 |
| **B 申请即连** | **Klook affiliate** | [affiliate.klook.com](https://affiliate.klook.com) 申请（或走 Travelpayouts）；[Open API 文档](https://klook.gitbook.io/openapi)公开 | 中国门票/活动覆盖最强的海外平台商品+佣金（2–5%） | 入境游方向（Phase 2 友好）；affiliate 链接级个人可申请 |
| **B 升级现有** | **高德企业认证** | 营业执照落地当天申请（设计 v1.7 既定动作） | 免费配额提升+商用合规确认 | 公司主体落地即办 |
| C 需企业+流量 | **TripAdvisor Content API / Terra** | [官方页](https://www.tripadvisor.com/hotels/content-api)提交 partner 申请→**商务团队个案审批**，无自助 key；需真实业务+流量+展示合规（署名/logo/回链）；价格谈判制 | 全球评论/评分/照片/详情 | **优先级提升（§3.6：主要客户=外国人）——原 L4 兜底改为「公司主体落地即申请的第一批」**；对入境用户 TA 星标同时是信任转化手段 |
| C 需企业+流量 | Klook Open API（distribution 级）/ 飞猪开放平台完整 API 组 / 美团开放平台 API | 企业资质+商务对接 | 结构化商品库存/订单同步 | 均为公司主体落地后动作 |
| D 基本连不上 | 小红书内容 API（机构限定）/ Meta Instagram PCA·oEmbed（App Review 高拒签+大陆开发者+无中国数据）/ Google Places（ToS 禁缓存+大陆不可达）/ 大众点评（无开发者内容 API）/ 马蜂窝（ToS 禁抓） | — | — | 一次定死不再讨论；小红书走 §5 三招；Instagram 走链接解析 |
| E 无通道 | 任何形式批量抓取内容本体 | — | — | 判例红线，不碰 |

**现在就能办的三件事（零企业主体、零成本，建议本周）**：① FSQ Places Portal 注册拿 token（餐厅密度补量）；② 携程开放平台个人注册实名（转链+商品库，转链交易中心的正主渠道）；③ 淘宝联盟个人推客+网站媒体备案（飞猪商品通道）。三家都是 B 档，注册本身不产生义务，先用起来看数据质量。

### 3.6 入境游客评论源（2026-10-24 用户定调：主要客户=外国人，优先级反转）

> 外国人看中国游评论的真实渠道排序：TripAdvisor（西方游客第一信源）> Google Reviews（默认习惯，❌ 不可用）> Trip.com 国际版（外国游客对中国酒店/景点的英文点评）> Klook/GetYourGuide（亚洲玩乐）> Yelp（无中国数据）。**结论：有结构化"外国人评论"API 的只有 TripAdvisor 一家**，其余平台的评论在页面上但不开放 API——策略分三层。

| 层 | 源 | 通道 | 能拿到什么 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- | --- |
| ① 提前申请 | **TripAdvisor Content API / Terra** | C 档（企业+流量，商务个案审批） | 中国 POI 的外国游客评论/评分/照片 + **信任角标**（外国用户认 TA 的星标） | **高**（客户=外国人） | M | **原 L4 兜底升级为「主体落地即申请的第一批」**；对入境用户，TA 星标同时是转化手段（display 合规=署名+logo+回链） |
| ② affiliate 实测 | **Klook affiliate / Trip.com（Travelpayouts）/ GetYourGuide·Viator partner** | B~C 档（Klook/Travelpayouts 个人可申请） | 商品+转链是确定项；**部分 affiliate/distribution API 返回产品评分**（Klook 产品卡带 rating）——评论本体不开放 | 中 | S-M（实测） | 注册后第一件事=实测评分字段可得性；拿得到就进 `rating`（source=klook 等），拿不到就只做转链 |
| ③ 自产（最契合） | **我们自己的用户** | 无需申请 | `poi_reviews` 由外国游客产生——**天然就是"外国人视角"评论库**（英文菜单？外卡支付？护照预订？这些只有外国游客会评） | **高** | S（表已设计 §3.4） | 冷启动用 TA/affiliate 评分，自产积累后成为独家资产：国内平台拿不到、外国平台没覆盖的第四方视角 |

**不可用判定（一次性）**：Google Reviews = Places API 明确禁止缓存评论 + 大陆 POI 稀疏 → 不做；Yelp = 零中国数据；Reddit = 官方 API 商用内容条款严格 → D 档不碰。

**VPN 可达性说明（2026-10-24 用户提供：开发机有 VPN）**：VPN 解决的是**可达性**，不解决**权限**。当前数据作业全部跑在开发机（ops/*.cmd 计划任务），OSM planet 小时增量已是 VPN 依赖（osm_fetch.py 实测注记）——因此 MVP 阶段外国源抓取可行。逐家重判：Google Places = 可达性解决，但 **ToS 存储禁令**（评论/详情禁止落库，与我们"库规划只读"架构冲突）+ 中国数据稀疏 + 需 GCP 计费账号 → 仍出局；Yelp = 可达但零中国数据 → 仍不可用；Reddit = 可达但商用内容条款 → 仍 D 档；Wikipedia/Wikimedia/Open-Meteo/UNESCO = VPN 下抓取更稳，照常。**规模化警示**：作业迁阿里云 CN 区后 VPN 不存在——届时外国源要么放弃、要么等 Phase 2 海外区中转；§9.2 作业清单中以 ⛴ 标注 VPN 依赖源，迁移时逐一复核。

**schema 联动**：`review_tags` 预置标签增加**入境专属维度**（§4-④ 点评卡同步）：`外卡支付可用`（Alipay/WeChat Pay 国际版）、`英文菜单/英文服务`、`护照预订友好`、`免签适用`——这四个标签只有外国游客会给，是自产评论库的差异化起点，也直接喂选点匹配（"护照预订友好"的酒店/景点对外国人就是硬需求）。

---

## 4. 评论吸收与客户互动：四层闭环（自产评论机制）

> 原则：外部合法评论负责**展示与初排**；自产评论负责**个性化与复购**。每层 = 触点 → 存储 → 消费。

| 层 | 触点 | 存储 | 消费 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- | --- |
| ① 行前 | 澄清轮第二问升级为 4 道选择题（节奏/博物馆vs街头/早起/人均档）——抄马蜂窝"旅行性格诊断" | `user_profiles.profile.preference_tags` | 选点 prompt 偏好输入、蒸馏 | 中 | S | 画像表/蒸馏管线已有，只差采集入口；§6.1 澄清≤2 轮不破 |
| ② 规划中 | 推荐卡 👍/👎 + LLM 选点输出 `reason`（"为什么是它"一句话）；"换一个"（备选一键换入**已存在**） | 👎→trip_items unwanted+蒸馏；换入/换出计数 | poi_stats.thumbs_up/dislike；质量分加权 | **高** | S | unwanted 状态已有；reason 随 §8 选点 prompt 改造顺带 |
| ③ 行中 | 行程卡"到了"打卡按钮 | trip_items.status=visited + poi_stats.visit_count | 足迹页（gap #12）、**北极星指标端上采集器**（预测 vs 实际偏差） | 中 | M | visited 状态机扩展；execution_events 联动远期 |
| ④ 行后 | 行程结束推点评卡：星级+预置标签 chips（人多/出片/一般/亲子友好/不值 + **入境专属：外卡支付可用/英文菜单·服务/护照预订友好/免签适用**，§3.6）+可选一句话 | `poi_reviews` | (a) 聚合进 poi_stats+review_summary 重蒸 (b) 蒸馏进画像（"二刷记得你嫌人多"） (c) 站点气泡"去过的人说" | **高** | M | 冷启动靠 TA/affiliate 评分+高德评分，自产积累后自然接管权重；**自产=外国人视角独家评论资产（§3.6-③）** |

**推荐排序公式（确定性，落 `PoiDetailStore.top_pois_in_city`）**：
`score = 质量分(rating × log(1+rating_count)) × 自产热度(1+wish+plan) × 距离衰减 × 偏好匹配(preference_tags × review_tags)`
冷启动自产项=0 即退化为纯质量分——公式不变、权重随数据自然生长。

---

## 5. 小红书接入：四条路径

| # | 路径 | 状态 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- |
| 5.1 | **单链接深度解析**：web_reader 对 xhs 图文笔记补正文全文+作者定位城市+话题标签（视频链路已建成） | 部分已有（通用网页处理） | **高** | S-M | 话题标签=品类愿望线索，喂 `_wish_city_hint` |
| 5.2 | **批量收藏导入**：输入框一次粘贴 ≤30 条链接→逐条入队解析→汇总候选清单（服务端解析+进度提示，形态同圆周旅迹） | 缺（pitravel 主打卖点"收藏30篇还排不出行程"） | **高** | S | H5 侧为主；复用现有链接识别轮，改批处理+并发限速 |
| 5.3 | **行为热度代理**：链接解析事件按 POI 聚合计数进 `poi_stats.xhs_mentions` | 缺 | 中 | S | 存统计不存内容本体——合规的"小红书热度"信号 |
| 5.4 | 官方内容 API / 爬虫 / 蒲公英采买 / 发布回流 | ❌/❌/远期/反向 | 低 | — | 官方笔记 API 只对机构开放（开放平台审查结论 2026-10-24）；爬虫判例风险；蒲公英需企业主体；行程长图分享回流是增长渠道非数据源 |

红线：用户自己转发的链接单条/批量解析 = 合理使用；批量抓取内容本体 = 不碰。

---

## 6. 地理规划器（自动版，非 TREK 手动版）

> 事实：TREK 是地图为中心的**手动**规划器（协作/预算/清单/PWA），无自动地理引擎，日内路线在 discussion #435 仍在讨论。我们的差异点恰是 CP-SAT。

| # | 项 | 内容 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- |
| 6.1 | **聚类分日** | 用 `business_area`/坐标做贪心/KMeans 聚类，"哪天去哪片"从 LLM 拍脑袋改为地理聚类定片、LLM 只在片内选点 | **高** | M | feature_gap §4.2 第 6 条既定设计的落地；消灭"一天横穿城三趟"；新 `services/itinerary/geo.py` |
| 6.2 | **地图增强**（gap #C 原计划） | 按天色分筛选/序号 marker/表↔图联动/步行腿画线（legs.py 数据现成）/跨城段分色 | 中 | M | 增量改现有手写瓦片图，**不迁 MapLibre**（gap 已判缓） |
| 6.3 | 聚类挪站提示 | "这站离第 2 天片区更近，要挪过去吗" | 低 | S | 把 district 字段变成用户可见建议 |

---

## 7. 竞品逐家吸收清单

| 产品 | 吸收点 | 落到我们哪里 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- |
| Wanderlog | 地点卡三件套（评分/通常停留多久/照片）；"基于你行程的智能推荐" | A1/A4 写回 + 卡片；备选按行程上下文排序 | **高** | S | 信任层的标配，数据已在自己库里 |
| Trip Planner AI | 以酒店为锚的路线优化 | 行程加 hotel anchor 坐标，solver 软目标"晚归酒店就近" | 中 | S-M | `itinerary_days.base_city` 已有，缺住宿点字段 |
| Layla | 短视频种草流（Expedia 收购验证价值） | 远期城市灵感卡（intro+photos 现成） | 低 | — | 方向背书，不急做 |
| TripAdvisor | 评论摘要+可解释推荐；GPT-4 裸评"有用但常漏点"的教训 | D3 review_summary + LLM reason；卡片明示"已按营业时间/步行距离校验" | 中 | M | 我们比它多的 CP-SAT 可行性要显性展示 |
| 携程问道 | "权威数据验证行程"话术 | `*_source` 溯源列变用户可见"数据来源"角标 | 中 | S | 溯源基建已全有，只差 UI |
| 马蜂窝 | ①旅行性格问卷 ②完整路书（预算/贴士）③垂直语料定位 | ①§4-①；②预算=ticket_price×天数+avg_cost×餐次（依赖 B3）+打包清单（gap #11）；③自产行为语料（D2） | 中 | S / M | 问卷 S；预算汇总 M |
| 小红书/点点 | 转发笔记→总结种草；过滤广告 | §5.1/5.2；视频抽取输出 `ad_hint`（LLM 已看画面顺手判） | **高** | S | ad_hint 加一个输出字段 |
| TREK | ICS/GPX 导出、PWA、协作 | 导出/PWA 已有；协作远期（gap P3） | 低 | — | |
| AdventureLog | Atlas 足迹页 | trip_items.visited + poi_stats 即 Atlas 数据层（gap #12） | 低 | M | P2/P3 |
| LetsFG | MCP server 形态（agent 可调用） | 远期：API 包一层 MCP | 低 | M | 蹭 Cursor/Claude 生态，无紧迫性 |
| 圆周旅迹 | 批量导入、行程地图、长图分享回流 | §5.2、§6.2、OG 卡已有 | **高** | S+M | 导入协议已摸清（journey detail API） |

---

## 8. 引擎升级（LLM 侧 / 排期侧）

### 8.1 LLM 侧

| # | 项 | 内容 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- |
| 8.1.1 | **候选库优先** | `_collect_candidates` 改：每城先查 pois（`top_pois_in_city`，§4 公式排序，取 30），高德仅在库存<10 时补量（around/text 独立配额池结论复用） | **高** | S | 配额压力反而下降；占位假 POI 场景基本消失 |
| 8.1.2 | **选点 prompt 全字段** | 清单行升级为 `名称（城｜类目｜评分4.7·2.3万评｜宜傍晚｜建议120min｜unesco｜室内）`；duration 兜底读 suggested_duration_min；输出加 `reason` | **高** | S | 全部来自 §3 字段；LLM 失败时 shortlist 仍可占位 |
| 8.1.3 | 两段式选点 | 确定性 shortlist → LLM 仅 rerank+reason | **高** | S | 与 8.1.1/8.1.2 同一改造，列出以明确架构 |
| 8.1.4 | 天气感知重排 | weather_reports × indoor/rain_ok → "明天下雨，露天广场和博物馆对调"+一键改（只提示不全自动，gap #5 既定口径） | 中 | S-M | 两张表都建好了，就差这条线 |
| 8.1.5 | 评测集 | TravelPlanner 式常识约束（同店不重复/每天≤4 景点/总步行≤15km=铁律6）做 pytest 回归，mock LLM 跑 CI | 中 | M | 防选点层改造回归 |

### 8.2 排期侧（solver 已建好，全是"喂饱"问题）

| # | 项 | 内容 | 重要度 | 开发量 | 评论 |
| --- | --- | --- | --- | --- | --- |
| 8.2.1 | **best_visit_time→时间窗** | morning 08-12/afternoon 12-17/evening 17-21/sunset·sunrise 近似窗，进 `_visit_spec` 开窗 | **高** | M | 设计文档挂账的最后一块；夜景自动进晚上 |
| 8.2.2 | **travel matrix 传入** | v0 用 haversine×1.3÷80m/min（legs.py 同款）构造 cost matrix 传 `travel_minutes`；`_enrich_legs` 高德缓存反哺 | **高** | S-M | AddCircuit 目标从 makespan 切到真实动线 |
| 8.2.3 | poi_hours 进 solve | 营业时间以 PoiHours 传入（现 `poi_hours=[]` 事后补） | 中 | S | 约束先于排期 |
| 8.2.4 | **餐厅 v0 自动插入** | `recommend_restaurants`（已写好未接线）对每天午/晚餐空窗各插 1 家，米其林/必比登/黑珍珠加权 | **高** | S | 铁律 20 空窗校验现成；城市活动丰富感最大来源 |
| 8.2.5 | 品类疲劳约束 | 每天 ≤1 博物馆类（prompt 规则 + solver 软目标） | 中 | S | |
| 8.2.6 | 计划级查全率 | 5A/UNESCO 白名单 vs 当次计划——"北京 3 天没排故宫"级事故告警 | 中 | S | 底库查全率指标提到计划级 |

---

## 9. 迁移与作业设计（提案，待审查）

### 9.1 迁移 `0009_planning_engine_enrichment`

- **pois +14 列**：`rating_count INT`、`review_tags JSONB`、`review_tags_source VARCHAR(20)`、`ticket_price_min INT`、`ticket_price_max INT`、`ticket_source VARCHAR(20)`、`district VARCHAR(50)`、`business_area VARCHAR(50)`、`indoor VARCHAR(10)`、`rain_ok VARCHAR(10)`、`name_aliases JSONB`、`duration_source VARCHAR(20)`、`review_summary TEXT`、`review_summary_source VARCHAR(20)`；索引 `(city, business_area)`。
- **restaurants +12 列**：`rating_count`、`review_tags`+`review_tags_source`、`signature_dishes JSONB`、`taste_score/env_score/service_score NUMERIC(3,1)`、`price_level VARCHAR(10)`、`meal_periods JSONB`、`district`、`business_area`、`name_aliases`。
- **新表 `poi_reviews`**：id UUID PK / poi_id FK / user_id FK 可空 / device_id VARCHAR(64) 可空 / rating SMALLINT / tags JSONB / text TEXT / visited_at TIMESTAMP / source VARCHAR(20) / created_at；索引 poi_id、(user_id)。
- **新表 `poi_stats`**：poi_id UUID PK FK / wish_count、plan_count、visit_count、dislike_count、thumbs_up、xhs_mentions INT DEFAULT 0 / updated_at。
- 存量行新列全 NULL/0，不回填阻断；dev 无 PG 时沿用 poi_details 内存降级模式。

### 9.2 作业扩展与新作业（编排沿用 ops/*.cmd + 计划任务）

| 作业 | 变更 | 时机 | 评论 |
| --- | --- | --- | --- |
| refresh_pois | 写回 rating/photos/phone/website/district（A1-A3/B1） | 每日 02:00 城轮转不变 | 零新增请求 |
| ctrip_hours（CtripHoursReader） | +建议时长/评分/点评数/点评标签/门票 正则（A4/A5/A6/B3） | 随回源链 | 同页零新增请求 |
| aggregate_poi_stats（新） | trip_items GROUP BY 全量重建 poi_stats | 每日 03:40 | 量小幂等 |
| backfill_indoor_rain（新） | 三层：类别启发式→LLM→回源校验（B2） | 每周日 03:30 搭车 best_visit | 模式复用 |
| review_summary 蒸馏（新） | LLM 蒸馏合法源并集（D3） | 季批+周日滴灌搭 intro | 五关校验复用 |

> ⛴ VPN 依赖（§3.6 说明）：上表现有作业均可达（携程/高德/智谱皆国内源）；**既有管线中 OSM planet 小时增量已依赖开发机 VPN**；未来接入的 FSQ Places Portal 与 TripAdvisor API 属 ⛴ 源——迁阿里云 CN 区时需逐一复核或等 Phase 2 海外区中转。

### 9.3 服务与端点

- `PoiDetailStore`：`upsert` 扩签名（rating/photos/phone/…只填空）；新增 `top_pois_in_city(city, limit, *, exclude_food)`（§4 公式）。
- 新端点：`POST /api/v1/pois/{id}/review`（行后点评）、`POST /api/v1/trip-items/{id}/visit`（打卡）、`POST /api/v1/plan/{sid}/items/{id}/vote`（👍👎）、`POST /api/v1/links/batch`（批量导入）；`GET /api/v1/pois/{id}` 扩返回 review_summary/review_tags/stats。
- 新服务：`services/itinerary/geo.py`（聚类分日）。

---

## 10. 阶段计划（重要度 × 开发量排序）

### P0（数据地基，~1.5 周）

| 顺序 | 项 | 重要度 | 开发量 | 依赖 |
| --- | --- | --- | --- | --- |
| 1 | 迁移 0009 + A 组字段全部落库（含 upsert 扩签名、作业扩字段） | 高 | S | — |
| 2 | poi_reviews/poi_stats 两表 + 夜聚合 | 高 | S | 0009 |
| 3 | 8.1.1 候选库优先 + 8.1.2/8.1.3 选点全字段+reason | 高 | S | 1 |
| 4 | 8.2.4 餐厅 v0 插入 | 高 | S | — |
| 5 | 5.2 批量链接导入 + 5.1 图文笔记深度解析 | 高 | S+S-M | — |
| 6 | 互动②卡片👍👎（消费 unwanted 已有链路） | 高 | S | 2 |

### P1（引擎与体验，~1 月）

| 项 | 重要度 | 开发量 |
| --- | --- | --- |
| 8.2.1 best_visit 窗 + 8.2.2 travel matrix + 8.2.3 hours 进 solve | 高 | M |
| 6.1 聚类分日 | 高 | M |
| B2 indoor/rain_ok 回填 + 8.1.4 天气感知重排 | 高 | M+S |
| 互动③打卡 + ④行后点评卡 + D3 摘要展示 | 高 | M |
| 6.2 地图增强（gap #C） | 中 | M |
| A6/B3 评论标签+门票全量回填、8.2.5 品类疲劳、8.2.6 计划级查全率、7 表格中 S 级小项（溯源角标/ad_hint/hotel anchor/问卷） | 中 | S×n |

### P2（增强，随量）

C1-C4 餐厅深字段、7 表格 M 级项（Atlas 足迹/预算汇总）、8.1.5 评测集（建议提前到 P1 末）、MCP、蒲公英、协作。

**触发器清单（不排期，条件到即办）**：公司主体落地 → 当天办 TripAdvisor Content API 申请（§3.6-①）+ 高德企业认证 + 美团 API 层；Klook/Travelpayouts 注册后 → 立即实测 affiliate 评分字段可得性（§3.6-②，半天工作量）。

---

## 11. 风险与红线

| 风险/红线 | 等级 | 对策 |
| --- | --- | --- |
| 爬虫红线（小红书/点评/马蜂窝内容本体） | P0 | §3.5/§5 判定一次定死；只做链接解析与行为计数 |
| 携程 sight 页扩字段扩大解析面 | 中 | 同页零新增请求；最小量+白名单口径不变 |
| LLM 蒸馏幻觉（review_summary/indoor/rain_ok） | 中 | 五关校验复用 backfill_intro_llm；`*_source` 如实标注；排序只用确定性公式 |
| 高德配额（top_pois_in_city 若触发补量） | 低 | 库优先本就降配额；补量走 around 独立池 |
| poi_stats 隐私 | 低 | 只存聚合计数，不存个人浏览轨迹；评论文本归用户可删 |
| 存量行新列 NULL 兼容 | 低 | 公式全部 NULL 容忍（log(1+count) 缺 count 视 1） |

## 12. 评测与验收

- 回归：§8.1.5 约束用例进 CI（mock LLM）。
- 计划级查全率：5A/UNESCO 白名单命中告警（§8.2.6）。
- 选点质量 A/B：新旧 prompt 同城对比（同一 LLM、同候选池），人工评 top-3 合理性。
- 互动漏斗指标：卡片反馈率 / 打卡率 / 行后点评率 / poi_stats 覆盖城市数（进 §7 评估体系）。

## 变更记录

| 版本 | 内容 |
| --- | --- |
| v1.4 | 2026-10-24 §14 第二轮外部对照审查（用户定调：优化面向外国游客的引擎能力）——三路调研（GitHub 开源/商业主流/入境产品）：① 架构论点获外部验证（四件套无开源全占、TravelPlanner GPT-4 通过率 0.6%→8.1.5 评测集升 P0 硬闸门、纯优化器商业全灭→信任角标+预订深链是另一半）；② 新增六缺口 G1-G6：预约制门票约束（入境第一实操痛）、240h 免签行程校验（独家信任功能）、多窗营业时间（solver 单窗实锤）、拖拽后时间重算、行程离线可开（西方规划器被墙的结构性优势兑现）、交通腿结构化 payload；③ 语言层明确排除（用户后做）；④ §3.6-② 触发器补 affiliate 代抢覆盖度实测；⑤ 工作区漂移快照（top_pois_in_city 已接线、8.2.1 已落） |
| v1.3 | 2026-10-24 §3.6 增 VPN 可达性说明（用户补充：开发机有 VPN）——可达 ≠ 权限：Google/Yelp/Reddit 逐家重判仍出局（ToS 存储禁令/零中国数据/商用条款）；MVP 阶段外国源抓取可行（作业跑开发机，OSM 已 VPN 依赖）；规模化迁阿里云后 ⛴ 标注源需复核 |
| v1.2 | 2026-10-24 新增 §3.6 入境游客评论源（用户定调：主要客户=外国人，优先级反转）——TripAdvisor 从 L4 兜底升为「主体落地即申请的第一批」（唯一结构化外国人评论 API）；Klook/Trip.com/GetYourGuide affiliate 评分字段实测路径；自产评论=外国人视角独家资产；review_tags 增入境专属标签（外卡支付/英文服务/护照预订/免签）；§3.5 C 档 TA 行与 §10 触发器清单同步；审查版格式 docx→PDF（横版 A4，表格优化） |
| v1.1 | 2026-10-24 §3.5 扩为数据源连通性五档总矩阵（A 已在用 / B 申请即连【FSQ·携程开放平台·淘宝联盟飞猪·美团推客层·Klook affiliate·高德企业认证】/ C 需企业+流量【TripAdvisor Content API 等】/ D 基本连不上 / E 无通道）+ "现在就能办的三件事"行动项（逐家申请通道查证） |
| v1.0 | 2026-10-24 初稿（待审查）：三层问题定位、A-D 四组字段清单（含外部评论源判定）、四层互动闭环、小红书四路径、地理规划器三项、竞品吸收清单、LLM/排期升级、迁移 0009 与作业设计、P0-P2 计划 |

---

## 13. Claude 审查意见（2026-10-24，锚定工作区实测）

> 审查方式：文档内部逻辑推演 + 三路并行探针对 feat/v24-trip-center 工作区（c1a7dfd + 未提交 WIP，约 +719 行）实测核查。事实断言逐条对照当前代码，不以文档自述为准。

### 13.1 总体判词

主干成立：A 组「已到手在丢」是全案最硬的发现，「库优先 + 全字段 prompt + 两段式选点」是低成本高确定性改法，五档数据源矩阵一次定死争议。文档描述的三层病灶在基线代码中**全部属实**（13.2 逐条核对），但工作区 WIP 已把 A 组大半与 8.2.1 一部分落地——本审查的剩余价值集中在**还没动**的部分：次序（评测先于 prompt 改造）、拓扑（poi_stats 跨库聚合没写明）、公式细节（零杀与双源混算）、以及三处「写好未接线」的措辞与排期修正。

### 13.2 文档断言 vs 工作区实测（2026-10-24）

| # | 文档断言 | 实测 | 判定 |
| --- | --- | --- | --- |
| 1 | 每城一次「景点」搜索取 8 条，失败落占位假 POI | plan.py:72-73 常量、2124-2165 逻辑一致，占位 POI 带 assumption | ✅ 属实 |
| 2 | LLM 只见 `名称（城市｜类目）` | plan.py:2290；有食物锚点时附加距离后缀（2291-2299），是行内唯一数值信号 | ✅ 属实 |
| 3 | pois 底库不进主候选池 | 基线属实（仅心愿落实/愿望城市/营业时间三处用库）；**WIP 已建 `top_pois_in_city`（poi_details.py:294，score=rating×log2(1+count)×标签加成）但 plan.py 尚未调用** | ⚠️ 基线属实，WIP 半程 |
| 4 | 「无 travel matrix（目标退化为 makespan）」 | **机制已实现**：AddCircuit + 矩阵弧 cost（solver.py:131-164、249-250），无匹配回退 30min；是 plan.py 全链路从不传 `travel_minutes`（_solve 仅传 poi_hours/time_budget） | ⚠️ 措辞应改「写好未接线」，效果等同 |
| 5 | `poi_hours=[]` 营业时间不进约束 | plan.py:2910 等多处；**比文档更严重：5 处 validate_plan 同样传空 → 规则 2 营业时间校验全链失效**（rules.py:377- 无数据跳过） | ✅ 属实且被低估 |
| 6 | 固定 08:00–21:00 窗 | solver.py:32-33 | ✅ 属实 |
| 7 | rating/photos 回源在丢 | 基线属实；**WIP 已修大半**：refresh_pois 落 rating/rating_count/photos/phone/business_area（携程 detail_fields + 高德 _extras 合并），且 hours 未中也有 enrich-only 兜底路径；**website/district 形参已备但链路无来源** | ⚠️ 基线属实，WIP 大半已落 |
| 8 | 携程 sight 页只正则开放时间 | 基线属实；**WIP 已扩全**：评分/点评数/门票/建议时长/点评标签（ctrip_hours.py:66-79、139-154） | ⚠️ 基线属实，WIP 已落 |
| 9 | recommend_restaurants 写好未接线 | restaurants.py:256，全仓调用仅 tests | ✅ 属实 |
| 10 | duration 兜底拍 60 | plan.py:75 `DEFAULT_VISIT_MINUTES=60` | ✅ 属实 |
| 11 | §9.1 迁移 0009（提案） | **已存在**：alembic/versions/0009 与 §9.1 基本一致（pois +14 列、restaurants +12 列、poi_reviews/poi_stats 两表、(city,business_area) 索引），目标 PG | ⚠️ 已从提案变现实 |

**汇总**：基线病灶全部属实；但状态行「未开工；迁移号、字段名均为提案」已失实——0009 已写、A 组约七成已落、8.2.1 开窗部分已落（solver.py:38-49、77-85）、top_pois_in_city 已建。**当前最大风险不是「方案对不对」，而是文档-代码漂移导致评审失效与重复开发。**

### 13.3 开工前必须解决（按对 P0 收益的影响排序）

1. **评测先于 prompt 改造**。8.1.5 排在 P2，而 8.1.2/8.1.3（选点 prompt 全字段化 + 两段式）是下一刀。最小 golden set（3-5 城固定输入 → mock LLM → 断言结构约束：同店不重复/每天≤4 景点/必去必含/时长合规）应在动 prompt 前进 CI，否则「变好」与「换一种错法」不可区分。P2 脚注「建议提前到 P1 末」不够，应为「8.1 动手前一天」。
2. **poi_stats 跨库拓扑写明**。实测：pois 在 PG（alembic 管）；trip_items 实际活在 SQLite（data/h5_state.db，PersistentTripItemService，JSON payload 文本；PG 侧 TripItem ORM 存在但被架空）。夜聚「trip_items GROUP BY」实际只能是**应用层解析 JSON 再聚合**（量小可行），结果写 PG poi_stats（FK 同库安全）。§9.2 应如实写「应用层聚合（双库读取）」，或另作架构决定把 trip_items 收编进 PG——二选一要明说，不能默认读者以为单库。
3. **xhs_mentions 会被全量重建抹掉**。aggregate_poi_stats 若整表覆盖写，链接解析攒的小红书计数一夜清零。重建必须列限定（只重算 wish/plan/visit/dislike 四列，保留 xhs_mentions），或把 xhs_mentions 挪独立存储。
4. **8.1.1 切流量前的冷数据问题**。库内 3887 条的 rating/rating_count 目前靠 refresh_pois 每日轮转回填，切换当天排序键大面积 NULL——「公式 NULL 容忍」≠「排序有意义」。P0 第 1 项应含一次性回填冲刺（v5 detail 全量补一轮，配额允许分批 2-3 天），且 top_pois_in_city 对无分 POI 给确定性兜底序；动手前先跑探针统计当前 rating 填充率再定冲刺规模（tmp_t/ 已有探针脚本可复用）。
5. **UGC 合规缺口**。poi_reviews 存用户文本，§11 只谈隐私不谈内容审核：境内产品 UGC 有审核义务。最低配：写入时机审钩子 + 「审核通过前仅作者可见」开关；入境专属标签（外卡/英文服务）无风险，评论正文才是监管面。另 device_id 匿名写入需限频防刷。

### 13.4 设计待补（不阻塞开工，P1 内解决）

6. **排序公式两处失真**。(a) 乘法零杀：§4 公式任何因子取 0 即全盘归零，「自产热度=0 退化纯质量分」只在各因子缺省=1 时成立——每个因子的 NULL/无信号缺省必须显式定义为 1（工作区已实现的简化版 rating×log2(1+count) 无此问题，按 §4 扩展时才会踩）。(b) 双源混算：rating（高德尺度）×rating_count（携程点评数）已在现行公式合流，两源分母分布不同，建议 per-source 归一或改加性 log 空间；「距离衰减」的锚点未定义（酒店？城心？多日行程取哪个）。§3.6-② affiliate 评分若进同一 rating 列，同理需归一。
7. **聚类分日 × 时间窗冲突**。6.1 硬分片后，晚窗 POI（8.2.1 sunset/evening）可能落在早晨片。聚类必须是软偏置（跨片挪站罚分进 solver），不是硬分配——§6.1 补一句口径。
8. **travel matrix 速度模型**。haversine×1.3÷80m/min 是全域步行速：10km 腿算 125min（打车实约 25min），AddCircuit 拿它当 cost 会系统性压扁行程。v0 至少分段速写（<2km 步行速、以上按 25-30km/h 地面交通），展示侧再由 _enrich_legs 纠偏。
9. **携程解析面扩大无监控**。A4/A5/A6/B3 五字段同押一页正则，页面改版=五字段同时静默 NULL。回源作业加字段级解析成功率日志/告警，一行成本保整个 A 组。
10. **poi_stats 删除语义未定义**。夜聚全量重建=「当前状态计数」：用户删 unwanted 项，POI 计数随之回落。这是合理语义但需与「历史热度累计」二选一并明示，写进 D2。
11. **三处「接线级」修复被排入 P1、且被低估**。8.2.2（传 matrix）、8.2.3（传 poi_hours）、外加 validate_plan 5 处补传——solver 侧全部已建好，合计接线级工作量；8.2.3 顺带修复规则 2 校验失效（13.2#5）。建议提进 P0：这是「一天横穿城三趟」「夜景排上午」两个最可见痛点的最小修复路径。

### 13.5 排期与验收微调

- P0 表加「状态」列（已落/部分/未动），以工作区为准同步，避免并行会话重复开发。
- §12 补基线指标先行：现在从存量计划统计「日均跨片腿数 / 饭点空窗数 / 占位假 POI 出现率」，P1 solver 改造才有 before/after 数字，否则验收全是主观描述。
- P0 工作量标尺：第 1 项按 WIP 实际规模（+719 行、10 文件、测试三件）已接近 M 而非 S；剩余项按原标尺可维持。

### 13.6 文档卫生

- 状态行改为「P0 实施中（审查后）」；§9.1 字段名以 0009 实际为准，去「提案」标注。
- §2 措辞修正：travel matrix 与 poi_hours 是「已建未接线」而非「没有」——这直接影响工作量直觉（接线 S vs 重造 M）。
- §3.5 B 档各家「个人可注册/约 1 天审过」是 2026-10-24 时点结论，动手注册当天逐家复核（平台政策变动快）。
- §1「没有一家靠 LLM 更聪明赢」是修辞性归纳（样本有幸存者偏差：赢在渠道/品牌者不在样本内）；作为资源分配论据成立，且 8.1 的做法本身并未否定 LLM，口径自洽——无需改，留此备查。

---

## 14. 第二轮外部对照审查（2026-10-24，GitHub 开源 × 商业主流 × 入境产品三路调研）

> 审查方式：三路并行调研（① GitHub 开源行程规划器与学术基准；② Google/Wanderlog/Sygic/携程/马蜂窝等商业产品引擎能力；③ 入境游客在华真实痛点与在售产品）× 工作区实测。目的（用户定调）：**优化面向外国游客的规划引擎能力**——本节按此重排权重。语言层（英文输出/翻译）**明确不在本节范围**（用户指示语言后做，此处不列缺口）。

### 14.1 架构论点外部验证（本设计押对了什么）

| # | 外部证据 | 对本设计的意义 |
| --- | --- | --- |
| 1 | 开源侧无可信工程范式共识：**LLM 选点/聚类 → 时间窗 VRP/TOPTW 排程 → 真实地图矩阵 → 校验闸门** 四件套，**没有任何单一开源项目全占**（route-compass 缺真实矩阵、I-Sheng 缺多日、CrewAI 系零求解器、Swiss planner 最接近） | 本设计目标位恰好是四件套全占（LLM 两段式 + CP-SAT + 高德矩阵回灌 + validate_plan）——差异化成立，照做 |
| 2 | TravelPlanner 基准（ICML'24 Spotlight）：GPT-4 全约束通过率 **0.6%**，最常挂的是**饭点吃饭/酒店城市一致**类常识约束；行业研究 ~90% 裸 LLM 行程含事实错误 | ① 选点层 grounding（8.1.1-8.1.3）论点坐实；② 8.2.4 餐厅插入与 hotel anchor 恰好打在最弱环；③ **8.1.5 评测集从 P2 提 P0 前置**（与 §13.3-1 合并升格为硬闸门：8.1 动手前进 CI） |
| 3 | 纯优化器商业先例全灭：Inspirock（Klarna 收购后关停）、Utrip（卖给 DMO 后沉寂）——但它们的引擎特性（营业时间感知/交通时间/防过载）活在 Wanderlog/Sygic 血统里 | 引擎质量是必要非充分；对外国人场景，**信任角标 + 预订深链**是商业侧另一半（14.3-G1、§3.6-②） |
| 4 | 携程 AI 行程助手 2025-09 已上**地图拖拽重排路线、实时同步**；Wanderlog 拖拽后自动重算时间是用户最高频表扬点 | §6.2 拖拽联动方向正确，但需补「拖后时间重算」（14.3-G4）——拖拽排序本仓已有、时间联动未接 |
| 5 | Voyaiger 等 2026 新入场的中国游 AI 规划器**被 GFW 墙**，西方规划器在华境内全灭；Amap Global 14 语言 + 离线地图 | 我们 H5 + 高德栈**境内可达是结构性优势**，但必须落地「行程离线可开」（14.3-G5）才兑现 |
| 6 | 开源侧矩阵缓存无人做（逐请求重算是常态）；OSRM 只有车行、Valhalla 是唯一时间感知开源引擎 | 8.2.2 两段式（v0 估 + `_enrich_legs` 高德实耗反灌）+ 缓存复用即是差异化，坚持；§13.4-8 分段速写修正照旧 |
| 7 | 多窗营业时间是 OR-Tools 社区公认的建模难题（单点多时间窗反复出现在 issues/StackOverflow）；opening_hours.js 是唯一严肃解析器，多数项目存字符串裸查 | **实测本仓同样受限**：PoiHours 单窗 `opens/closes`（solver.py:85-88 单次相交），**国内场馆午休闭馆（12:00-13:30）无法表达**——14.3-G3 |

### 14.2 入境痛点 → 引擎能力映射（r/ChinaTravel 等 2024-2026 高频排序）

| 痛感排名 | 痛点 | 本设计现状 | 判定 |
| --- | --- | --- | --- |
| 1 | 支付（Alipay/WeChat 国际绑卡） | 点评标签已排（外卡支付可用） | ✅ 已覆盖（行前内容层面） |
| 2 | 地图/GFW | 高德栈 + PWA | ✅ 结构性优势，差离线兜底（G5） |
| 3 | **预约制景点**（故宫提前 7 天 8:00 微信小程序秒光；国博/陕历博同类；外国手机号常失败→Trip.com/Klook 代抢是标准解法） | **零覆盖**——只有营业时间约束与 B3 门票价 | ❌ **G1，本节最高优先新增** |
| 4 | 火车票（12306 外照可用但 14 天窗+难用→Trip.com 代理是主流） | 12306 已接（查询）；预订深链未排 | ⚠️ §3.6-② affiliate 落地时顺带，不单列 |
| 5 | **240h 免签过境**（57 国/65 口岸/24 省、须第三国联程票；游客普遍反映"官方答案互相矛盾"） | 仅「免签适用」点评标签 | ❌ **G2，独家信任功能**（14.3） |
| 6 | 语言 | 输入双语已有；输出层全中文 | ⏸ 用户明确后做，本节不列 |
| 7 | 酒店拒外宾（2024-05 已令整改，Trip.com 有"接待外宾"角标） | 住宿未入规划域 | ⏸ 住宿入域时再加标志位，记挂账 |

### 14.3 新增引擎缺口清单（按入境痛感排序；G=Gap）

| # | 项 | 内容 | 证据/来源 | 重要度 | 开发量 | 落点 |
| --- | --- | --- | --- | --- | --- | --- |
| G1 | **预约制门票约束** | pois 增 `reservation_required BOOL` + `reservation_advance_days INT` + `booking_url`（0010 增列，0009 已落地不再改）；solver 软约束：需预约 POI 卡片亮「现在就订·提前 N 天·放票 08:00」；booking_url 缺省落 §3.6-② affiliate 转链（Klook/Trip.com 代抢即外国人标准解法） | 故宫/国博/陕历博微信小程序秒光是入境第一实操痛；Klook/GetYourGuide/Viator 靠代抢英文化赚这个钱 | **高** | S-M | 随 0010；名单 v0 人工录入 top 预约制场馆（数十家）+ 携程 sight 页「需预约」标识回源补量 |
| G2 | **240h 免签行程可行性校验** | 确定性规则引擎（零 LLM）：入境/出境口岸对 + 允许省份范围 × 行程城市集合 + 停留时钟 ≤240h + 第三国联程票提醒 → 行程页绿/红横幅 +「以边检为准」免责 | 游客"答案互相矛盾"是普遍吐槽；**无一家规划器有权威校验**（Voyaiger 宣称有 visa 逻辑但被墙）；政策快变→快照日期 + 数据表可热更 | **高** | S | `services/itinerary/visa_check.py`；政策快照表（生效日期/口岸/省份 JSON） |
| G3 | **多窗营业时间** | PoiHours 增 `windows`（多段开窗）；solver 用可选区间逐窗建模（OR-Tools optional intervals，社区成熟解法）；回源解析「12:00-13:30 午休」分段 | solver.py:85-88 单窗实锤；OR-Tools 多窗是公认难题但有标准答案；**国内场馆午休是常态不是边角** | 中-高 | M | P1 solver 改造同批（与 8.2.1-8.2.3 同批动刀） |
| G4 | **拖拽后时间自动重算** | trip center 拖拽排序已有（⠿ 把手）；补：拖后触发 validate_plan + `_enrich_legs` 增量重算当日时间线，改完即存 | Wanderlog 最高频表扬点；携程 2025-09 已上同款；无重算的拖拽=只是改顺序不是改计划 | 中 | S-M | H5 + 端点复用，§6.2 拖拽联动的引擎半边 |
| G5 | **行程离线可开** | PWA 已有（HTTPS/8443）；补：sw 缓存当前会话行程 JSON，断网/无 VPN 打开不白屏；ICS/GPX 导出已有兜底 | 西方 AI 规划器在华全灭反衬价值；外国人漫游常无 VPN；手机信号差的景区（山里/地铁）实用 | 中 | S | H5 sw 策略一项（记得 VERSION+1） |
| G6 | 交通腿结构化 payload | legs 数据已有；补结构化字段（线路名/站名/出口号/打车地址串）——**只做结构，语言渲染后置**（用户语言层统一做） | 外国人换乘踩坑主因是「哪条线哪个口」；数据结构先行不依赖语言决定 | 低 | S | P2；`_enrich_legs` 返回体扩字段 |

**明确不做（本轮）**：语言输出层（用户自做，2026-10-24 指示）；酒店「接待外宾」标志（住宿未入域，挂账）；人工专家转接（马蜂窝指路人模式，不适用）。

### 14.4 对排期的影响（叠加在 §13 修正之上）

1. **P0 修正**：8.1.5 评测集升格为「8.1 动手前一天」硬闸门（§13.3-1 结论获 TravelPlanner 0.6% 外部证据加持，从"建议"改"必须"）。
2. **P1 新增**：G1（预约制约束）+ G2（免签校验）作为**入境信任双件套**插 P1 前段——两个都是 S 级，是外国人场景下"竞品没有/我们独有"密度最高的两项；G3/G4 并入 P1 solver/地图批。
3. **P2**：G5 可提前（S 级一行 sw 策略）；G6 随语言层一起做更顺。
4. **§3.6-② 触发器补强**：Klook/Trip.com affiliate 注册后，第一件事从「实测评分字段」扩为「实测评分字段 + **预约制门票代抢商品覆盖度**（故宫/国博等 top 场景有没有货）」——affiliate 的真正价值一半在 G1 的 booking_url 兜底。

### 14.5 工作区漂移快照（§13 之后的增量，2026-10-24 下午）

- `top_pois_in_city` **已接线**：plan.py:2159（库优先 8.1.1 半落——库存≥10 跳过高德的分支待确认）；
- 8.2.1 best_visit 开窗**已完成**（PROGRESS #13，solver/time_slot/rules 48 测试过）；
- poi_hours 仍全链 `[]`（plan.py 896/2790/3078/3279/3341/3647/3731 七处 validate/solve 调用）、travel matrix 仍在并行开发（PROGRESS #14）——§13.4-11「接线项提 P0」维持。
- 本节不重复 §13 的 P0 状态表，以 PROGRESS 活文档为准。

### 14.6 杂项风险注记

- Google Play 已有同名 "ChinaTrip" AI 规划器 App（2025-12 更新）——出海命名/商店 SEO 需差异化，记入远期品牌清单。
- Amap Global（14 语言、2025-07）与我们是同源底库的官方国际化版：其存在证明高德数据撑得起外国人场景，也意味着**纯导航层不要重复造**——我们的差异化在规划器+校验（G1/G2）不在地图。

### 14.7 主要来源（2026-10-24 查证）

- 开源/学术：[TravelPlanner 基准 (OSU-NLP, ICML'24)](https://github.com/OSU-NLP-Group/TravelPlanner)、[route-compass TOPTW](https://github.com/DENGYUFAN0/route-compass)、[I-Sheng GPTs+OR-Tools+学习时长](https://github.com/I-Sheng/Travel-Itinerary-Planning-System-Using-GPTs-as-the-Core)、[Swiss-AI-Travel-Planner](https://github.com/mirkokeller/Swiss-AI-Travel-Planner)、[OR-Tools 多窗讨论](https://github.com/google/or-tools/discussions/3385)、[opening_hours.js](https://github.com/opening-hours/opening_hours.js)、[PyVRP](https://github.com/PyVRP/PyVRP)
- 商业：[Google AI Mode Canvas 行程](https://blog.google/products-and-platforms/products/search/agentic-plans-booking-travel-canvas-ai-mode)、[Wanderlog](https://wanderlog.com)、[Sygic Travel](https://www.sygic.com/travel)、[Klarna 收购 Inspirock](https://www.klarna.com/international/press/klarna-acquires-inspirock-bringing-smooth-travel-planning-to-its-90m-global-consumers)、[携程 AI 行程助手 (2025-09)](http://www.caacnews.com.cn/1/7/202509/t20250916_1389990.html)、[Trip.com Trip.Planner](https://www.trip.com/blog/trip-planner-tool)、[AI 行程 90% 含错研究](https://www.thrillist.com/news/nation/ai-travel-itineraries-wrong-incorrect-study)
- 入境：[240h 免签过境官方公告 (2024-12)](https://english.www.gov.cn/news/202412/17/content_WS6760e5eac6d0868f4e8ee0b8.html)、[故宫微信小程序抢票攻略](https://hellochinatrip.com/how-to-book-forbidden-city-tickets-on-wechat-miniprogram)、[12306 外照购票 vs Trip.com](https://dolphinunion.com/post/china-train-ticket-booking-for-foreigners-12306-vs-trip-com)、[酒店须接待外宾令 (2024-05)](https://www.pekingnology.com/p/china-now-asking-all-hotels-to-accept)、[Voyaiger 中国游 AI 评测（被墙）](https://voyaige.to/blog/best-ai-travel-planner-for-china-2026)、[Amap Global 14 语言](https://apps.apple.com/us/app/amap-global/id461703208)、r/ChinaTravel·r/travelchina 2024-2026 高频帖
