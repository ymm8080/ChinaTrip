# 规划引擎升级 0009 — 开发进度交接（活文档）

> 用途：任何新会话读本文件即可无损接续开发。每完成一项立即更新。
> 计划：[planning_engine_upgrade_2026-10-24.md](planning_engine_upgrade_2026-10-24.md)（v1.3 已审查通过，用户指示"keep developing till complete + fan out subagents"）
> 分支：feat/v24-trip-center ｜ 工作区另有他人未提交 WIP（retime/weather/osm/tag_quality）——**不要动那些文件的既有改动，不要自行提交**



## 批次完成总账（2026-10-25 · 全量 1051 测试绿 + ruff 干净）

| 项 | 状态 | 产物 |
| --- | --- | --- |
| 迁移 0009（pois+14/restaurants+12/poi_reviews/poi_stats） | ✅ | alembic 0009 + models.py（poi_reviews 正文字段 DB=text/ORM=body） |
| 迁移 0010（G1 预约制三列） | ✅ | alembic 0010 |
| upsert 扩签名 + top_pois_in_city | ✅ | poi_details.py（确定性排序公式；G1 三键透传） |
| refresh_pois 全字段写回 + ctrip detail_fields_for | ✅ | 真实页验证：210min/4.7分/16000评/4标签/¥24 全命中 |
| amap _extras（photos/tel/business_area） | ✅ | amap_client.py |
| 8.1.1 候选库优先 | ✅ | 库≥10 跳过 amap；占位路径保留 |
| 8.1.2/8.1.3 选点全字段+reason | ✅ | listing 全信号 + duration 兜底 + 理由汇假设 |
| 8.2.1 best_visit→solver 窗 | ✅ | solver._BEST_VISIT_WINDOWS（子代理完成） |
| 8.2.2 travel matrix + 两段式重解 | ✅ | 高德实测优先（用户拍板）+ leg_cache 回放 _replay_measured_legs |
| 8.2.3 营业时间进 solve | ✅ | _plan_poi_hours（含 G3 多段） |
| 8.2.4 餐厅 v0 插入 | ✅ | auto_restaurants 开关；配额静默 |
| 8.1.5 评测集 P0 闸门 | ✅ | test_engine_constraints.py + 每日≤4 裁剪守卫 |
| G1 预约制 | ✅ | 名单 v0（reservation_seeds.py 17 馆）+ hint/chip/假设 |
| G2 免签校验 | ✅ | visa_check.py + /api/v1/visa/240h + H5 红绿横幅（sw v22） |
| G3 多窗营业时间 | ✅ | PoiHours.windows + 条件开窗 ExactlyOne + 午休补集解析 |
| G4 拖拽时间重算 | ✅ | move/retime 已有校验+时链；补实测腿回放 |
| G5 离线可开 | ✅ | 既有 SW 已覆盖（API NetworkFirst+缓存回落；pwa 测试过） |
| G6 腿结构化 | ✅（结构层） | legs payload 结构已有；语言渲染按用户指示后置 |
| 互动端点 | ✅ | /feedback/vote·visit·review·poi + /links/batch + poi_feedback store |
| aggregate_poi_stats 夜作业 | ✅ | jobs + ops/poi_stats_nightly.cmd（03:40） |
| backfill_indoor_rain | ✅ | heuristic 层（类别规则）+ 测试；LLM 层接口预留 |
| review_summary 蒸馏 | ✅ | 五关校验 + mock 跳过 + 测试 |
| geo 聚类分日 | ✅ | geo.py（最远点种子确定性聚类）+ listing 片区 chip + prompt 规则 |
| 计划级查全率 | ✅ | coverage.premium_coverage_gaps → 假设区「白名单未排」 |
| 天气感知建议 | ✅ | coverage.rain_swap_advice + H5 wxRainBar 雨天横幅（index.html `_day` 挂载 + VisitItem.rain_ok 透传，回归 test_plan_agent.py::test_rain_ok_passthrough_for_rain_banner，2026-10-25 复核 6 passed） |


## 2026-10-25 第十四批：booking 按钮 geo 分流（用户拍板：境外→Trip.com / 国内→美团）

- ✅ `services/geo_split.py`：XFF 首段优先 → APNIC CN 委派段表（`data/cn_ip_ranges.txt` 8,797 段，mtime 热更、零第三方库）→ 境内=meituan/境外=tripcom；私网/回环/未知/段表缺失→境外侧默认（主要客户=外国人，安全侧）
- ✅ order-intent 接线（服务端选好成品 URL，前端零判断；显式 booking_url 优先；返回 geo_channel/client_ip）；config 增 domestic 模板
- ✅ 测试 3 用例（CN 段 1.0.1.5→美团、8.8.8.8→Trip.com、XFF 优先+显式 URL 优先）；全量 1148 绿
- 📁 段表重生成：跑 APNIC delegated-apnic-extended-latest 拉取脚本即可（热更自动生效）

## 2026-10-25 第十三批：booking 设计 PDF + 归档

- ✅ `DESIGN/booking_design_2026-10-25.pdf`（6 页横版 A4，Edge 渲染，已在 PDF 面板打开）
- ✅ ARCHIVE/booking_design_2026-10-25.pdf 副本归档（25 件）；原 Booking for client.md 未入 git（untracked）无法恢复归档，其精华已在定稿 §8
- 📁 当前 BOOKING 域文件：定稿 md + pdf（工作区）+ pdf（ARCHIVE）——单档三副本

## 2026-10-25 第十二批：单档定稿（用户拍板 we need one only）

