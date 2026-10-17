# Travel Agent App — 系统设计文档

> 版本：v1.0 ｜ 日期：2026-10-17
> 一句话定位：**外国人在海外规划中国旅行，入境后无缝切换为导航 + 打车助手的 AI 行程规划 App**

---

## 1. 产品概述

### 1.1 核心场景闭环

```
【人在海外】
打开 App → 邮箱登录 → 对话："我打算在上海玩3天"
→ agent 澄清偏好 → 生成双语行程 → 地图+时间线预览
→ 粘贴小红书链接 → 抽取景点 → 确认收藏

【落地中国】
App 检测定位在中国 → 高德定位实时显示
→ "去这里" → deeplink 高德 App 导航
→ "打车去" → deeplink 高德打车（已引导绑定支付宝国际卡）
→ 打卡景点 → 写入"去过的地方"

【回国后】
行程自动生成游记草稿 → 分享（带拉新链接）
```

### 1.2 与同类产品的差异

| 差异点 | 说明 |
|---|---|
| 双语 POI 数据资产 | 自建中英文景点库，外国人看得懂（高德/Google 都给不全） |
| agent 生成 + 手动微调 | 对话改规划 + 地图拖拽编辑双向同步，不是静态攻略 |
| 贴链接收藏 | 小红书/TikTok 链接 → 抽取景点 → 一键进兴趣库 |
| 跨境无缝 | 海外规划、入境导航打车，一套账号全球可用 |

---

## 2. 技术选型总览

| 层 | 选型 | 理由 |
|---|---|---|
| 跨平台框架 | **Flutter（Dart）** | 一套代码出 iOS+Android，未来可扩桌面端；地图自绘引擎性能优于 RN 桥接模式 |
| 地图 SDK | **高德（官方 Flutter 插件）** | 核心场景是中国境内景点，Google Maps 在国内数据差且有 GCJ-02 偏移 |
| 后端 | **Python (FastAPI)** | 与 agent 生态（LangChain/LlamaIndex）契合；开发者熟练 |
| 数据库 | **PostgreSQL + PostGIS** | 结构化用户数据 + 地理查询 + 未来 pgvector 扩展 |
| 主 LLM | Claude / GPT-4o（开发期） | 开发期用最强模型保证体验；量产评估 Qwen-VL 等降本 |
| 部署 | 海外云（AWS 新加坡/东京）+ 国内加速 | 海外用户访问快；国内用户走优化线路 |

### 2.1 已排除的选项（决策记录）

- ~~知识库插件（Obsidian 等）~~：用户兴趣/足迹是结构化数据，关系型数据库即可；知识库只在未来做攻略 RAG 时用 pgvector 解决
- ~~微信小程序~~：目标用户是外国人，无小程序生态
- ~~Web App 起步~~：产品形态已明确为独立 App，且地图重交互需要原生体验
- ~~React Native~~：复杂地图（满屏 marker + 路线 + 拖拽编辑）桥接性能是已知坑
- ~~Google Maps~~：中国境内数据不准 + GCJ-02 偏移

---

## 3. 系统架构

![系统架构图](architecture_diagram.png)

```
┌────────────────────────────────────────────────────────────┐
│  Flutter App（iOS + Android，海外应用商店分发）                │
│  ├── 聊天页（对话规划/修改行程，流式输出）                      │
│  ├── 地图页（高德底图 + 自建双语POI图层 + 行程路线）           │
│  ├── 时间线页（每日行程卡片，拖拽排序，与地图联动）             │
│  ├── 收藏页（贴链接/粘贴文字 → 抽取 → 确认 → 入库）            │
│  ├── 足迹页（去过 / 想去，分开管理）                           │
│  └── 本地缓存（行程 + 离线地图，断网可用）                     │
└──────────────────────┬─────────────────────────────────────┘
                       │ HTTPS + WebSocket（流式）
┌──────────────────────▼─────────────────────────────────────┐
│  Python FastAPI 后端（部署海外 + 国内加速）                    │
│  ├── Agent 编排层（见 §6：规划状态机 + 工具调用）               │
│  ├── 链接解析服务（§7：文本/图文/视频抽取流水线）               │
│  ├── 数据管线（§8：营业时间每日刷新仲裁）                       │
│  └── 高德 API 封装（定位/路径规划/POI搜索，服务端调用）         │
└──────────────────────┬─────────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────────┐
│  PostgreSQL + PostGIS                                        │
│  ├── users / user_interests（兴趣）/ user_visited（去过）     │
│  ├── pois（双语POI库：name_zh/name_en/坐标/类别/营业时间）    │
│  ├── itineraries / itinerary_items（行程）                   │
│  ├── poi_hours_raw（多源原始数据，留档可重仲裁）               │
│  └── extraction_logs（链接抽取记录，评估集来源）               │
└────────────────────────────────────────────────────────────┘
```

