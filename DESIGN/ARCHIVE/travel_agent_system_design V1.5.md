# 随行旅行 Agent — 设计文档 v1.5.2（终版）

> 版本：v1.5.2 ｜ 状态：可直接开工（**海外区先行**）
> v1.5.1 增量：**付费基建前置、收费时机后置**——权益服务（Entitlement）+ IAP 接口一期建成；何时开收费 = 远程配置的运营决策，不发版。
> v1.5.2 增量：**付费墙升级为场景规则引擎**——任意时间、任意场景可简单配置（事件 + 条件 → offer 动作），客户端统一 PaywallGate 组件零硬编码。
> 合并范围：v1.3 全部内容 + 五轮评审裁决 + 行程快照版本功能。
> 核心变更：**①海外区先行 scope 收敛（最大决策）②北极星指标改为行程时间预测准确率 ③行程快照版本功能 ④铁律 0 统一变更管线 + 铁律扩充至 19 条 ⑤地图许可隔离（高德/OSM 不混库）⑥注入防御架构化 ⑦付费墙后移 + 免费应急兜底 ⑧轨迹数据单列敏感级 ⑨渐进式规划 ⑩节奏量化建模**

---

## §1 产品定义

### §1.1 四象限用户场景 + 发布顺序

| | 境外规划 | 境内执行 |
|---|---|---|
| **外国用户** | 海外区注册（邮箱/Apple），出发前规划 | 入境后定位检测 → 执行模式 |
| **国内用户** | 国内区注册（手机号/微信），无入境检测 | 直接执行 |

- **发布顺序决策（v1.5）：海外区先行。** Phase 1 只上 AWS 新加坡区（外国用户入境场景）；国内区待合规串行链完成后作为 Phase 2 上线。理由：备案链 1–3 个月串行不可加速，双区并行 11 周不可行；外国入境游客付费意愿最强、竞品最弱；数据驻留铁律使后上国内区零数据迁移成本。
- **范围声明**：国内用户出境游一期不做（四象限之外，避免定位检测与 region 逻辑歧义）。

### §1.2 核心差异点

执行模式随行 Agent（重排 / 讲解——截图带不走的价值）+ **紧急卡**（110/120/119/最近警局医院/使领馆信息，纯静态本地数据，离线可用，零合规风险）。

### §1.3 商业模式

- **规划免费**（获客锚点）。
- **海外**：执行期**消耗型 IAP $6.99/行程**（重排 + 完整讲解 + 误车跨天改），服务端收据校验 + webhook 退款回收权益。Stripe 仅保留给未来非数字商品，一期不上。
- **国内**：门票/餐厅佣金 + 增值订阅 **¥39–68/行程**（IAP 档位）。**佣金分销选型 W11 前必须完成**：海外用户走 Trip.com affiliate，国内走美团/携程联盟——这是商业模式支柱，不是可选项。
- **付费开关化（v1.5.1 决策）**：付费基建（IAP、收据校验、权益系统）一期建成，但**何时开始收费是运营决策，全部远程配置**——付费墙总开关（支持分地区/分用户群灰度）、免费额度数、快照上限、触发时机均为服务端配置；默认策略 = 全免费，可随时灰度开启，**不需要发版**。
- **免费额度 = 每行程 1 次重排**（绑定 itinerary，不绑日历月）。
- **免费应急兜底（v1.5 新增，永远免费）**：误车/错过时免费给出「最近替代班次 + 打车 deeplink」——静态数据 + deeplink，成本近零，慌张时刻救命不收费。
- **付费墙后移（v1.5 修正）**：慌张时刻只做价值展示（免费应急兜底），付费转化推送放在**慌张解决后 30 分钟**（情绪平复 + 感激峰值）。卖「安心」（下次提前预警 + 全程自动重排），不卖「救命」——防止「绑架行程」差评反噬，评分是旅行产品的获客引擎。
- **快照版本额度**：免费 **3 版** / 付费 **10 版**（服务端配置化，不写死）。
- **iOS 必须申请 App Store Small Business Program**（15% 而非 30% 抽成）。
- **单位经济硬指标（v1.5 量化）**：毛利底线 **≥65%**；**讲解缓存命中率 ≥90% 升格为核心经营指标**（缓存与否 = 亏损边缘 vs 70% 毛利的分水岭）；月度成本复核。