- ✅ `Booking for client.md` 精华（能力速览/诚实声明/质量状态）并入 booking_design_2026-10-25.md §8 → **简报文件已删除**
- ✅ 全部引用修净（设计档头部/§7/主文档 14.7/INDEX）；**巡检层注意：客户向更新一律写 booking_design §8，勿重建简报文件**
- ✅ 全量 1105 绿

## 2026-10-25 第十一批：booking 设计独立成册（用户指示：先查重再建）

- ✅ 查重发现既有 `Booking for client.md`（巡检层建的客户简报）——**不重复建设**：新档 `booking_design_2026-10-25.md` 定位=技术设计定稿，简报=客户层，互挂链接+数字以定稿为准
- ✅ 吸收简报更新事实（65 口岸全表/1400 条补量/评测集扩样 10→15 抓真回归）；主文档 §14.7 缩为指针（14.5 标题修复回补）
- ✅ INDEX 挂链；全档与代码同步（1099 绿）

## 2026-10-25 第十批：并发冲突处置 + 巡检层产出盘点

- ⚠️ 事故：LLM 巡检层写 plan.py（多语言 _with_lang 等）与主会话编辑相撞，一度 69 红（畸形缩进块 + sep='\n' 转义错误）；主会话修复 3 处后**全量 1099 passed**（含巡检层新工作并入的 18 测）
- ✅ 制度化：主会话对巡检层在写文件（mtime 几分钟内变动）避让；巡检层已有自锁语义（上轮未完本轮让位）
- 📋 巡检层产出盘点：①plan.py 多语言指令层 _with_lang（_LANG_DIRECTIVES，SITES/编辑提示词接入）②app/jobs/enrich_{ctrip,amap}_detail.py / enrich_review_summary.py / enrich_heuristics.py（携程确定性填列管线）③名单三轮官方核对（恭王府 10 天/莫高窟 30 天等）④衍生 CT-first 富化巡检自动化（每 2 分钟，文件锁互斥）
- ✅ 双自动化职责确认不重叠：①=代码续跑/修复，②=数据富化批处理（禁改代码文件）

## 2026-10-25 第九批·续：FlyAI 入 §3.5 候选 + 观察项双通道落档

- ✅ 设计文档 §3.5：飞猪 FlyAI 行（B/C 待查资质，L2/L3 库存腿候选，角色=后端库存 API）；§3.6 新增 ⓪ 观察触发行（Mastercard×Trip.com + 支付宝 AI付 双通道季度扫）

## 2026-10-25 第九批：MCP/支付宝/Trip.com 事实核查（用户两问）

**Q1 MCP+支付宝订票行得通吗？——拆三件，两件通一件不通**
- ✅ MCP=工具调用协议（非业务），自用无门槛；我方可把自有 API 包 MCP server 蹭 Cursor/Claude 生态（远期）
- ✅ 支付宝支付 MCP Server（2025-04 上线，魔搭首发）+「AI付」（2025-09，瑞幸首单）——**语义=收单**（商户收用户的钱）：适用=未来订阅/自营服务收款（需企业主体+商户号）；**不适用=代客向第三方商户付票钱**（代付=资金过手=二清，支付宝 MCP 不提供该形态）
- ✅ 票务库存侧真通道（新发现）：**飞猪 FlyAI**（flyai.open.fliggy.com，机/酒/门票/度假全品类 AI 开放，OpenClaw 协议）；携程商旅 MCP（2026-04，企业差旅向）；高德 MCP（行程/地图，非交易）——飞猪 FlyAI 入 L2/L3 库存腿候选（B/C 档，资质待查）
- ❌ 不通的：MCP+支付宝组合替代不了 ACP 形态（agent 用用户钱包付第三方）——国内等支付宝生态内智能体交易开放，或走 Mastercard 轨（见下）

**Q2 Trip.com 走 ACP 吗？能帮老外抢票吗？**
- Trip.com **不走红 ACP（Stripe/OpenAI 轨）**，走 **Mastercard 轨**：2026-09 Mastercard×Trip.com 官宣 agentic commerce（TripGenie+Mastercard 技术，UCP/Google-Mastercard 阵营）——**中国系 OTA 首次公开进场 agentic commerce，一个月前刚发生，重评触发器第一声已响**
- 能帮老外：**机/酒=真库存即时确认（完全行）**；**景点票=护照可订 SKU（故宫官方价 60/40）+含票导览，但代抢受官方配额约束**（放票同为 20:00/提前7天，Reddit 实测有 Being Confirmed 停留期；售罄兜底=当天护照窗口购票）——定位=外国人最顺通道（护照+外卡+英文），非保证抢到
- 行动：观察项从"ACP/UCP"扩为「Mastercard/Trip.com agentic + 飞猪 FlyAI」双通道；L3 非 ACP 闭环主案不变

## 2026-10-25 第八批：非 ACP 主案定调（用户拍板：ACP 不可用就走非 ACP 解）

- ✅ 口径改写：L3 从「等待 ACP 的降级形态」升为**标准下单闭环**（预填下单→渠道支付→粘贴回填→联盟对账，三段即完整产品形态）；ACP/UCP 降为观察项（不依赖，接入换 channel 不动架构）
- ✅ H5 **行前抢票日历**（sw v26）：行程卡顶部金黄卡——每馆一行「📅 开抢日 放票时刻 开抢 · 馆名（提前 N 天，游 X 日）」+ 直达按钮；数据来自 /booking-auto/tasks（plan visits + start_date）
- ✅ resolve_tier/OrderIntent 文档同步；测试 11 绿 → 全量回归

## 2026-10-25 第七批：L3 伪闭环（ACP 就绪前的等价体验）