### 3.1 跨境可用性设计（重点）

| 项 | 方案 | 说明 |
|---|---|---|
| 后端部署 | 主服务海外 + 全球加速 | 国内直访海外服务不稳定，需 CDN/加速线路；二期可做国内镜像双区 |
| **登录体系** | **邮箱验证码为主 + Apple 登录补充** | ⚠️ 严禁依赖 Google OAuth / Firebase：用户入境中国后这些服务不可用，会登不上自己的账号 |
| 游客模式 | 规划功能免登录可用 | 登录只为同步收藏/行程；即使入境后登录异常，本地数据不丢 |
| 中国区上架 | 暂缓（需 ICP 备案主体） | 一期只上海外 App Store / Google Play |
| 高德 SDK | 海外用户手机可用 | 与手机国籍/SIM 无关，人在中国即正常定位 |

### 3.2 导航与打车（分期实现）

| 阶段 | 方式 | 说明 |
|---|---|---|
| 一期 | **deeplink 跳转高德 App**（`androidamap://` / `iosamap://`，传坐标） | 零 SDK 集成成本，导航体验是满分的高德原生体验 |
| 二期 | 应用内集成高德导航 SDK | 需 Platform Channel（Kotlin/Swift）调原生能力 |
| 打车一期 | **deeplink 到高德打车页**（传目的地坐标） | 支付走用户自己的支付宝（需 onboarding 引导绑定国际卡） |
| 打车二期 | 申请高德打车企业 API，应用内闭环叫车 | 需企业资质审核 |

外国用户支付链路提醒：支付宝 2024 年起支持绑定国际信用卡（Visa/Mastercard），产品内需有"出发前准备"引导流程（绑卡、国际漫游/临时 SIM）。

---

## 4. 数据库设计（核心表）

```sql
-- ========== 用户与偏好 ==========
CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text UNIQUE NOT NULL,
    locale        text DEFAULT 'en',           -- en/zh/ja/...
    created_at    timestamp DEFAULT now()
);

-- 兴趣点（想去的）：贴链接抽取 + 对话中收藏 + 手动添加
CREATE TABLE user_interests (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid REFERENCES users(id),
    poi_id      int REFERENCES pois(id),       -- 挂标准POI；未匹配上可空
    raw_name    text,                          -- 抽取原文（如"巷子里那家咖啡馆"）
    source      text,                          -- 'link' | 'chat' | 'manual'
    source_url  text,                          -- 来源链接（溯源）
    status      text DEFAULT 'active',         -- active / visited / removed
    created_at  timestamp DEFAULT now()
);

-- 去过的地方：打卡写入
CREATE TABLE user_visited (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid REFERENCES users(id),
    poi_id      int REFERENCES pois(id),
    rating      smallint,                      -- 1-5，可选
    note        text,
    visited_at  date,
    UNIQUE(user_id, poi_id)
);

-- ========== 核心资产：双语 POI 库 ==========
CREATE TABLE pois (
    id           serial PRIMARY KEY,
    name_zh      text NOT NULL,
    name_en      text,                          -- 缺失=待完善（热门景点优先补）
    aliases      jsonb DEFAULT '[]',           -- 别名：["苏博","Suzhou Museum"]
    category     text,                          -- landmark/food/museum/nature/...
    city         text,
    location     geography(Point, 4326),
    coord_sys    text DEFAULT 'gcj02',         -- 统一火星坐标系，禁止混用WGS-84
    recommended_duration_min int,               -- 建议游玩时长
    popularity   int DEFAULT 0,
    -- 营业时间（每日管线仲裁后写入，见 §8）
    opening_hours  jsonb,                      -- {"mon":"09:00-17:00","exceptions":{"2026-10-01":"closed"}}
    oh_source      text,                       -- 'amap' | 'osm' | 'user_report'
    oh_confidence  text,                       -- high/medium/low
    oh_updated_at  timestamp,
    status         text DEFAULT 'open',        -- open/closed/seasonal/draft
    created_at     timestamp DEFAULT now()
);
CREATE INDEX ON pois USING GIST(location);
CREATE INDEX ON pois (city, category);

-- ========== 行程 ==========
CREATE TABLE itineraries (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid REFERENCES users(id),
    destination text,
    start_date  date,
    days        int,
    status      text DEFAULT 'draft',          -- draft/active/completed
    created_at  timestamp DEFAULT now()
);

CREATE TABLE itinerary_items (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    itinerary_id uuid REFERENCES itineraries(id),
    day          int,
    poi_id       int REFERENCES pois(id),
    start_time   time,
    duration_min int,
    note         text,
    sort_order   int,
    UNIQUE(itinerary_id, day, sort_order)
);

-- ========== 数据管线（§8）==========
CREATE TABLE poi_hours_raw (
    poi_id     int REFERENCES pois(id),
    source     text,
    raw_value  jsonb,
    fetched_at timestamp DEFAULT now(),
    PRIMARY KEY (poi_id, source, fetched_at)
);

-- ========== 抽取评估（§7）==========
CREATE TABLE extraction_logs (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid REFERENCES users(id),
    input_type   text,          -- 'text' | 'link' | 'video'
    input_raw    text,
    extracted    jsonb,         -- LLM输出
    confirmed    jsonb,         -- 用户最终确认结果
    created_at   timestamp DEFAULT now()
);
```