---

## §2 技术选型

| 层 | 选型 |
|---|---|
| 移动端 | Flutter 3.x + Riverpod 2 + drift（SQLite） |
| 后端 | Python FastAPI |
| 数据库 | PostgreSQL + PostGIS（Alembic 迁移） |
| 缓存/状态 | Redis（会话状态、成本闸门计数、WS 连接注册表） |
| 实时 | WebSocket（FastAPI 原生）：**握手鉴权 + 心跳 + seq/resume 断线补发**；SSE 备选降级 |
| LLM 接入 | LiteLLM 自建网关，按 region 路由；**fallback 链**（CN：Qwen→GLM；海外：Claude→GPT-4o） |
| API 网关 | 云厂商现成，不自建 |
| 部署 | Docker Compose，两区各一台云主机；**蓝绿发布（双 compose + nginx 切换）**；每日快照 + WAL 归档，**备份季度恢复演练** |
| 高德 Key | **企业认证 Key + 服务端代理调用，Key 永不进客户端** |
| 地图分层（v1.5 许可隔离） | **瓦片 = OSM/MapTiler（允许离线缓存，ODbL 署名）｜ POI/路径 = 高德 API 实时调用（不存瓦片）。两库物理隔离，禁止混库**——ODbL Share-Alike 传染性 + 高德禁止批量缓存，混库 = 许可炸弹 |
| CDN/加速 | **只缓存静态资源**（瓦片/讲解模板/App 包），用户 API 响应一律 `no-store`——否则全球加速与数据驻留铁律自相矛盾 |
| 观测 | Sentry（崩溃/性能）+ 云监控告警 + **trace_id 贯穿 App→API→LLM** |

---

## §3 接入设计

- 登录双轨：海外（邮箱验证码 + Apple，禁 Google OAuth）｜ 国内（手机号验证码 + 微信）。
- **数据驻留铁律**：用户数据只落所在区，永不跨境同步。
- **参考数据同步方向定案（v1.5）**：**CN 区为参考数据主库，单向复制到海外区**（POI 几乎全是中国城市，CN 区靠近数据源）。白名单 = pois / 班次静态库 / 讲解模板 / **匿名化行程模板**（二期）。讲解文案判定为参考数据（不含用户信息），在 CN 区生成后经白名单同步，判定依据写入本节备查。
- **推送入境切换**：海外区统一 APNs（入境后可达）；Firebase 境内到达率实测推迟到国内区上线前（海外先行后不再是 P0）。
- **多设备策略（v1.5 明确）**：last-write-wins + WS 互踢通知（「另一设备已更新行程」）。

### §3.3 合规清单（串行关键路径，本周启动，与开发并行）

> 这条链是**串联**的，任何一环卡住国内区上架整体停摆——它是项目真正的关键路径，不是工程。

1. **高德书面确认四问一次发工单**（本周最高杠杆动作）：①商用授权范围 ②**POI 数据持久化存储与二次加工（双语翻译）许可** ③瓦片任何形式缓存的禁止确认（佐证瓦片选型）④海外访问 SLA 与计费。漏问一条 = 工期 +1 个月。
2. 国内公司注册 → ICP 备案 → App 备案（1–3 个月）→ 软著 → 上架；备案号 App 内展示。
3. **生成式 AI 服务备案/登记（v1.5 补）**：接入已备案模型（Qwen/GLM）走登记简化路径；产品义务同步落地：**AI 生成内容标注 + 投诉举报入口 + 安全评估**。
4. 微信支付商户号；iOS 双区 IAP。
5. **隐私清单（Privacy Manifest）**：第三方 SDK 清单 + required reason API 声明，提审前统一检查。
6. **账号删除入口 + 数据导出**（App Store / Google Play / 个保法 / GDPR 四方强制）；删除级联 itineraries/traces/snapshots。
7. **数据分级保护（v1.5 升格）**：
   - **轨迹级（最高）**：`execution_events` 含外国人在华行踪轨迹——静态加密 + 独立密钥 + **保留期 30 天** + **员工访问双人审批 + 审计日志**（客服只看聚合偏差，不看原始轨迹）；
   - 用户位置 TLS 1.3 传输加密；支付信息不存储；行为数据匿名化。
