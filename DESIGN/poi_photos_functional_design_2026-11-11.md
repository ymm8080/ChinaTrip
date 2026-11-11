# POI 照片功能设计（FUNCTIONAL DESIGN）2026-11-11

> 状态：**待拍板**。需求缘起：行程卡站点点出简介气泡后，用户想"看相关图片"。
> 2026-11-11 路线拍板（用户口头）：**库里存照片 URL（不存二进制）+ 点击懒加载；
> 库空时点击触发回源拉取；AI 搜索只做最末兜底**。本文是落地设计。

---

## 1. 现状盘点（全部实测，2026-11-11）

| 层 | 事实 | 证据 |
|---|---|---|
| 库表 | `pois.photos` JSONB（`[{title,url}]`）+ `photos_source` 已有；`restaurants` 同构 | app/models.py:89-90, 182-183 |
| 写入管道 | wikimedia P18（backfill_intro）/ 高德 v5 place/detail（enrich_amap_detail）/ 携程详情 HTML（enrich_ctrip_detail）/ 百度（baidu_client）/ refresh_pois 合并路径——**全部"只填空"** | app/jobs/backfill_intro.py, enrich_amap_detail.py:76-78, enrich_ctrip_detail.py:125 |
| 读侧 API | `/api/pois/detail` 已透出 `photos` + `photos_source` | app/api/pois.py:68-69, 114-115, 212-213 |
| H5 | 简介气泡（enrichBrief）**只渲染第一张图**（max-height 140px，onerror 摘除）；悬停 .site-pop 无图 | app/static/index.html:2256-2276, 2281-2360 |
| 覆盖率 | **active 9,787 行，有非空 photos 仅 1,650（16.9%）**；其中 photos_source 为 NULL 的 1,449、wikimedia 201；**restaurants 覆盖为 0** | 活库 Docker chinatripcodes-db-1 实测探针 |

**盘点结论：存读链路已通，缺的是①多图查看（画廊）②空图点的点击回源 ③来源标注漏洞。**

### 1.1 顺手发现的既有漏洞（登记台账，不在本设计内静默修）

- `enrich_amap_detail.py:76-78` 填 `photos` 但不写 `photos_source` → 1,449 行来源悬空（另有 opening_hours 同函数写了 hours_source="amap"，口径不一致）。修法一句话：补 `row.photos_source = "amap"`，连同历史行 UPDATE。归本设计 F5 一并收口。
- `backfill_intro.py:24-27` 头注"AmapClient 现有方法均不透出 photos"已过时——enrich_amap_detail 后经 place_hours 拿到了 photos（同一客户端）。头注应删改。

---

## 2. 核心决策：三路分层，AI 搜索排最后

| 优先级 | 路径 | 时机 | 成本/延迟 |
|---|---|---|---|
| P0 | **库内 URL 直读**：画廊渲染已有 photos | 点击站点即得（已随 detail 接口到达前端） | 零外呼，秒开 |
| P1 | **点击触发确定性回源**：库空 → 后端按源优先级现拉现写回 | 用户点"找图"（或画廊空态自动一次） | 1-2s，只烧高德/百度配额 |
| P2 | **AI 搜索兜底**：确定性源全空才允许，用户显式点"AI 找图" | 显式触发 | 慢车道异步，烧 LLM token |

**为什么 AI 搜索不能当主路径**：①延迟几秒，泡在手机上看图等不起；②结果不可控（错图/张冠李戴），照片正确性没有校验手段；③每次点击烧钱；④**coding 端点 web_search 2026-10-25 实测静默忽略**（enrich_llm_web.py 头注，该 job 至今挂"暂勿排期"）——AI 找图的能力底座还没通，只能做预留开关。

---

## 3. 功能设计

### F1 画廊灯箱（H5，读侧纯前端）

- 简介气泡首图保持现状轻量；**点击首图（或照片计数"📷 N"）开全屏灯箱**：横滑/点切全部 photos，底部来源小字（复用 `brief.sourcePre/Close` 口径与 `photos_source`）。
- 键位/手势：左右箭头等价 swipe；Esc/点遮罩关闭；EN 语境来源标签不翻译（source 戳原样）。
- 悬停 .site-pop 仍不出图（流量与骚扰控制），点击气泡才出图。
- 图源是第三方 URL 直链（referrerpolicy="no-referrer"，防盗链兜底——高德/百度图床对空 referrer 策略不一，需 UAT 实测）。
- 空态：photos 为空时不显示灯箱入口，改显 F2 的"🔍 找图"按钮。

### F2 点击触发确定性回源（后端新端点）

- `POST /api/pois/photos/fetch`，入参 `{city, name}`（与 detail 端点同键），鉴权口径同 `/api/pois/detail`。
- 服务端行为（幂等）：
  1. 查行；`photos` 非空 → 直接返回（冷却内不重复外呼）。
  2. 空 → 按源优先级现拉：**amap_id → 高德 v5 place/detail（client.place_hours 已回 photos）→ 百度 uid → wikimedia P18**，首个非空命中即停。
  3. **只填空写库**（沿用回填铁律）：`photos` + `photos_source` + `photos_fetched_at`；拉不到不写字段，返回空列表。