---

## 5. Flutter App 模块

### 5.1 页面清单

| 页面 | 核心交互 |
|---|---|
| 聊天页 | 对话生成/修改行程；流式展示 agent reasoning |
| 地图页 | 高德底图 + POI marker 图层 + 行程路线 polyline；点卡片地图飞点联动 |
| 时间线页 | 每日行程卡片；拖拽重排；与地图双向同步 |
| 收藏页 | 粘贴链接/文字 → 抽取候选 → 确认卡片（高置信预勾选） |
| 足迹页 | 去过/想去分栏；打卡写入 |
| 行程编辑态 | 用户任何修改 → 增量 diff 回传 agent（"agent 记得我的操作"的体感来源） |

### 5.2 关键工程点

- **离线缓存**：当日行程 + 地图瓦片预下载（SQLCipher/SQLite），景点现场弱网可查看
- **地图代码抽象层**：地图调用封装在统一接口后，未来换实现/加国内版地图只改一处
- **检测定位在中国 → 自动切换为"旅行模式"**（导航/打车按钮激活）

---

## 6. Agent 设计（系统核心）

### 6.1 心智模型：带状态机的 agent 循环

LLM 只做"生成/修改决策"一环；检索、校验、状态管理都是代码。
LLM 是"交易员"，代码是"风控和交易所"。

```
接收输入（用户说话/拖拽地图/点收藏）
  → 理解意图（新规划 / 改现有 / 问答）
  → 信息不足？→ 澄清反问（≤3个问题，可点选选项）
  → 检索候选POI（代码从库查，LLM不可见库外景点 → 结构上消灭幻觉）
  → agent 工具循环（选点 → 查营业时间 → 算交通时间 → 排时间）
  → 代码硬校验（时间重叠/ID合法/营业检查）
  → 展示 + 等待反馈（用户改 → 回到"理解意图"）
```

### 6.2 上下文组装器（Context Builder）

```python
def build_context(user_id, user_message, current_itinerary):
    return {
        "user_profile": {
            "interests": get_user_interests(user_id),
            "visited": get_visited_places(user_id),   # 去过且低分→排除
            "pace": "relaxed",
        },
        "poi_candidates": search_pois(city, categories, limit=50,
                                      exclude_visited=True),  # 硬规则否决
        "current_itinerary": current_itinerary,
    }
```

### 6.3 工具集

| 工具 | 实现 | 原则 |
|---|---|---|
| `search_pois` | POI 库检索 | 候选集的唯一来源 |
| `get_poi_detail` | 读库 | 营业时长/门票 |
| `check_opening_hours` | **读库**（管线每日刷新，见 §8） | LLM 不脑补营业时间 |
| `estimate_travel_time` | 高德路径规划 API（服务端） | LLM 对"外滩到豫园多久"的估计经常离谱，必须调工具 |
| `create_itinerary` / `update_itinerary` | 写库 | update 只输出 diff |