8. 未成年人条款与退款申诉流程。
9. **抓取合规**：遵守 robots.txt、频率白名单、优先官方公告页。
10. 术语：**双主体** = 国内/海外两个法律主体的分工（W7 前完成决策）。

---

## §4 数据模型

**原则不变：数据模型一次到位（多城），功能分期解锁（先单城）。单城也走多城写入路径。**

```sql
-- W1-2 建表（全部建齐，约束先立）
CREATE TABLE users (
  id UUID PRIMARY KEY,
  region VARCHAR(10) NOT NULL,         -- 'CN' | 'OVERSEAS'（修正 VARCHAR(2) 存不下 OVERSEAS）
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()   -- 全表补审计字段
);

CREATE TABLE pois (
  id UUID PRIMARY KEY,
  source VARCHAR(20) NOT NULL,         -- 稳定业务键：刷新走 upsert，UUID 永不变
  source_poi_id VARCHAR(100) NOT NULL,
  UNIQUE(source, source_poi_id),       -- 防止管线刷新打断 itinerary_items 引用
  city VARCHAR(50) NOT NULL,
  name_zh VARCHAR(200), name_en VARCHAR(200),
  category VARCHAR(50),                -- 含 transport_hub
  status VARCHAR(20) DEFAULT 'active', -- 关停/搬迁 → 行前体检联动
  location GEOGRAPHY(POINT, 4326),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_pois_location ON pois USING GIST (location);
CREATE INDEX idx_pois_city ON pois (city);

CREATE TABLE poi_hours (               -- 营业时间规则表（粒度补齐）
  id UUID PRIMARY KEY,
  poi_id UUID REFERENCES pois(id),
  rule_type VARCHAR(20) NOT NULL,      -- standard | holiday | special（淡旺季/午间闭馆）
  payload JSONB NOT NULL
);

CREATE TABLE itineraries (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  cities TEXT[] NOT NULL,
  title VARCHAR(200),
  working_sync_version INT NOT NULL DEFAULT 1,  -- 原 version 改名：技术同步计数器
  active_snapshot_id UUID,             -- 执行版；NULL = 工作副本直接执行
  status VARCHAR(20) DEFAULT 'draft',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
  -- execution_log 字段移除 → 独立表（JSONB 挂热表无界膨胀）
);

CREATE TABLE itinerary_snapshots (     -- ★ v1.5 新增：用户快照版本
  id UUID PRIMARY KEY,
  itinerary_id UUID REFERENCES itineraries(id),
  name VARCHAR(100),                   -- 自动「版本1 · 10/17 15:20」，可改名
  note TEXT,                           -- 用户备注 or LLM 差异摘要
  sync_version INT NOT NULL,           -- 保存时工作副本版本（溯源）
  created_at TIMESTAMP DEFAULT NOW()
  -- 不可变：无 updated_at，不暴露 UPDATE 接口
);

CREATE TABLE itinerary_days (
  id UUID PRIMARY KEY,
  itinerary_id UUID REFERENCES itineraries(id),
  snapshot_id UUID REFERENCES itinerary_snapshots(id),  -- NULL = 工作副本
  day INT NOT NULL,
  base_city VARCHAR(50) NOT NULL,
  UNIQUE(itinerary_id, day, snapshot_id)
);

CREATE TABLE intercity_transfers (
  id UUID PRIMARY KEY,
  itinerary_id UUID REFERENCES itineraries(id),
  snapshot_id UUID REFERENCES itinerary_snapshots(id),
  day INT NOT NULL,
  seq INT NOT NULL DEFAULT 1,          -- 放宽「一天一跨城」：同日内有序多段
  from_city VARCHAR(50), to_city VARCHAR(50),
  mode VARCHAR(20),
  UNIQUE(itinerary_id, day, seq, snapshot_id)
);

CREATE TABLE itinerary_items (
  id UUID PRIMARY KEY,
  itinerary_id UUID REFERENCES itineraries(id),
  snapshot_id UUID REFERENCES itinerary_snapshots(id),
  day INT NOT NULL,
  poi_id UUID REFERENCES pois(id),
  position FLOAT NOT NULL,
  start_time TIME, end_time TIME,      -- 一律行程城市时区（铁律 13）
  draft BOOLEAN DEFAULT TRUE
  -- sync_status 字段删除：与全量覆盖机制语义重叠
);

CREATE TABLE execution_events (        -- ★ v1.5：独立表，按月分区
  id UUID PRIMARY KEY,
  itinerary_id UUID REFERENCES itineraries(id),
  ts TIMESTAMP NOT NULL,
  type VARCHAR(40) NOT NULL,           -- 事件分类法 v1（见下）
  payload JSONB
) PARTITION BY RANGE (ts);

CREATE TABLE entitlements (            -- ★ v1.5.1：权益系统（付费基建前置，收费时机后置）
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),   -- 匿名期挂 device_id 映射的 shadow user
  itinerary_id UUID REFERENCES itineraries(id),
  product_id VARCHAR(50) NOT NULL,     -- exec_pass（消耗型）/ sub_cn（订阅）等
  status VARCHAR(20) NOT NULL,         -- active | consumed | refunded
  source VARCHAR(20) NOT NULL,         -- ios_iap | wechat | promo | free_grant
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE iap_transactions (        -- 收据校验留痕 + 退款 webhook 对账
  id UUID PRIMARY KEY,
  entitlement_id UUID REFERENCES entitlements(id),
  platform VARCHAR(10) NOT NULL,       -- apple | google | wechat
  transaction_id VARCHAR(100) UNIQUE NOT NULL,
  receipt_payload JSONB,
  verified_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE paywall_rules (           -- ★ v1.5.2：付费场景规则引擎（任意场景可配）
  id UUID PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  enabled BOOLEAN DEFAULT FALSE,       -- 默认全关 = 全免费
  priority INT DEFAULT 100,
  trigger_event VARCHAR(40) NOT NULL,  -- 场景事件（见 §6.8 场景目录）
  conditions JSONB,                    -- 任意条件：day>=N / quota_used>=M / region / 灰度比例…
  offer JSONB NOT NULL,                -- product_id + 文案 key + 折扣/试用
  caps JSONB,                          -- 频次上限：每日/每行程最多次数、冷却期
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 其他：itinerary_members（协作预留）· extraction_logs · agent_traces · user_interests · user_visited
```

