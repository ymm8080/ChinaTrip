# 随行旅行 Agent — 设计文档 v1.3（终版）

> 版本：v1.3 ｜ 状态：可直接开工
> 合并范围：v1.2 全部内容 + 三轮评审中确认采纳的修订（铁律 12、version 同步机制、多城写入路径锁死、高德企业 Key + 书面确认 + 用量埋点、PostGIS 前置、12306 deeplink 定案、免费额度改为每行程 1 次、IAP 定价分层、打车降级链、TrainService 抽象层）

---

## §1 产品定义

### §1.1 四象限用户场景

| | 境外规划 | 境内执行 |
|---|---|---|
| **外国用户** | 海外区注册（邮箱/Apple），出发前规划 | 入境后定位检测 → 执行模式 |
| **国内用户** | 国内区注册（手机号/微信），无入境检测 | 直接执行 |

### §1.2 核心差异点

执行模式随行 Agent（重排 / 讲解——截图带不走的价值）。

### §1.3 商业模式

- **规划免费**（获客锚点）。
- **海外**：执行期订阅 **$6.99/行程**（重排 + 完整讲解 + 误车跨天改）。
- **国内**：门票/餐厅佣金 + 增值订阅 **¥39–68/行程**（落档时对齐 iOS 中国区 IAP 价格档位）。
- **免费额度 = 每行程 1 次重排**（额度绑定 itinerary，不绑定日历月——防止规划期耗尽、慌张时刻没额度）。
- **付费墙触发时机**：执行第一天推送转化；第二次慌张时刻即付费点。
- **iOS 必须申请 App Store Small Business Program**（年收入 < $1M 抽成 15% 而非 30%），直接决定国内定价档位。
- 单位经济模型：单行程成本 = LLM 调用 + 加速线路 + 推送 + 高德调用（按实测基线），定价上线前验证毛利底线。

---

## §2 技术选型

| 层 | 选型 |
|---|---|
| 移动端 | Flutter 3.x + Riverpod 2 + drift（SQLite） |
| 后端 | Python FastAPI |
| 数据库 | PostgreSQL + PostGIS |
| 缓存/状态 | Redis（会话状态、成本闸门计数、WS 连接注册表） |
| 实时 | WebSocket（FastAPI 原生），SSE 备选降级 |
| LLM 接入 | LiteLLM 自建网关，按 region 路由 |
| API 网关 | 云厂商现成（AWS API Gateway / 阿里云 API 网关），不自建；熔断/限流逻辑挂在 LLM 网关与成本闸门层 |
| 部署 | Docker Compose，两区各一台云主机（不上 K8s） |
| 高德 Key | **开发期即走企业认证 Key**（勾选海外访问权限），个人 Key 路径封死 |

---

## §3 接入设计

- 登录双轨：海外（邮箱验证码 + Apple，禁 Google OAuth）｜ 国内（手机号验证码 + 微信）。
- **数据驻留铁律**：用户数据只落所在区，永不跨境同步。跨区同步白名单仅含参考数据（pois / 班次静态库 / 讲解模板）。

### §3.3 合规清单（本周启动，与开发并行不阻塞）

1. 国内公司注册（个人主体无法 App 备案）。
2. ICP 备案 → App 备案（周期 1–3 个月）→ 软著 → 商店上架；备案号须在 App 内展示。
3. 高德企业认证 + 商用授权政策**书面确认**（工单/邮件留痕，不接受口头答复）。
4. 微信支付商户号申请（需营业执照）；iOS 国内区虚拟订阅走 IAP，注意 30%/15% 分成差异。
5. 数据分级保护：用户位置 TLS 1.3 传输加密；支付信息不存储；行为数据匿名化。
6. 隐私合规双轨：国内个保法 + 海外 GDPR；`execution_log` 默认保留 90 天、用户可一键删除。

---

## §4 数据模型

**原则：数据模型一次到位（多城），功能分期解锁（先单城）。单城行程也走多城写入路径——W9 解锁跨城是加功能，不是改数据流向。**