- ✅ order-intent 发起即落 `action_handoffs`（action_type=site_ticket，channel 按域名判 ctrip/klook/meituan/other，refund_summary 铁律 23 C 级口径）——用户渠道付款后回「订单」页粘贴回填 → apply_paste_return → user_confirmed → 联盟同步 verified：**发起-支付-回传三段全通，ACP 要给的闭环今天就有 90%**
- ✅ H5 toast 提示回填路径（sw v25）；测试断言 handoff_id + opened 状态（35 绿含 backfill 套件）
- 📋 ACP 行业就绪：不可由我们推动（Stripe 轨道×中国持牌支付双障碍）；行动=①本伪闭环（已做）②季度盯 ACP/UCP 公告+**支付宝/微信智能体支付**（国内真正的 ACP 时刻大概率在此）+OTA 开放平台 agent API ③社区提 travel use case（低杠杆可选）

## 2026-10-25 第六批：L2 provider 国内优先（用户二次纠偏）

- ✅ 「中国票务不需要 Klook/Trip.com」半对：国内用户不需要，但主要客户=外国人——Trip.com 本就是携程国际版（同一国内库存），Klook=外国人顺手入口。**按用途分家**：L2 库存主力=携程联盟/同程/美团（config 增三键，任一配好 L2 即活）；Klook/Trip.com 降为 L1/L3 外国人下单面（直达/代抢），不作库存主源
- ✅ resolve_tier 五键任一判定；测试桩同步（国内键点亮 L2 用例）
- ✅ 全量 1080 passed + ruff 干净

## 附：ACP 行业就绪释义（答复用户提问，落档）

ACP（Agent Commerce Protocol）= Stripe×OpenAI 2025-09 发布的开源支付协议（Apache-2.0），专为 AI agent 代客完成交易设计：商户保持 record-of-record、支付走用户自己的钱包授权（agent 不碰资金）。UCP = Google 同类标准。「行业就绪」= 主要商家/OTA（携程/美团/Klook…）真正接入 ACP/UCP 或开放合规下单 API——2026-10 观察：中国 OTA 均未接入。就绪前 L3 恒为 manual_confirm（预填链接+用户支付）；就绪后换 channel 实现不动架构（供应链适配层扩展位，v1.9.6 预留）。重评触发器：任一主要 OTA 接入即评估升级。

## 2026-10-25 第五批：L2 语义纠偏（用户挑战「Klook/Trip.com 不管境内票务余量」）

- ✅ 纠偏成立，分两层事实：①预约制馆（故宫/国博免费票）真实配额在官方微信小程序，**任何联盟 API 都查不到**（Klook/Trip.com 卖的是代抢服务商品非官方库存）→ L2 对这批馆诚实返回新枚举 `official_quota`（不查 provider 不编造，提示走 L1 放票提醒/代抢直达）；②商业付费 SKU（门票/演出/一日游）才有渠道库存可查——L2 语义从「现场余量」改为**「渠道可订性」**
- ✅ check_availability 按场馆类型分流（名单命中→official_quota 短路；否则 provider 可订性）；测试改双分支断言，11 绿
- 🔭 远期数据飞轮（记档）：poi_reviews 增「抢到/没抢到」标签 → official_quota 场馆的经验售罄规律（自产独家，渠道拿不到）

## 2026-10-25 第四批（主会话收尾：双语双部署 + 官方事实定案）

- ✅ 双语双部署架构定稿：[language_dual_system_design_2026-10-25.md](language_dual_system_design_2026-10-25.md) + 同名 PDF（拓扑图纵版防裁切；**一仓/一 schema/两部署/分库/参考表 _en 列**；方案 A 两仓/B 镜像表/C 同表加列对比后定 C+分库；P1 _en 列+翻译 backfill → P2 海外部署+参考同步 → P3 译文质检）
- ✅ 预约名单三轮官方直核定案：恭王府 7→**10 天**（文旅部 2019-12 全网售票公告：提前 10 天预售、最早参观十日前 20:00 可订）、莫高窟 15→**30 天**（敦煌市政府 2025 公告/新华网：门票可提前 30 天在莫高窟参观预约网预订）；其余 9 项与二轮一致；核对文档追加「三轮官方直核补正」节
- ✅ 免签快照三轮补正：city_scope 补云南 9 市州；57 国时间线注记（2025-06-12 印尼→55、2026-08-20 越南/吉尔吉斯斯坦→57，NIA 现行页）；+3 官方事实钉测试（贵州/吉林/65 口岸/广东 5 口岸/云南范围）
- ✅ 全量回归 **1069 passed** + ruff 干净（含并发会话 timing_engine 等新测试）
- ℹ️ 事实类数据约定（用户 2026-10-25 指示）：名单/口岸/政策口径一律 WebSearch/WebFetch 官方源直核回写，查不到的标「未能核实」，禁止凭记忆编造；LLM 生成仅限简介/点评摘要等描述性内容

## 2026-10-25 第四批：预约自动化三档栈（L1/L2/L3 可选）