**事件分类法 v1（为评估而生，建表前评审定稿）**：
`schedule_predicted` / `check_in` / `check_out` / `replan_proposed` / `replan_accepted` / `deviation_reported`（**端上计算偏差，只上传聚合分钟数，不上传轨迹**）/ `emergency_served` / `paywall_shown` / `paywall_converted`。

**快照语义（铁律 16–18 的数据层落地）**：快照内容 = 三张行程表按 `snapshot_id` 行级复制；恢复 = 读快照行 → 覆盖写回 `snapshot_id=NULL` 的工作副本 + `working_sync_version +1` + WS 全量覆盖推送——**复用现有同步机制，客户端零新逻辑**。

---

## §5 移动端

- 六页：聊天页 · 地图页 · 时间线页（天主轴 Day1/Day2…，跨城交通 = 日内特殊卡片）· 收藏页 · 足迹页 · 执行模式页。
- **版本入口（v1.5）**：时间线页/行程详情 → 保存此版（自动命名 + 备注 + LLM 差异摘要）/ 版本列表 / 基于此版继续改 / 设为执行版。恢复前工作副本有未保存改动 → 弹窗「先存一版 / 丢弃并恢复」。
- **手动编辑（v1.5）**：时间线拖拽/改时间 = 本地生成 diff op，**与 LLM 同管线校验**（铁律函数的 Dart 移植版，纯函数移植成本可控）——改个时间零 LLM 成本、零 3 秒等待，离线可用。
- **离线 = 执行模式生存底线**：行程 + **OSM/MapTiler 瓦片**（2km 走廊 ≤150MB）+ 讲解文案预下载；音频 = 预合成包可选下载（+30MB）或系统 on-device TTS 降级（解决「TTS 在线 vs 离线底线」矛盾）。
- **时区铁律（铁律 13）**：一切时间计算以行程城市时区为准，推送注册时折算——防止用户手机在出发国时区导致凌晨推送。
- **到点提醒**：geofence 动态注册（只保留下一个点，≤2 个常驻），避免常驻后台定位的耗电与审核风险。
- **通知权限 priming**：先解释价值再请求系统权限；被拒后 App 内 briefing 页兜底。
- **隐私（v1.5）**：预测偏差在端上计算，只上传聚合值；轨迹不出设备。