```sql
-- W1-2 建表（全部建齐，transfers 允许为空表，约束先立）
CREATE TABLE users (
  id UUID PRIMARY KEY,
  region VARCHAR(2) NOT NULL,          -- 'CN' | 'OVERSEAS'
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE pois (
  id UUID PRIMARY KEY,
  city VARCHAR(50) NOT NULL,
  name_zh VARCHAR(200), name_en VARCHAR(200),
  category VARCHAR(50),                -- 含 transport_hub 类目
  location GEOGRAPHY(POINT, 4326),
  ...
);
CREATE INDEX idx_pois_location ON pois USING GIST (location);
CREATE INDEX idx_pois_city ON pois (city);

CREATE TABLE itineraries (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  cities TEXT[] NOT NULL,              -- 单城也存数组：['东京']
  title VARCHAR(200),
  version INT NOT NULL DEFAULT 1,      -- 每次重排 +1，挂在行程级
  status VARCHAR(20) DEFAULT 'draft',
  execution_log JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE itinerary_days (
  id UUID PRIMARY KEY,
  itinerary_id UUID REFERENCES itineraries(id),
  day INT NOT NULL,
  base_city VARCHAR(50) NOT NULL,      -- 当晚住宿城市；单城=该城市
  UNIQUE(itinerary_id, day)
);

CREATE TABLE intercity_transfers (     -- W1-2 建空表 + 约束
  id UUID PRIMARY KEY,
  itinerary_id UUID REFERENCES itineraries(id),
  day INT NOT NULL,
  from_city VARCHAR(50), to_city VARCHAR(50),
  mode VARCHAR(20),                    -- train/flight/bus
  UNIQUE(itinerary_id, day)            -- 一天限一次跨城
);

CREATE TABLE itinerary_items (
  id UUID PRIMARY KEY,
  itinerary_id UUID REFERENCES itineraries(id),
  day INT NOT NULL,                    -- 挂 day
  poi_id UUID REFERENCES pois(id),
  position FLOAT NOT NULL,             -- fractional indexing
  start_time TIME, end_time TIME,
  draft BOOLEAN DEFAULT TRUE,
  sync_status BOOLEAN DEFAULT FALSE
);

-- 其他：itinerary_members（协作预留，二期启用功能）
-- poi_hours_raw · extraction_logs · agent_traces · user_interests · user_visited
```

**关键决策**：不做"单城特殊路径"——写入第一天就经过 `itinerary_days`（一天一条，base_city = 该城市）；`cities` 即使是单城也存数组，W9 读取端零改动。

---

## §5 移动端

- 六页：聊天页 · 地图页 · 时间线页（天主轴 Day1/Day2…，跨城交通 = 日内特殊卡片）· 收藏页 · 足迹页 · 执行模式页。
- **离线 = 执行模式生存底线**：行程 + 瓦片 + 讲解文案预下载到本地（drift）。
  - 离线包预算 ≤150MB：瓦片只下行程路线 2km 走廊；讲解文案离线、音频 TTS 走在线。
- 离线场景优先级：

| 场景 | 优先级 | 实现 |
|---|---|---|
| 行程查看 | ⭐⭐⭐⭐⭐ | 本地 SQLite（drift） |
| 到点提醒/打卡 | ⭐⭐⭐⭐⭐ | flutter_local_notifications（行程确认时一次性注册） |
| 导航/打车 | ⭐⭐⭐⭐ | deeplink 降级链：高德 → 滴滴英文版 → Apple Maps（外国人可能没装高德，降级链一期必做） |
| 重排/对话 | ⭐⭐⭐ | WebSocket（需网络） |

### §5.4 同步机制（version 全量覆盖，不做增量合并）

- `itineraries.version` 每次重排 +1；本地 drift 存 `sync_state(itinerary_id, last_version)`。
- 触发时机两处：**App 前台激活时 + 收到 WS 重排推送时**，本地 version 落后即拉全量覆盖当日及之后的天数。
- 一天几十个条目，全量覆盖毫秒级——增量冲突处理是深坑，明确不做。

---

## §6 Agent 设计

### §6.1–6.3 规划状态机 + 工具循环 + 增量 diff

- 会话状态存 Redis；LLM 工具循环（structured output，JSON Schema 约束）。
- diff 输出：只输出变更操作 `[{op:"move", item_id, new_time}]`，不全量重输出行程。
- 澄清维度含多城（W1-2 先做单城澄清）。
- W1-2 工具集（单城）：`search_pois` / `get_poi_details` / `estimate_travel_time` / `check_opening_hours` / `get_weather`。跨城工具（`search_intercity_routes` / `pacing`）W9 挂载。

### §6.4 硬校验铁律（纯 Python 校验函数，不打 prompt 补丁；失败打回 LLM 自修）

1. 时间冲突 ｜ 2. 营业时间校验 ｜ 3. 地理自洽 ｜ 4. 跨城衔接缓冲 ｜ 5. 一天一跨城 ｜ 6. 节奏合理性 ｜ 7. 交通可达 ｜ 8. 3 秒延迟预算 ｜ 9. 重排带 reasoning ｜ 10. 只动当天及之后 ｜ 11. **执行模式不动过去（生成端）** ｜ 12. **同步端不覆盖过去（同步端）** —— 11/12 成对，杜绝本地足迹与服务端记录不一致。

### §6.5 链接解析三刀分期

文字 → 图文 → 视频；粗筛 → 精读 → 确认卡片 → 分级报错 → 成本闸门。POI 匹配走高德 POI 搜索 + 城市上下文，置信度 < 0.8 进"待确认"，不硬猜。

### §6.6 成本闸门