### 6.4 系统 Prompt 铁律（要点）

1. 所有地点必须来自候选列表并引用 poi_id；库外景点禁止出现
2. 同一天时间不重叠；相邻点用 estimate_travel_time 验证可行性（预留 30% 缓冲）
3. 必须调用 check_opening_hours（含节假日 exceptions）
4. 信息不足时一次提 ≤3 个澄清问题，选项可点选
5. **增量修改只输出 changed_fields，禁止重发完整行程**

### 6.5 输出 Schema（结构化输出强制）

```python
class ItineraryItem(BaseModel):
    poi_id: int                     # 必须来自候选集
    start_time: str                 # "09:00"
    duration_min: int
    note: str                       # agent 自由发挥（随用户语言）
    travel_to_next_min: int | None  # 工具计算

class DayPlan(BaseModel):
    day: int
    theme: str
    items: list[ItineraryItem]

class AgentResponse(BaseModel):
    action: Literal["clarify", "create", "update", "chat"]   # 驱动前端渲染什么
    questions: list[str] | None
    options: list[list[str]] | None
    itinerary: list[DayPlan] | None
    changed_fields: dict | None     # 增量 diff
    reasoning: str                  # "考虑到你提过膝盖不好……"
```

### 6.6 Agent 主循环骨架

```python
class PlanningAgent:
    async def handle(self, user_id, message, itinerary_id):
        ctx = build_context(user_id, message, itinerary_id)
        messages = [SystemMessage(SYSTEM_PROMPT),
                    HumanMessage(json.dumps(ctx) + "\n\n用户说：" + message)]
        for _ in range(10):                      # 防死循环上限
            resp = await self.llm.ainvoke(messages, tools=self.tool_schemas,
                                          response_format=AgentResponse)
            if resp.tool_calls:
                results = [await self.execute_tool(c) for c in resp.tool_calls]
                messages += [resp, *results]
            else:
                parsed = AgentResponse.model_validate(resp.content)
                self.validate(parsed, ctx)       # 代码硬校验，不过不生效
                if parsed.action in ("create", "update"):
                    self.persist(parsed, itinerary_id)
                return parsed
```

---

## 7. 链接抽取功能（贴链接/文字 → 收藏景点）

### 7.1 分期流水线

```
第一刀：粘贴文字 → LLM 抽取 → 确认卡片 → 入库（一周可完成）
第二刀：+ 图文（抓图床 + Referer 伪装 + 粗筛精读）
第三刀：+ 短视频（yt-dlp 下载 + Whisper 转录 + 抽帧 + 多模态）
```

### 7.2 各源处理

| 来源 | 做法 | 备注 |
|---|---|---|
| 分享文本 | 用户复制小红书分享文本（自带标题+正文） | 首选，零反爬 |
| 图文链接 | trafilatura 提取正文；图床 URL 解析（伪造 Referer 取原图） | 原图对 OCR 至关重要 |
| TikTok | yt-dlp 下载 → ffmpeg 抽帧（3-5s/帧）+ whisper-large-v3 本地转录 | 多数 vlog 口播信息密度高，转录稿够就只走文本链路 |

### 7.3 多模态精读策略（省钱关键）

```
全部图片 → 粗筛（低清批量问"有店招/路牌/门票吗？"，快模型）
        → 选 2-3 张信息图 + 正文 → 精读（强模型，图文交叉验证）
```

### 7.4 确认卡片（功能灵魂）

- 每个候选**必须带原文上下文**（"这家咖啡馆"→ 显示原文句子，用户自己认得）
- 高置信预勾选，低置信标注原因（"原文未提名字"）
- 宁可少抽不可错抽；识别不出如实说，不硬猜
- 确认即写 `user_interests`，挂标准 poi_id（匹配不上的建 draft POI）

### 7.5 分级报错（信任基石）

```
"链接打不开，请复制文字给我"          ← 抓取失败
"只解析了文字部分，图取不出来"        ← 部分成功
"这篇内容没找到明确地点"              ← 抽取为空
```

### 7.6 成本闸门

- 每用户每日免费解析 N 次（如 5 次）
- 短视频 >60s 先转录，信息够则跳过画面分析
- 抽取失败案例全部入 `extraction_logs`，攒 200-300 例建评估集，按失败分类迭代

---