### §5.4 同步机制（全量覆盖，不做增量合并）

- `working_sync_version` 每次变更 +1；本地 drift 存 `sync_state(itinerary_id, last_version)`。
- 触发时机：App 前台激活 + 收到 WS 推送；本地落后即拉全量覆盖**当天及之后**的天数（铁律 12）。
- **多设备**：last-write-wins + WS 互踢通知。
- **快照**：服务端权威，本地缓存只读。

---

## §6 Agent 设计

### §6.0 行程变更管线（Itinerary Mutation Pipeline）★ v1.5 新增

> **铁律 0：一切行程变更——LLM 重排 / 手动拖拽 / 快照恢复 / propose_replan——产出统一 diff op，进同一硬校验管线。无例外通道。**

硬校验从「Agent 的校验函数集」升格为**独立行程域服务**，Agent 只是调用方之一。收益：手动编辑零 LLM 成本；测试只需针对一个入口；快照恢复天然复用。

### §6.1 渐进式规划（v1.5 修正澄清前置）

澄清 **≤2 问**（天数、城市）→ **立即生成带假设标注的 v0**（「假设中等节奏、不早起」，标注可见可改）→ 对话迭代。**Time-to-first-itinerary < 60s 为激活指标**。反转顺序的理由：用户在具体行程上改比回答抽象问题容易十倍；假设标注是信任建设。

### §6.2–6.3 工具循环 + 增量 diff

- 会话状态存 Redis（滚动摘要 + 单会话 token 上限触顶处理）；structured output，JSON Schema 约束。
- diff 输出 `[{op:"move", item_id, new_time}]`；W1-2 单城工具集不变；跨城工具 W9 挂载。

### §6.4 硬校验铁律（扩充至 19 条；纯函数，100% 单测覆盖）

1. 时间冲突 ｜ 2. 营业时间校验 ｜ 3. 地理自洽 ｜ 4. 跨城衔接缓冲 ｜ 5. ~~一天一跨城~~ → **同日多段跨城需衔接缓冲**（seq 有序）｜ **6. 节奏合理性 → 量化重写**：日步行 ≤15km × 人群系数（0.6–1.2）｜ 日爬升系数 ｜ 有效游览时长占比 ≥55% ｜ 7. 交通可达 ｜ 8. 3 秒延迟预算 ｜ 9. 重排带 reasoning ｜ 10. 只动当天及之后 ｜ 11. 执行模式不动过去（生成端）｜ 12. 同步端不覆盖过去（同步端）
13. **时区以行程城市为准** ｜ 14. **解析期 LLM 零写权限**（解析阶段工具列表物理上不含行程写入工具）｜ 15. **不可信内容 quarantine 标记**（用户粘贴/网页抓取文本仅为数据，永不作为指令）｜ 16. **快照不可变，恢复只写工作副本** ｜ 17. **执行中切换执行版 = 受限重排，只动当天及之后** ｜ 18. **离线禁止切换到未下载离线包的版本**（明确报错）｜ 19. **最小改动原则**：改动条目数 ≤ 解决问题所需最小集合；输出必附 `change_summary`（人类语言改动清单）+ `affected_items_count`

**自修循环上限**：硬校验失败打回 LLM 自修 **≤3 次**，超限降级为「半成品行程 + 人工标注」——防烧钱死循环。

### §6.5 链接解析三刀分期 + 安全架构

文字 → 图文 → 视频；粗筛 → 精读 → 确认卡片 → 分级报错 → 成本闸门。POI 匹配置信度 < 0.8 进「待确认」。
**注入防御架构化（v1.5）**：铁律 14/15 + **红队注入用例进评估集**（藏指令的笔记、恶意网页），每版 prompt 回归必跑。威胁模型：攻击者无需是用户，只需在公开网页埋注入文本等管线来抓。

