# 规划引擎升级与底库富化设计 — ChinaTrip

日期：2026-10-24
基准：本仓库代码现状（feat/v24-trip-center, c1a7dfd + 未提交 WIP）× 11 家竞品调研（Wanderlog / Trip Planner AI / Layla / TripAdvisor / 携程问道 / 马蜂窝 AI / 小红书点点 / Instagram / TREK / AdventureLog / LetsFG / 圆周旅迹）+ 本仓代码核查（哪些数据已到手在丢）
状态：**待用户审查**（未开工；迁移号、字段名、作业名均为提案）

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
| v1.3 | 2026-10-24 §3.6 增 VPN 可达性说明（用户补充：开发机有 VPN）——可达 ≠ 权限：Google/Yelp/Reddit 逐家重判仍出局（ToS 存储禁令/零中国数据/商用条款）；MVP 阶段外国源抓取可行（作业跑开发机，OSM 已 VPN 依赖）；规模化迁阿里云后 ⛴ 标注源需复核 |
| v1.2 | 2026-10-24 新增 §3.6 入境游客评论源（用户定调：主要客户=外国人，优先级反转）——TripAdvisor 从 L4 兜底升为「主体落地即申请的第一批」（唯一结构化外国人评论 API）；Klook/Trip.com/GetYourGuide affiliate 评分字段实测路径；自产评论=外国人视角独家资产；review_tags 增入境专属标签（外卡支付/英文服务/护照预订/免签）；§3.5 C 档 TA 行与 §10 触发器清单同步；审查版格式 docx→PDF（横版 A4，表格优化） |
| v1.1 | 2026-10-24 §3.5 扩为数据源连通性五档总矩阵（A 已在用 / B 申请即连【FSQ·携程开放平台·淘宝联盟飞猪·美团推客层·Klook affiliate·高德企业认证】/ C 需企业+流量【TripAdvisor Content API 等】/ D 基本连不上 / E 无通道）+ "现在就能办的三件事"行动项（逐家申请通道查证） |
| v1.0 | 2026-10-24 初稿（待审查）：三层问题定位、A-D 四组字段清单（含外部评论源判定）、四层互动闭环、小红书四路径、地理规划器三项、竞品吸收清单、LLM/排期升级、迁移 0009 与作业设计、P0-P2 计划 |