## 8. 数据管线：营业时间每日刷新（预计算 + 版本化）

### 8.1 原则

实时查询 → 每日凌晨批量刷新、多源仲裁后写库，agent 查询只读库。
快（毫秒级）、稳（API 挂了不影响线上）、可仲裁（冲突在管线解决一次）、可追溯（来源+时间戳）。

### 8.2 流水线

```
Stage 1 调度：凌晨 2:00，APScheduler（coalesce=True, max_instances=1）
Stage 2 多源采集（信号量限流 10 并发）：
        源A 高德 POI 详情（主源）/ 源B OSM（补充长尾）/ 源C 用户报错（人工审核）
Stage 3 仲裁引擎：
        1. A 存在 → 采信 A
        2. A 缺失 B 存在 → 用 B，置信度 medium
        3. A/B 冲突 → 取 fetched_at 较新者，记冲突日志
        4. 用户反馈"关门"≥2 人 → 覆盖一切源，status=closed
        5. 连续 7 天全源缺失 → stale，agent 提示"建议出发前电话确认"
Stage 4 写 pois 表（opening_hours/oh_source/oh_confidence/oh_updated_at）
        原始数据存 poi_hours_raw（保留每源原始值，可重仲裁）
Stage 5 agent 端 check_opening_hours 改为纯读库；低置信度在 note 中提示
```

### 8.3 实务要点

- **增量刷新**：只刷活跃行程城市 + 热度 Top N；冷门 POI 被规划到时按需刷一次并写库
- **节假日 exceptions 单独处理**：国庆/春节营业特殊，这是"最正确答案"与普通答案的分水岭
- **用户反馈闭环**：App 内一键报错 → 审核队列 → 通过后覆盖
- **监控日报**：`刷新3120个POI | A源2890 | B源补充180 | 冲突45 | 连续缺失5`，冲突数突增=某源异常，报警

---

## 9. 开发路线图

| 阶段 | 内容 | 验证目标 |
|---|---|---|
| **W1-2** | 最小闭环：粘贴文字→抽取→确认→入库；Flutter 骨架（聊天+时间线） | 核心交互成立 |
| **W3-4** | agent 切片A："上海3天"→澄清→生成 JSON→渲染；POI 库建库（首批 10 城市×300 景点，LLM 翻译+校对） | 核心价值：能生成行程 |
| **W5-6** | 地图接入（高德+POI图层）、增量修改对话（"第二天太满"） | 地图联动 + 多轮体感 |
| **W7-8** | 兴趣库/去过参与生成；链接解析（图文）；营业时间管线 v1 | 数据飞轮启动 |
| **W9-10** | 定位检测→deeplink 导航/打车；支付宝绑卡引导；离线缓存 | 入境场景闭环 |
| **W11+** | TikTok 视频抽取；应用内导航 SDK；评估集驱动迭代 | 体验打磨 |

原则：每个切片都可演示、可验证，拒绝"做三个月什么都没有"。

---

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| Google 系服务入境失效 | 登录/推送/统计全部选中国可用方案（邮箱、APNs） |
| 高德 Flutter 导航插件生态弱 | 一期 deeplink 交付，二期 Platform Channel |
| 小红书/TikTok 反爬与 ToS | 只做"用户主动粘贴"形态；不主动爬；量大了走官方 API |
| 外国人支付/手机号门槛 | onboarding 引导（支付宝绑国际卡、漫游/eSIM） |
| LLM 幻觉编造景点 | 候选集硬约束 + 代码校验 + 只从库选 ID，结构防幻觉 |
| 多源营业时间冲突 | 仲裁规则 + 冲突日志 + 原始数据留档可重算 |
| 海外主体中国区上架 | 暂缓，需公司主体 + ICP |

---

## 附录 A：坐标系统一纪律

- 全部数据统一 **GCJ-02**（高德标准），入库即转换
- OSM/Google 数据为 WGS-84，直接叠高德底图偏移数百米，必须转换后入库
- `pois.coord_sys` 字段标记来源坐标系，转换函数集中在数据入口

## 附录 B：双语 POI 库建设

- 首批：10 热门城市 × 200-500 核心景点，几千条
- 英文名来源：OSM 现成数据 → LLM 批量翻译兜底 → 热门人工校对
- 库外景点（用户提到/抽取到）：建 draft 状态，后续补全
- 该库是永久核心资产，竞品难以低成本复制