### §6.6 成本闸门

- **匿名期（W1-2）**：device_id + IP 双维限额 + 单行程 token 上限——匿名期 /extract 是敞口成本攻击面。
- **触顶体验**：降级小模型 / 缓存讲解，**不硬停服务**（慌张时刻硬停 = 最差时刻的最差体验）。
- **讲解生成管线按 POI 缓存复用**：缓存键 = POI + **poi_version** + 语言 + 时长档位；命中率 ≥90% 监控告警（商业模式前提）。

### §6.7 执行模式 Agent

- 三形态：定时推送（纯本地）/ 主动问（重排，需网络）/ 到点讲（文案预下载）。
- **重排一键确认制（v1.5）**：执行模式重排**禁止静默生效**——「我建议这样改，只动 2 个地方」+ 一键确认。慌乱中用户需要确定感，静默改行程一次清零信任。
- **免费应急兜底路径**：误车 → 最近班次 + 打车 deeplink，永远免费。
- `propose_replan` = 规划 Agent 受限子调用，走统一变更管线。

### §6.8 权益服务（Entitlement Service）★ v1.5.1 新增 / v1.5.2 升级

> **原则：付费基建前置，收费时机后置，任意场景可配。** 接口和闸门第一天就建好；何时开、在哪个场景开、对谁开、展示什么 offer，全部是规则配置，运营决策不需要发版。

**① 付费点统一查权益，禁止硬编码免费/付费**：重排额度、讲解档位、快照上限（3/10）、误车跨天改——调用前一律过权益服务。

**② 付费场景规则引擎（v1.5.2 核心）**：付费墙不是几个固定开关，而是规则表 `paywall_rules`：

```jsonc
// 一条规则 = 什么时候 + 什么场景 + 给谁 + 展示什么
{
  "name": "慌张解决后转化",
  "enabled": false,                      // 默认全关 = 全免费
  "trigger_event": "emergency_resolved", // 场景事件
  "conditions": {                        // 任意组合条件
    "delay_minutes": 30,                 // 事件后延时
    "region": "OVERSEAS",
    "replan_quota_used": ">=1",
    "rollout_pct": 20                    // 灰度 20%（user_id 哈希）
  },
  "offer": { "product_id": "exec_pass", "copy_key": "paywall.panic_resolved" },
  "caps": { "per_trip_max": 1, "cooldown_hours": 24 }
}
```

**③ 付费场景目录（trigger_event 枚举，四阶段全覆盖，新场景 = 加枚举 + 加规则，不改代码）**：

| 阶段 | 场景事件 |
|---|---|
| 规划期 | `snapshot_limit_hit`（快照超 3 版）· `narration_preview_end`（讲解试听结束）· `multi_city_unlock` |
| 执行前 | `offline_pack_download`（下载离线包时）· `trip_day1_morning` |
| 执行中 | `replan_quota_exhausted`（免费重排用完）· `emergency_resolved`（应急兜底解决后 N 分钟）· `narration_locked`（到点讲解付费档） |
| 执行后 | `footprint_review`（足迹页回忆）· `share_itinerary`（分享时） |

**④ 客户端零硬编码**：统一 `PaywallGate` 组件——任何场景只上报「事件 + 上下文」，服务端规则引擎匹配后返回「展示哪个 offer / 不展示」，客户端只负责渲染。**新增付费场景 = 后台加一条规则**；调整时机 = 改 conditions。

**⑤ 安全阀**：`caps` 频次上限 + 冷却期兜底（任何场景每天最多弹 N 次）；规则表全部改动留审计日志；`kill switch` 一键全局关闭。

**⑥ 默认策略 = 全免费**（所有规则 `enabled=false` + 额度放宽）；开启时按 `rollout_pct` 灰度放量，观察转化与差评率再全量。

**⑦ 匿名期即落 entitlement 数据**（device_id 维度 shadow user，登录后迁移合并）——从第一天就有额度消耗与权益留痕，未来开启收费时转化漏斗基线数据已在。