- ✅ `services/booking_auto.py`：BookingTier 三档 + **降级链**（请求档不可用自动回落 L3→L2→L1 并注明，L1 零依赖恒可用）；L1 放票任务（visit_date-advance_days 开抢日 + release 时刻，名单 17 馆含结构化放票时间）；L2 AvailabilityProvider 协议+注册表（联盟 key 未配=诚实 unknown，签约即插 Klook/Trip.com adapter）；L3 OrderIntent（manual_confirm 形态：预填 authorization_url，requires_user_confirmation 恒 True——铁律 22；ACP 扩展位=OrderChannel 协议）
- ✅ `api/booking_auto.py` 五端点：GET /tiers（档位目录+降级注记，选择器数据源）、POST /tasks（L1 行前抢票日历）、POST /check（L2 库存）、POST /order-intent（L3）、POST /select + GET /selected（**客户自选档位**，设备级记忆）
- ✅ config：klook_api_key/tripcom_api_key/booking_search_template（联盟参数 alliance_id/sid 双非空才附加——转链同款纪律）
- ✅ reservation_seeds 升结构化 {days, release, note}（保留监控层三轮官方核对数据：恭王府 10 天/莫高窟 30 天/熊猫基地 14 天等）
- ✅ H5：预约行「抢票直达 →」按钮（order-intent 开预填页，sw v24）
- ✅ 测试 test_booking_auto.py 12 用例（降级链/日期数学/联盟参数条件/unknown 诚实缺省/支付永归用户/API 全链）；全量 1080 passed + ruff 干净
- 注：监控层并行建了 app/jobs/enrich_{amap,ctrip}_detail.py / enrich_review_summary.py（lint 已收编）

## 2026-10-25 第九批（主会话）：EN 存储缺口补齐（P1.5）+ 供应商真实性评估

- ✅ 用户指出 EN 存储缺口 → 迁移 **0013**（双库到 head）：pois.review_summary_en + restaurants.review_tags_en/cuisine_en/signature_dishes_en；ORM 同步；FIELD_SPECS 扩展；city 名决策不加列（前端字典，§6）
- ✅ 新字段真跑回填：pois 摘要 **1,134+688 字段**、餐厅菜系/标签 **647 字段**（两轮 mop-up 后 errors 归零；首次双批并发 16 路撞免费池限流——教训：大批串行跑）
- ✅ 同步链白名单扩展（review_summary(_en)/cuisine(_en)/signature_dishes(_en)）+ INTL 库重同步 **16,577 行 0 错误**，review_summary_en 播种链实测（111 行经导出→导入自动到达海外库）
- ✅ 代修并行会话 enrich_baidu/tencent_map 4 处 E501（mtime 停笔 20min+ 判定安全）
- ✅ 全量回归 **1,148 passed** + ruff 干净
- 📌 供应商真实性评估（用户问询）：POI 闭店/更名勤度 高德>腾讯≈百度，维持高德主源；三家景点深度都弱→携程回源+官方校订架构不变；第二源交叉验证（百度）暂不做

## 2026-10-25 第八批（主会话）：P2 同步链本地全链路实测 ✅（无服务器完成功能闭环）

> 用户指示：先完成全部功能任务再谈部署。方法：同一 WSL PG 起第二库
> `chinatrip_intl` 模拟海外 PG-INTL，同步链全环节真跑。

- ✅ T1 本地 INTL 库：`CREATE DATABASE chinatrip_intl` + alembic 到 head（w12_0012，含并发会话新增 payments 迁移）
- ✅ T2 真实导入 **16,922 行（3890+13032）0 错误**；行数/内容/坐标/译文抽查全对（同 source_poi_id 双行场景厘清：amap 行译文在、chinatravel 行坐标在）
- 🐛 实测抓到 2 个真 bug 并修复：① 导入 insert 缺 id（ORM 主键无默认生成器，CN 侧总是显式赋 id 掩盖了它）→ `setdefault("id", uuid4())`；② restaurants 白名单误含 review_tags_en（设计 §5.2 只给 pois）→ 移除。**dry-run 在 CN 库测不出这两个——本地双库实测正是为此**
- ✅ T3 变异测试三语义全过：本地改业务列 → 再导入被 CN 覆盖（name_zh 回滚）；本地改 _en → 保留（LOCAL CURATED 存活）；重导入幂等（update 16922 / insert 0）
- ✅ 墓碑传播实测：CN 行置 inactive → 重导出重导入 → INTL 行变 inactive；恢复流程同链路验证
- ✅ T4 lang 指令达 LLM：RecordingLLM 捕获 system 消息，lang=en 必含 "LANGUAGE:"、zh 路径必不含（2 断言）
- ✅ T5 H5 i18n 在位测试 3 个（i18n.js API 齐全/挂载+回退在位/SHELL 入壳）
- ✅ T6 全量回归 **1126 passed** + ruff 干净（+27：同步 7 + lang 3 + H5 3 + 并发会话增量）
- 🏁 **功能任务全部完成**。P2 剩余纯部署动作（服务器/域名/代理/对象存储），到位后照 `.env.example.intl` + `import_reference` 即开即用

## 2026-10-25 第七批（主会话）：双语 P2 可开发项全落地

- ✅ 参考同步核心 `app/services/reference_sync.py`（纯逻辑）：显式列白名单导出/NDJSON+SHA256 manifest/导入决策（CN 业务列覆盖、**本地 _en 非空保留、为空播种**、status 墓碑传播）——7 单测绿
- ✅ 导出作业 `export_reference.py`：真实导出 **3890 pois + 13032 restaurants**（含 poi_hours 嵌套、双坐标系 lon/lat）→ `data/reference_export/2026-10-25_094014/`
- ✅ 导入作业 `import_reference.py`：同批 dry-run **16922 行决策 0 错误**（自然键命中=update 路径全走通）；poi_hours 按本地 poi_id 先清后插重链
- ✅ INTL 部署模板 `.env.example.intl`（region=INTL / 高德经 CN 代理注释 / 同步消费说明）
- ✅ 会话级 `lang` 参数：PlanSession.lang + agent.start(lang=) + 系统提示词 EN 指令注入（sites/v0/edit 三路；无 session 作用域的两点改显式 lang 参数直传）+ 2 单测；CN 默认零行为变化（zh 直通断言过）
- ✅ H5 卡片微文案 i18n 扩面 8 处（钉住/分钟/距下一站/步行/实测与估算/抢票直达/营业时间待确认）
- ⚠️ 过程事故记录：lang 注入首版与 2 分钟巡检自动化**并发写 plan.py** 撞车写伤（f-string 真换行+嵌套 return），已全部修复并全量回归；教训已在本批自动化 prompt 里加"上轮未完本轮秒退"
- ✅ 全量回归 **1099 passed** + ruff 干净（+8：同步 7 + lang 持久化 1）
- 📌 P2 剩余（依赖用户部署决策）：海外服务器/域名、高德 CN 代理隧道搭设、海外 PG 建 head、对象存储同步通道；代码侧 P2 全部就绪