- 冷却：同一 poi 24h 内重复请求直接回库值，防连续点击烧配额。冷却键落 `photos_fetched_at`（F4 新列）。
- 响应：`{photos, photos_source, fetched: bool}`；失败/异常**必须留日志**（用户 10-25 立规：静默吞掉不允许），响应里不吐错误细节给前端。
- 批量预热（非点击路径，同期施工）：`python -m app.jobs.backfill_photos [--limit N] [--city X]`——active + 有 amap_id/百度 uid 优先 + rating 降序（复用 enrich_amap_detail 的选行骨架与源优先级常量），把覆盖率从 16.9% 先抬一档；点击回源兜剩下的长尾。

### F3 AI 搜索兜底（P2，能力闸默认关）

- 仅当 F2 确定性源全空，且用户显式点"AI 找图"，才走 LLM+web_search：查询词 = `{name_zh} {city} 景点 图片`（EN 语境 `{name_en} {city} images`），模型返回候选图 URL 数组，服务端逐条 HEAD 验活（200 + content-type image/*）后入库，**来源标 `llm_web`**。
- **能力闸 `_PHOTO_AI_ENABLED = False`**，coding 端点 web_search 实装前不得打开（enrich_llm_web.py 同闸先例）。打开前必须补：URL 域白名单（防脏链）、与主规划器共用账户的 429 退避（同 enrich_llm_web 骨架）。
- 每 poi 冷却 7 天 + 失败 2 次后永不主动再试（落 `photos_fetch_fail`）。

### F4 失效处理与刷新

- 新列（migration，pois/restaurants 同构各两条）：`photos_fetched_at TIMESTAMP NULL`、`photos_fetch_fail INT NOT NULL DEFAULT 0`。
- 前端 onerror 不再静默摘除：灯箱/首图加载失败 → 上报 `POST /api/pois/photos/report-dead {poi_id}`（fire-and-forget，失败不阻塞用户），服务端 `photos_fetch_fail += 1`。
- 日/周 job（挂在现有 refresh 管线同节奏，一行一月原则内）：`photos_fetch_fail >= 3` 或 `photos_fetched_at` 超 30 天 → 按 F2 链重拉**整组替换**（替换前必须新源非空；这是 photos 字段首个"非只填空"写语义，拍板点在此——建议替换+留 source/fetched_at 戳，不做历史快照，YAGNI）。
- 已知风险：第三方图床 URL 会漂移，30 天窗口是拍板值，UAT 后按失效率高低调。

### F5 来源标注收口

- enrich_amap_detail 补写 `photos_source='amap'`（新行），历史 1,449 行 `photos_source IS NULL AND photos IS NOT NULL` 一次性 UPDATE 标 `amap`（这批即 amap 管道所填——先抽 20 行人工核 URL 域名再批量，防误标）。
- backfill_intro 过时头注删改（§1.1）。
- H5 来源小字口径与 intro/review_summary 完全一致（`（来源：xxx）`）。

---

## 4. 数据契约

- `photos`：`[{"title": str, "url": str}]`，≤8 条，url 必须 http(s) 绝对地址；写库前逐条 HEAD 验活（F3 必做；F2 高德/百度回源为厂商直出 URL，免 HEAD 但保留 url 非空校验，沿用 `_normalize_photos`）。
- `photos_source` 枚举：`wikimedia | amap | ctrip | baidu | llm_web`。
- 二进制/转存/用户上传：**全部不做**（版权+存储成本，拍板点）。

## 5. API 面汇总

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/pois/detail` | GET | 不变（已透 photos） |
| `/api/pois/photos/fetch` | POST | F2 点击回源，24h 冷却，幂等 |
| `/api/pois/photos/report-dead` | POST | F4 死图上报，fire-and-forget |
| `app.jobs.backfill_photos` | job | F2 批量预热 |

## 6. 施工顺序与验收

1. migration（photos_fetched_at / photos_fetch_fail）→ F2 端点 + job → pytest（幂等/冷却/只填空/源优先级/死图计数）→ F1 灯箱 H5 → F5 收口。
2. F3 只施工能力闸骨架，默认关。
3. 验收：活服 H5 CDP 实测灯箱开/滑/关 + EN 语境 + 空图"找图"全流程；sw.js VERSION +1（改 shell 规矩）；回归锚：本设计不动兜底排序，无需 wedge/purity/cluster 三锚；跑全量 pytest。
4. 完成后实测覆盖率复查（目标：点击路径 100% 有响应，批量预热后 active 有图率 ≥60% 拍板待定）。

## 7. 非目标

- 不存二进制、不转存、不做用户上传/打卡照片。
- 不做图片审核/去重/质量排序（标题=图注直出）。
- restaurants 照片（当前 0 覆盖）本设计只加列，填充另案。