**⑧ IAP 工程闭环**：消耗型商品 → 服务端收据校验（iap_transactions 留痕）→ entitlement 激活 → webhook 退款/撤销 → entitlement 状态回收。

**⑨ 与成本闸门的关系**：权益服务管「**能不能用**」（商业闸门），成本闸门管「**烧不烧钱**」（成本闸门），两者独立、都要过。

---

## §7 评估体系

- **北极星指标（v1.5 修正）：行程时间预测准确率**（预测 vs 实际偏差，**端上计算只传聚合值**）。「执行模式周留存」降为结果指标——它掉了你不知道哪环断了，不可操作。
- 因果链：付费转化 ← 慌张采纳率 ← 信任 ← 前几天预测准 ← 预测准确率。它是唯一可操作的北极星。
- 过程指标：**TTI <60s**（激活）、规划→确认转化、**慌张解决后 30 分钟付费转化**、重排采纳率（联动 `affected_items_count`——改动数 vs 采纳率是质量信号）、离线可用率、**讲解缓存命中率 ≥90%**、月度毛利复核。
- 每轮交互落 `agent_traces`；**prompt 文件化 + 版本号落 traces，评估集回归测试**（含红队注入用例）。
- 评估飞轮：执行偏差按城市/POI 类目/时段聚合 → 校准 `estimate_travel_time` 与节奏量化阈值。

---

## §8 数据管线

- 每日 02:00 (UTC+8)：多源采集 + 仲裁引擎；源 D = 头部 POI 官网公告（**合规抓取**：robots.txt + 频率白名单），T-30 抓节假日例外落 `poi_hours` 规则表。
- 变更检测三层：ETag + 哈希 + LLM。
- **POI 稳定键 upsert**（source + source_poi_id），UUID 永不变——管线刷新不打断行程引用。
- **行前体检（v1.5）**：`poi_status` 变更（关停/搬迁/营业时间调整）→ 执行前一天服务端扫描受影响行程 → 推送预警，不等到现场才发现。
- 班次静态库：周级刷新，只读展示，购票跳 12306 deeplink；`TrainService` 抽象层不变。
- **讲解生成在 CN 区**（Qwen 成本优，英文质量 W5-6 验证），经白名单单向同步海外区。
- **模板飞轮（二期）**：高表现快照经用户 opt-in 授权 → 匿名化（剥离标识与精确日期，只留结构）→ 行程模板库 → 新用户冷启动检索 + 天然评估集。匿名化模板作为白名单单列一类。

---

## §9 路线图（海外区先行；人力假设 2–3 人：1 Flutter + 1 后端/Agent + 0.5 数据/合规）

| 周次 | 内容 |
|---|---|
| **W1-2** | **海外区**最小闭环：FastAPI 骨架 + `/extract` + **建表全量**（含快照表/execution_events 分区/POI 稳定键/poi_hours）+ 高德服务端代理 + 用量日志 + device_id+IP 限额。匿名 device_id |
| W3-4 | 规划 Agent 单城（渐进式澄清）+ **行程变更管线域服务（铁律 0–19，100% 单测）** + **快照 API** + 四适配器接口与 mock + **权益服务（含远程配置，默认全免费）** |
| W5-6 | 多源仲裁（合规抓取）+ 双语 POI（CN 主库）+ 时间线页 + **版本 UI + 差异摘要** + Qwen 英文讲解质量验证 |
| W7-8 | Apple/邮箱登录 + LiteLLM + WS（鉴权+seq/resume）联调 + **TestFlight 内测** |
| W9-10 | 执行模式三形态 + 离线包（OSM 瓦片）+ **执行版绑定 + 铁律 17/18** + 多城解锁 + **紧急卡** |
| W11+ | 重排 Agent + 讲解管线 + **消耗型 IAP 真接 + 收据校验对账**（权益服务已在 W3-4 就位，此处仅接支付渠道）→ **海外区上架（默认全免费，收费开关留待运营决策）** |
| 二期 | 国内区（合规链完成后：生成式 AI 备案/隐私清单/厂商推送实测）· **佣金分销对接** · 误车跨天 · 实时排队 · 协作 · **模板飞轮（opt-in）** · 微信小程序 |

---

## §10 风险清单