## 2026-10-25 第六批（主会话）：双语 P1 落地 + 监控提到 2 分钟

- ✅ 迁移 **0011**（w12_0011 head）：pois +intro_en/address_en/review_tags_en、restaurants +intro_en/address_en；ORM 模型同步；只填空语义入注释
- ✅ _en 透传链：top_pois_in_city 投影 + _collect_candidates 白名单补键 + VisitItem(name_en/address_en/intro_en) 并出（回归 test_en_fields_passthrough_for_bilingual_cards：有值并出/无值回退双路径）
- ✅ 翻译作业 `app/jobs/backfill_en_columns.py`（译不写：只翻库内已有中文，绝不生成事实；五关校验 Latin 主体/长度/非复读/meta；tags JSONB 逐条译同型回写；+5 单测）。真跑：pois 20 行验质（慈宁宫→Palace of Compassion and Tranquility 等）→ 400 行批次 **396 行/841 字段**、47 字段级拒绝留空自动重试；restaurants 600 行批次后台
- ✅ H5 i18n 骨架：`static/i18n.js`（字典 t()/pick(_en??中文)/localStorage locale）+ nav 七 tab 与主按钮 data-i18n + 🌐 语言开关 + 卡片名称/地址可见文本回退（data-* 仍喂中文）；sw.js v26（i18n.js 入壳）
- ✅ ops：poi_en_nightly.cmd（pois+restaurants 各 500/夜 04:10）+ register_schtasks 加行 + 本机注册成功
- ✅ 监控改频（用户指示 auto restart every 2 minutes）：LLM 巡检自动化 20min→**2min**（加"上轮未完本轮秒退"心跳防重叠）+ TimingEngine schtasks 2 分钟心跳——双层重启机制就位
- ✅ 全量回归 **1091 passed** + ruff 干净

## 2026-10-25 第五批（主会话）：回填存量清零 ✅ 收官

- ✅ review_summary 蒸馏收尾：再跑 45/45（eligible 归零；此前 30+45 共 75 行全量蒸馏完毕）
- ✅ indoor/rain_ok 存量清零：heuristic 补扫再填 183（扫到 449 行窗口外行）+ LLM 层批量 175 填入/0 错/0 拒；**active 行覆盖 100%**（终验 `active empty indoor/rain = 0`）
- ℹ️ 剩余 74 行空值全部为 `status='inactive'` 退役 POI（闭馆/去重行）——按设计不进选点候选，留空正确非欠账；并发会话同跑回填时"只填空"避让生效（8 行 skipped_existing 实证）
- ✅ 终验：全量 **1080 passed** + ruff 干净（并行会话又新增若干测试）
- 🏁 至此《规划引擎升级》清单全部完成或按设计豁免；30 分钟续跑自动化进入"仅确认"模式（全绿即报 ALL TASKS COMPLETE 不改码）

## 2026-10-25 第三批：自研定时引擎 + 双层监控

- ✅ 自研定时引擎 `ops/timing_engine.py`（纯 stdlib：到期计算/失败退避×2ⁿ封顶30min/水位原子持久化 data/timing_state.json/--once/--loop/--run-now）+ `ops/timing_probe.py`（PROGRESS 待办探测 → data/dev_pending.flag）+ `ops/timing_engine.cmd` 宿主
- ✅ schtasks 注册：ChinaTrip\TimingEngine 每 2 分钟拉起 --once（已验证：状态落盘 last_ok=true）
- ✅ LLM 续跑层：ZCode 自动化「开发监控·每2分钟巡检续跑」（automation-6d8ea1fb，去重后仅此一个）
- ✅ 双层架构：确定性执行层（timing_engine：心跳/待办探测/可扩展作业）+ LLM 巡检层（续跑开发/重启失败代理）
- ✅ PROGRESS 旧清单勾稽清理（假待办 17→2：免签口岸核对代理运行中 + backfill 阻塞缺 ZHIPU_API_KEY）
- ✅ 全量回归 1063 passed + ruff 干净

## 2026-10-25 第二批收尾（H5 + 名单校订）