- 对话成本闸门：Redis 计数，按用户/行程限额。
- 讲解生成管线**按 POI 缓存复用**（同 POI 不重复生成，按语言/时长档位缓存），行程确认时批量生成。

### §6.7 执行模式 Agent（双边付费核心）

- 三形态：定时推送（纯本地，离线）/ 主动问（重排，需网络）/ 到点讲（文案预下载，离线）。
- 六工具：get_weather / get_remaining_plan / propose_replan / narrate_poi / search_pois / estimate_travel_time。
- `propose_replan` = 规划 Agent 受限子调用，输出走 diff + 硬校验。
- 三场景状态机：时间落后 / 天气突变 / 到点讲解；ExecutionResponse schema 约束输出。
- 天气突变形态依赖 Push：Firebase 境内到达率需实测（P0），不达标降级为 App 前台轮询。

---

## §7 评估体系

- 国内用户是抽取评估集首批来源；`execution_log` 是付费价值评估集。
- 每轮 Agent 交互（messages + tool_calls）原样落 `agent_traces`。
- 北极星指标：**执行模式周留存**；过程指标：规划→确认转化率、执行首日付费转化率、重排采纳率、离线可用率。

---

## §8 数据管线

- 每日 02:00 (UTC+8)：多源采集 + 仲裁引擎；源 D = 头部 POI 官网公告，T-30 抓节假日例外。
- 变更检测三层：ETag + 哈希 + LLM。
- 班次静态库：周级刷新，**只读展示**，标注"班次仅供参考"；购票永远跳 12306 官方 App deeplink（查询与交易分离，法律风险收敛在数据准确性）。
- `TrainService` 抽象层：一期实现指向 deeplink + 静态库，二期可切授权第三方数据源，业务代码不耦合。
- 车站 → `transport_hub` POI 入双语库；讲解生成管线：行程确认时批量生成 + 预下载。

---

## §9 路线图

| 周次 | 内容 |
|---|---|
| **W1-2** | 单城最小闭环：粘贴 → 抽取 → POI 匹配（置信度）→ 确认卡片 → 入库。建表含 PostGIS 索引 + 三张行程表全建 + version + cities 数组 + 写入走 itinerary_days。匿名 device_id，不做登录。**同步埋高德调用量日志（日期/端点/次数/region/scene）** |
| W3-4 | 规划 Agent 单城 + 硬校验函数集 + 四适配器接口与 mock |
| W5-6 | 多源时间仲裁 + 双语 POI + 时间线页 |
| W7-8 | 国内登录 + LLM 路由（LiteLLM）+ WS 流式联调；单城闭环可用 |
| W9-10 | 执行模式 A/C 形态（纯本地）+ 离线包 + 多城静态版（解锁跨城工具） |
| W11+ | 重排 Agent + 讲解管线；国内资质办妥后上国内商店 |
| 二期 | 误车跨天重排、实时排队、协作规划（itinerary_members）、微信小程序（需生成式 AI 备案，另议） |

---

## §10 风险清单

| 风险 | 等级 | 对策 |
|---|---|---|
| 境内 WS 流式实测 | P0 | W7-8 前实测，不过则退 SSE |
| Firebase 境内到达率 | P0 | 实测，不达标则天气突变形态降级前台轮询 |
| 高德海外链路延迟（新加坡服务端帮境内用户查路径跨境回源） | P0 | W1-2 实测，与调用量基线数据合并评估 |
| 高德商用政策变动 | 中 | 书面确认留痕 + 用量基线作谈判筹码；企业认证 Key 开发期即用 |
| 12306 数据源稳定性 | 中 | 静态库只读展示 + deeplink 交易分离 |
| 双主体决策 | 中 | W7 前完成，否则阻塞国内联调 |
| App 备案周期 1–3 个月 | 中 | 本周启动，与开发并行 |

---

## §11 下一步动作（本周）

1. ⚖️ 国内公司注册 + 备案材料准备（并行，不阻塞开发）。
2. ⚖️ 高德企业认证 + 勾选海外访问权限 + **书面确认计费政策**（工单/邮件留痕）。
3. 🔨 W1-2 开工：FastAPI 骨架 + `/extract` + 建表（PostGIS + 三张行程表 + version）+ 高德调用量日志埋点。

---

## §变更记录

| 版本 | 变更 | 影响 |
|---|---|---|
| v1.3 | 铁律 12 + version 全量覆盖同步；数据模型多城一次到位（cities 数组 / transfers 空表约束先立）；免费额度改每行程 1 次；12306 deeplink 定案 + TrainService 抽象；高德企业 Key + 书面确认 + 用量埋点；PostGIS 前置 W1-2；打车 deeplink 降级链；IAP 小企业计划 | §1.3 / §2 / §3.3 / §4 / §5.4 / §6.4 / §8 / §9 / §10 |
| v1.2 | 多城模型、执行模式 Agent、商业模式、离线底线 | 全文 |