| 风险 | 等级 | 对策 |
|---|---|---|
| **高德 POI 存储授权被否决** | P0 | 书面确认四问本周发；备选：OSM POI + 官网源自建库（架构已许可隔离，切换代价可控） |
| 高德海外链路延迟 | P0 | W1-2 实测，与调用量基线合并评估 |
| 生成式 AI 备案周期 | 中 | 本周启动登记路径；海外先行使其不阻塞 Phase 1 |
| App 备案周期 1–3 个月 | 中 | 本周启动，仅阻塞国内区 |
| 「绑架行程」差评反噬 | 中 | 已由付费墙后移 + 免费应急兜底缓释 |
| Prompt 注入 | 中 | 已由铁律 14/15 + 红队评估集缓释 |
| Firebase 境内到达率 | 低（延期） | 海外先行后推迟至国内区上线前实测 |
| 境内 WS 流式 | 低（延期） | 同上 |
| 12306 数据源稳定性 | 中 | 静态库只读 + deeplink 交易分离 |
| 双主体决策 | 中 | W7 前完成 |
| 单机故障 | 中 | 蓝绿发布 + 每日快照 + 季度恢复演练 |

---

## §11 下一步动作（本周）

1. ⚖️ **高德书面确认四问一次发工单**（商用范围 / POI 存储与双语加工 / 瓦片禁存确认 / 海外 SLA）——最高杠杆。
2. ⚖️ 国内公司注册 + 备案材料准备 + 生成式 AI 登记咨询（不阻塞海外区）。
3. 🔨 **W1-2 开工**：FastAPI 骨架 + `/extract` + 建表全量 + 高德服务端代理 + 用量埋点 + 匿名限额。
4. 📊 **事件分类法 v1 评审定稿**（建表前必须完成，预测准确率指标依赖它）。

---

## §变更记录

| 版本 | 变更 | 影响 |
|---|---|---|
| v1.5.2 | **付费墙升级为场景规则引擎**：新增 paywall_rules 表（事件+条件→offer，优先级/冷却期/灰度比例）；付费场景目录覆盖规划期/执行前/执行中/执行后四阶段共 10 个场景事件；客户端统一 PaywallGate 组件零硬编码——新增付费场景 = 后台加规则，不改代码不发版；频次上限 + kill switch 安全阀 | §4 / §6.8 |
| v1.5.1 | **付费基建前置、收费时机后置**：新增权益服务（§6.8）+ entitlements/iap_transactions 表；所有付费点统一查权益；付费墙开关/额度/触发时机全远程配置，默认全免费可灰度；匿名期即落 entitlement 数据留转化基线；W3-4 建权益服务，W11+ 仅接支付渠道 | §1.3 / §4 / §6.8 / §9 |
| v1.5 | 海外区先行 scope 收敛；北极星改预测准确率 + 事件分类法 + execution_events 独立分区表；行程快照版本（itinerary_snapshots + snapshot_id 三表 + active_snapshot_id + 铁律 16-18）；铁律 0 统一变更管线 + 铁律扩充至 19（时区/零写权限/quarantine/快照/最小改动）；节奏量化（步行/爬升/占比/人群系数）；地图许可隔离（OSM 瓦片 + 高德 API 不混库）；CDN 仅缓存静态；参考数据 CN 主库单向复制；付费墙后移 + 免费应急兜底；轨迹数据敏感级（30 天/加密/双人审计/端上测量）；渐进式规划 TTI<60s；自修循环 ≤3 次；讲解缓存命中率 ≥90% 升格经营指标；佣金分销选型 W11 前置；紧急卡；消耗型 IAP + 收据校验；蓝绿发布/备份演练/Sentry；一天一跨城放宽为 seq 多段；region VARCHAR(10)；多设备 last-write-wins；模板飞轮二期 | 全文 |
| v1.3 | 铁律 12 + version 全量覆盖；多城模型一次到位；免费额度每行程 1 次；12306 deeplink + TrainService；高德企业 Key；PostGIS 前置；打车降级链；IAP 小企业计划 | §1.3/§2/§3.3/§4/§5.4/§6.4/§8/§9/§10 |
| v1.2 | 多城模型、执行模式 Agent、商业模式、离线底线 | 全文 |