- ✅ H5 卡片 👍/👎/✅到了/✍️点评 四按钮（box 点击分支 + /feedback/* 端点接线）
- ✅ H5 点评气泡（星级+REVIEW_TAGS chips+一句话 → POST /feedback/review）
- ✅ H5 批量链接导入（输入框 ≥2 链接自动走 /links/batch + 逐条送规划会话，planBatchImport）
- ✅ H5 预约提示行（🎫 reservation_hint 显示在卡片）+ 免签横幅（上一批）
- ✅ sw VERSION v21→v23（外壳变更）
- ✅ 全量回归 1051 passed + ruff 干净（两次确认）
- ✅ 名单校订：故宫 7天/20:00 ✓（审查稿 8:00 系误）、国博 7天/17:00（5→7 修正）、陕历博 5天/17:00 ✓、三星堆 5天/20:00 ✓；240h 政策快照修正（生效 2024-12-17、现行 57国/65口岸/24省，省份名单与官方逐项一致）
- ⏳ 剩余：~~其余 12 馆逐项核~~ ✅ 2026-10-25 监控会话子代理全量核完 17 馆（7 处官方口径修正已入 reservation_seeds.py，差异与待人工确认项留档 [reservation_seeds_核对_2026-10-25.md](reservation_seeds_核对_2026-10-25.md)）；口岸名录逐项核（后台调研代理运行中，报告将落盘 visa_check_核对_2026-10-25.md）；backfill LLM 层真跑；alembic upgrade head（docker db 未启动）；~~ops 注册 poi_stats_nightly~~ ✅（register_schtasks.cmd 已加行 + 本机 schtasks 注册成功，下次运行 2026-10-26 03:40）；~~天气建议 H5 横幅~~ ✅ 2026-10-25 已接线：rain_ok 透传 + wxRainBar 已在库并通过回归

## 剩余待办（2026-10-25 监控轮对账）

- [x] H5：卡片 👍/👎 + 打卡 + 行后点评卡 + 批量导入（上「第二批收尾」节，已接线并回归）
- [x] 天气建议接线：✅ 行程卡雨天横幅（VisitItem.rain_ok 透传 + index.html wxRainBar；test_rain_ok_passthrough_for_rain_banner 已覆盖）
- [x] reservation 名单校订：✅ 17 馆全量核对完毕（2026-10-25，7 处修正 + 待人工确认项见核对报告）
- [x] 免签名单校订 ✅ 2026-10-25 二轮全量核对完成（后台代理连 4 次死于基础设施错误后由监控会话内联完成）：口岸 20→**65 全表**（47空+14水+2铁+2陆）、24 省勘误（**删吉林/补贵州**）、新增市级范围 city_scope（晋太原大同/赣南昌景德镇/桂12市/川11市 + 主会话三轮补 **滇9市州**——深圳政府问答口径；阿坝·九寨沟现在正确判 fail）、哈尔滨映射修复（吉林→黑龙江）；报告留档 [visa_check_核对_2026-10-25.md](visa_check_核对_2026-10-25.md)，test_visa_check 13 绿（含官方事实钉回归）
- [x] backfill_indoor_rain LLM 层 + review_summary 真跑 ✅（主会话 2026-10-25 晚澄清：**不阻塞**——.env 的 glm_api_key 在、llm_backend=zhipu；`--stage llm` 已实现（规格照抄 backfill_intro_llm：flash 档/严格三词解析/逐列只填空/有界并发，+5 测试）；真跑 heuristic 1855 + llm 119/120 + review_summary 30/30；顺手修 backfill_review_summary 的 get_llm_adapter 漏传 settings bug）
- [x] ops 注册 poi_stats_nightly ✅（schtasks 就绪，2026-10-26 03:40 首跑）；alembic upgrade head ✅（主会话澄清：**DB 非 docker 而是 WSL Ubuntu PG18**（ops/db_up.cmd 拉起），`alembic current` = w12_0010 (head)，无需操作）
- [x] **设计文档 PDF 同步 v1.5 ✅**（2026-10-25）：md 追加 §15 落地收口与运维管道（G1-G6 总账/名单二轮校订/评测集扩样与铁律 20 修复/数据真跑/运维三件/剩余边界）+ 变更记录 v1.5 行；横版 A4 重建 20 页（Edge 无头打印，关键 4 页目检合格：无乱码/表格着色/内容完整）；
- [x] **17 馆预约规则周更管道 ✅**（用户拍板 2026-10-25：每周日晚上全量更新）：`app/jobs/refresh_reservation_rules.py`（zhipu web_search 逐馆核对官方口径 → 五关校验：天数域 1-30/时刻 HH:MM 越界/渠道长度/来源 URL/备注长度 → 三路输出：快照 JSON 落 DESIGN + 与 RESERVATION_V0 diff 报告（名单本体改代码留人工评审，作业不写码）+ 表行覆盖刷新（required/advance_days/官方 URL 落 booking_url））；别名条目（note「同「…」」）继承主馆结果不重复烧 LLM；`--with-visa` 附 240h 口岸数量只读核对；mock 后端跳过；+6 测试（test_refresh_reservation_rules.py）。调度：schtasks「ChinaTrip_reservation_rules_weekly」**每周日 21:00**（ops/reservation_rules_weekly.cmd，日志 devlogs/reservation_rules_weekly.log，2026-10-25 当晚即首跑）。全量 1105 绿

> 监控轮 2026-10-25（第 4 轮收尾）：全量 1063 passed + ruff 干净（含并发会话新入 timing_engine 测试与 enrich_llm_web；其间两次 ruff/收集错误均系对方在写文件的中途快照，已由对方自行收敛，监控只对账不抢改）。免签口岸名录核对代理已第 4 次重拉（前三次死于并发限制/流恢复等基础设施错误），报告落盘后自动跟进修正。
> 监控轮 2026-10-25（第 11 轮）：首跑出现 1 例瞬时失败（失败名被输出截断未捕获），立即复跑两次均 1069 全绿——判定 flaky，暂不处置；若复发，下一轮以完整输出抓取测试名再深查。
> 监控轮 2026-10-25（第 12-14 轮）：indoor/rain 库存补量真跑收官——监控会话连发 4 批 LLM 批次（50/498/442/约400，含与并发会话 enrich 作业的幂等互填），最终批目标 0；残留 74 行系作业目标查询有意排除（无名/非目标类目），非缺口。期间全量 1080 绿；ruff 在对方 booking_auto 开发波峰（25 处中途快照）后自收敛归零，监控未抢改。
> 监控轮 2026-10-25（第 15-17 轮 + 后续会话）：用户指示续跑两件后续——① **booking_auto 交叉回归 ✅**：接缝零漂移（_reservation_hint 已适配 dict 形态 meta['days']/meta['note']；visa/feedback/rain_ok 无接口变动），seam 批次 114 绿；② **8.1.5 评测集扩样 ✅**（10→15 用例）：晚餐窗挂窗、evening 开窗端到端、多窗午休 gap 不排站、时链不缩水、预约 hint 不干扰求解——**扩样抓到真回归并已修**：8.2.4 自动餐厅经 build_food_item 落窗后未 pin，紧跟的全量 solve 把餐自由重排出餐窗（实测 10:30 排餐，违铁律 20）；修复 = v0 插入路径当场 pin 空窗中点（plan.py _assemble_plan，不动 restaurants.py 的 apply_diffs/unpinned 契约）。全量 1090 绿 + ruff 干净（对方 discover_ctrip_slugs 3 处 E501 系在写快照，避让）。

## 已完成（2026-10-25 更新）

- ✅ 8.2.1 best_visit_time→solver 时间窗（子代理完成，48 测绿）
- ✅ 8.1.1 候选库优先 top_pois_in_city（库≥10 跳过 amap；占位路径保留）+ VisitItem.best_visit_time 透传
- ✅ 8.1.2/8.1.3 选点 prompt 全字段（评分·N评/建议时长/宜X/标签/室内/简介）+ reason 输出汇假设 + duration 兜底读 suggested_duration_min
- ✅ 8.2.4 餐厅 v0 自动插入（无 food 日晚餐窗 1 家，≤3 家/程，配额异常静默；auto_restaurants=False 测试开关）
- ✅ 8.2.2 travel matrix（haversine 基线 + leg_cache 高德实测覆写【用户拍板 2026-10-25】）+ 两段式重解（解→实测腿→升级矩阵再解，零额外配额，缓存回放保展示腿）
- ✅ 8.2.3 营业时间 HH:MM-HH:MM 解析进 PoiHours 硬窗（解析不出不硬卡）
- ✅ 8.1.5 评测集 P0 硬闸门：tests/test_engine_constraints.py（同站不重复/每日≤4 裁剪守卫/铁律6/时间不重叠/库优先无占位）——每日>4 裁剪守卫已入 _generate_v0（must 合并前，用户必去不受限）
- 引擎批次测试：test_plan_agent(76)+test_plan_api+test_solver+test_time_slot+eval = 116 全绿；ruff 干净

## 已完成 ✅（地基四件：0009 迁移/store 扩签名/top_pois_in_city/refresh+ctrip 全字段写回——详见 git diff）

| # | 任务 | 产物 |
| --- | --- | --- |
| 1 | 迁移 0009 | `alembic/versions/0009_planning_engine_enrichment.py`（pois +14 列 / restaurants +12 列 / poi_reviews / poi_stats；注意 poi_reviews 的正文字段 DB 列名 `text`、ORM 属性名 `body`——避开 sqlalchemy.text 冲突） |
| 1 | models.py | Poi/Restaurant 新列 + PoiReview/PoiStat 两模型（models.py:214 起） |
| 2 | PoiDetailStore.upsert 扩签名 | 新 kwargs：rating/rating_source/rating_count（**刷新语义**）+ photos/phone/website/district/business_area/suggested_duration_min/duration_source/review_tags/review_tags_source/ticket_price_min/max/ticket_source（**只填空语义**） |
| 2 | PoiDetailStore.top_pois_in_city(city, limit=30, *, exclude_food=True) | 确定性排序 `rating × log2(1+rating_count) × 标签加成(unesco/5a/michelin/black_pearl ×1.5)`；返回 dict：source_poi_id/name/city/category/address/opening_hours/source/rating(float|None)/rating_count/tags/best_visit_time/suggested_duration_min/indoor/rain_ok/review_tags/intro(≤60字)/location(**(lon,lat) 元组**，注意与 amap 的 dict 形状不同)；DB 失败自动内存回退 |
| 2 | search_keyword rating 修复 | 原来恒 None，现返回 row.rating |
| — | 测试 | `pytest tests/test_poi_details.py tests/test_models.py tests/test_poi_seed.py tests/test_poi_backfill.py` 43 passed |

## 进行中 / 待做（按序）

- [x] 3. refresh_pois 写回富化字段（A1-A3/B1）：`place_hours`/`search_hours` 返回值里已有 rating；把 amap v5 detail 的 photos/phone/website/district(从 adcode 或 business area 字段) 接进 upsert 调用（✅ 已完成，见总账）
- [x] 4. ctrip_hours 扩正则（A4/A5/A6/B3）：详情页同页解析 建议游玩时长/评分/点评数/点评标签 chips/门票价 → 新方法 `detail_fields_for(city,name)` 返回 dict，refresh_pois 消费（✅ 已完成，见总账）
- [x] 5-7. 引擎三件套（✅ 已完成，见总账）
- [x] 13. best_visit_time→开窗（8.2.1 完成 2026-10-24）：`_visit_spec` 按 `_BEST_VISIT_WINDOWS`（morning 08-12/afternoon 12-17/evening 17-21/sunset 16-19/sunrise 08-10:30）先于 PoiHours/pinned 收窄开窗，未知枚举按 any 不约束；test_solver.py +5 用例，solver/rules/time_slot 48 passed
- [x] 14. solver travel matrix + poi_hours（✅ 已完成，见总账）
- [x] 8. 互动端点：POST /plan/{sid}/items/{id}/vote（👍=poi_stats.thumbs_up，👎=trip_items unwanted 路径已有）、POST /trip-items/{id}/visit（visited 状态）、POST /pois/{id}/review（写 poi_reviews）
- [x] 9. links/batch 批量导入（H5 侧为主）
- [x] 10. aggregate_poi_stats 夜作业（trip_items GROUP BY 全量重建）+ ops cmd
- [x] 11. backfill_indoor_rain（类别启发式层先做）
- [x] 12. review_summary LLM 蒸馏（mock LLM 下跳过）
- [x] 15. services/itinerary/geo.py 商圈/坐标聚类分日
- [x] 16. 天气感知重排建议
- [x] 17. H5 index.html：卡片反馈/打卡/点评卡/批量导入
- [x] 18. 品类疲劳 + 计划级查全率（5A/UNESCO 白名单 vs 计划）
- [x] 19. 约束回归测试（同店不重复/每天≤4/步行≤15km=铁律6）
- [x] 20. 全量 pytest（`--cov=app --cov-fail-under=75`）+ ruff 通过

## 关键约定（新会话必读）

- Python：`.venv/Scripts/python`（Windows）；测试 `python -m pytest`；lint `python -m ruff check app tests`
- 注释/commit 中文；现有代码风格紧凑
- `poi_stats` 写入走 DB 失败静默（同 poi_details 模式）；dev 无 PG 时内存降级
- solver 契约：`solve_plan(plan, *, poi_hours, travel_minutes, time_budget_seconds)` 已支持 travel_minutes（AddCircuit 目标）——8.2.2 只需在 plan.py `_solve` 构矩阵传入
- 铁律 19：pinned 条目 solver 不动；餐厅插入只落用餐空窗（铁律 20，restaurants.meal_window/rank_by_detour 现成）


## 富化流水线（2026-10-25 夜，简介回填会话追加）✅

> 背景：GLM coding 端点静默忽略 web_search 工具（实测模型自认无搜索能力），
> 「LLM+联网」不存在；确定性源优先。三个新作业（app/jobs/，未提交）：
> enrich_ctrip_detail / enrich_amap_detail / enrich_review_summary，修正版
> enrich_llm_web（纯 LLM 别名）。全部逐列只填空 + *_source 溯源。

| 波 | 内容 | 结果 |
| --- | --- | --- |
| A-prime | ctrip detail（消费本流 item 4 的 CtripHoursReader，60页/城 caps 由作业参数放大，未改 ctrip_hours.py） | 9 城 2125 行：ticket 146 / review_tags 141 / rating 163 / duration 23 / hours +3；头部景点捞净，目录外长尾 miss |
| C | review_tags 到 review_summary 蒸馏（六轮至收敛） | 119+ 条入库（review_summary 现 163 含并行流写入），残约 4 条 bad_length |
| B | enrich_llm_web aliases（纯 LLM） | 14 行可用；web_search 证伪记录在案 |
| A | amap detail（phone/business_area/photos/hours/rating） | 作业就绪；10-25 日配额烧尽（USER_DAILY_QUERY_OVER_LIMIT），明早 9 点自动化 automation-ce495b14 探活后自动全量+顺带蒸馏 |

- 简介任务已收口：3816/3816 = 100%（LLM 549 + 手工 2 + 76 条长尾软删）。
- 残留清单：DESIGN/intro_backfill_residue_2026-10-25.md
- 追加（同夜）：RichCtripReader 子类（作业内）拦截详情页 raw HTML，同页多榨
  phone/district/photos（内嵌 JSON：telephoneList/address/imageList，真页验证
  真号），零额外请求零改 ctrip_hours.py。全量：phone +115 / district +118 /
  photos +98（photos 现 941=24.7%）。business_area 仅高德有结构化字段。
- 待办移交：amap 企业认证（用户侧）；duration 主要靠 item 11 类别启发式层补量。


## CT-first 全国富化收口（2026-10-25 深夜）✅

> 用户令：CT FIRST（高德 API 配额限制，amap 降级为手动备用）；wiki 源弃用
> （易变数据原则 + wikimedia 全家 403）。amap 自动化已撤。

| 动作 | 结果 |
| --- | --- |
| 城市 slug BFS 发现器（discover_ctrip_slugs.py） | 187/203 城；验证 place id=sight id；揪出并覆盖手写错值 guilin32（实为丽江目录） |
| 全国全量（变体匹配+200页大城/10页小城双 reader+同页多榨） | 508 命中零错误：phone +298 / ticket +301 / rating +306 / tags +293 / district +254 / photos +263 / duration +47 / hours +49 |
| 蒸馏 review_tags→review_summary | 累计 341 行（8.9%），巡检持续消化拒绝池 |
| duration 地板值（enrich_heuristics --with-duration，最后放） | +2232 行 → 60.7% |

- 终局 100% 列：intro / best_visit_time / indoor / rain_ok（indoor、rain_ok 由
  并行会话补完，值为 yes/no 字符串，消费方注意）
- 自锁机制：enrich_ctrip_detail 内置 DESIGN/ctrip_enrich.lock（<90min 让位），
  45 分钟巡检 automation-636cd8c4 与主会话可安全共存/接管
- 剩余封存：website（无携程/高德源，wiki 弃用）、business_area（仅高德有）
