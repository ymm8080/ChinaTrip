# 自助景点规划助手（暂名）ChinaTrip API (W1-2)

自助景点规划助手后端 — 设计文档 v2.5（国内区先行 · MVP 最小成本），W1-2 CN 区最小闭环起步，现处 v2.4/v2.5 行程中心 + POI 底库阶段。

- LLM = 智谱 GLM 云 API（个人 key，OpenAI 兼容端点，零 GPU 成本）。v1.9.9 拍板：MVP = 智谱云即正式路径（已备案模型，非降级）；自建 GPU/vLLM 后移至规模化阶段（W11+，量/成本阈值远程可配触发），切换 = 仅改 `GLM_BASE_URL` 与模型名，适配器零改动；`LLM_BACKEND=mock` 可完全离线开发测试
- 高德 = 个人开发者 Key，仅服务端调用，key 永不进客户端
- 匿名 device_id 单轨（无登录体系；支付/权益基建不建 —— 需公司主体，表结构保留在迁移中）
- 客户端 = Flutter 单代码库双端（Android+iOS，设计 v2.1 §5.0 原生模块契约表）；M1.5 独立工作流，待用户功能测试通过后启动——本仓 = 后端。MVP 功能测试走 `/docs`（Swagger）+ 单页 H5 冒烟，零客户端开发
- PostgreSQL + PostGIS（Alembic 迁移）
- v1.7 预埋：`pois.wgs84_location` 双坐标（境外渲染副本，Phase 2）；用量日志带 `region` 维度（`scene` 随 Phase 2 境外代理链路引入）
- v1.8 行程求解器：OR-Tools CP-SAT 管排期/排序，LLM 管理解与选点（§6.9 分工）；`ortools` 已入 requirements（MVP `solve_plan` 落地，3s 预算，失败降级 LLM 自修≤3→半成品）
- v1.9/v2.0 增量：`action_handoffs` 表（行动编排留痕 + 佣金对账，含 v1.9.4 `refund_policy`/`refund_deadline` 退改快照）；铁律扩至 0–23（21 语音本地闭环 / 22 只手off 不代客交易 / 23 退改签透明前置）；MVP 无状态横扩 + pgbouncer（万级容量基线，§6.12 ⑦）

## 开发环境

```bash
cd "CHINATRIP CODES"
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt pytest pytest-cov pytest-timeout ruff  # Windows
cp .env.example .env  # 填入 GLM_API_KEY / AMAP_API_KEY

docker compose up -d db            # PostGIS（可选，测试不需要数据库）
.venv/Scripts/python -m alembic upgrade head   # 建表全量
.venv/Scripts/python -m uvicorn app.main:app --reload
```

## 测试 / Lint

```bash
.venv/Scripts/python -m pytest --cov=app --cov-fail-under=75
.venv/Scripts/python -m ruff format app tests && .venv/Scripts/python -m ruff check app tests
```

## API

| 路由 | 说明 |
|---|---|
| `GET /health` | 存活检查 |
| `POST /api/v1/extract` | 链接/文本解析（GLM 或 mock；注入内容隔离标记；置信度 <0.8 待确认；解析期零写权限） |
| `GET /api/v1/amap/poi/search` | 高德 POI 服务端代理（key 不出服务端） |
| `POST /api/v1/translate` | 翻译快车道（zh↔en；短语缓存；注入防护；铁律 21 云端只收文本） |
| `POST /api/v1/plan/start` · `POST /api/v1/plan/{sid}/message` · `POST /api/v1/plan/{sid}/save` · `POST /api/v1/plan/from-itinerary/{id}` | 多城规划 Agent：澄清≤2→立即 v0 带假设→对话迭代（DiffOps 过管线，铁律 0/19；自修≤3）；save = 点「💾 保存行程」才落库+冻结快照（2026-10-20 起规划不自动写行程库；快照额度 402）；from-itinerary = 「行程」页「✏️ 修改」用工作副本开修改会话（跨归属/未知 404） |
| `POST/GET /api/v1/itineraries` · `PUT/DELETE /{id}` | 行程 CRUD（DELETE 连同其快照删除；行程中心 trip-items 不受影响；列表含 created_at/updated_at——UTC 存储、端侧本地时区渲染；updated_at 随每次保存/变更/恢复刷新（改完再存时间跟着走））+ 变更管线（铁律 1-6 校验；违规 422） |
| `POST/GET /api/v1/itineraries/{id}/snapshots…/restore` | 快照冻结/恢复（铁律 16 快照不可变；额度走权益服务 402；恢复只写工作副本） |
| `POST /api/v1/nav/walking` · `POST /api/v1/nav/transit` | 五模式导航（设计 v2.2 §6.13）：步行/公交路径高德 Web API 代理——fast 车道零 LLM，key 不出服务端；偏航重路由 = 携当前位置重调 walking |
| `POST /api/v1/nav/deeplink` | 出租/自驾 deeplink 合成（高德打车/滴滴 H5/驾车导航+Web 兜底+Apple Maps iOS 备选；无 key；铁律 22 只 handoff 不代叫车） |
| `POST /api/v1/nav/transport-reminders` · `POST /api/v1/nav/missed-connection` | 火车/飞机行程层：出发前赶车提醒（train 45min / flight 90min 缓冲）+ 误车免费应急兜底（最近班次 + 打车 deeplink，§6.7 永远免费） |
| `POST /api/v1/bookings/train` · `POST /api/v1/bookings/flight` · `POST /api/v1/bookings/hotel` | 行程后预订 handoff（设计 v2.2 §6.11）：12306 余票页带参 / 去哪儿主+携程备 / 携程酒店列表+美团备——铁律 22 只 handoff 不代客交易，铁律 23 每个 handoff 必带 refund_policy 退改摘要，无摘要=禁止跳转 |
| `GET /h5/` | 单页 H5 冒烟页（App 式交互测试面）：左栏 规划/翻译/导航/行程/预订 五模块 + 手写瓦片地图（高德栅格瓦片，无 SDK 无 key）+ 模拟导航/偏航重路由 + 预订确认浮层（退改摘要先行） |
| `POST/GET/PATCH/DELETE /api/v1/trip-items…` | 行程中心三态（设计 v2.4 §5/铁律 0 同源）：wishlist→scheduled（须 day）→booked（须 booking_id）状态机 + 撤销；手动/对话/粘贴写同一张表；Bookings 置顶 + Wishlist 流 |
| `POST /api/v1/offers/cards` | 转链交易中心（设计 v2.3 §6.11）：候选卡片组 2–4 渠道确定性比价 workflow——排序佣金权重为零、12306 全国统一价、同价按稳定性标「同价」、国外隐藏美团、深链服务端注入（alliance_id/sid 占位）、disclaimer 恒挂 |
| `POST /api/v1/backfill/handoffs…` · `/paste-return` · `/undo` · `/manual` · `/alliance-sync` | 订单回填三层管道（设计 v2.4）：粘贴回填为主（conf<0.8 不落库进待确认）+ 手动标记兜底 + 联盟订单同步 mock；双源验证状态机 opened→user_confirmed→alliance_verified→settled（returned 逆向）；paste/manual 可撤销 |
| `GET/PUT /api/v1/profile` · `POST /distill…/undo` | 全局 Agent 画像层（设计 v2.4 §6.14）：可查看可修正（手改字段蒸馏不覆盖）+ 确定性蒸馏 MVP（零 LLM，conf≥0.8 应用带 applied_id 可撤销，<0.8 进 suggestions） |
| `POST/GET /api/v1/links…` · `/{id}/reparse` · `/{id}/to-wishlist` | 个人主页链接历史（双来源 user_paste/agent_recommend）：重新解析 + 加入心愿单（写同一张 trip_items） |
| `POST /api/v1/auth/email/code` · `/auth/email/register` · `/auth/register` · `/auth/login` · `/auth/logout` · `/auth/password/reset` · `GET /auth/me` | 自定义邮箱+密码账号（设计 v2.4.1/2.4.2，决策速查 9）：注册/登录即认领当前设备匿名行程（owner_account_id）；SMTP 未配置=开发态回显验证码；Bearer 鉴权，OAuth 留待企业主体 |
| `POST /api/v1/asr` | H5 语音输入（multipart wav → 智谱 GLM-ASR → text）：替代浏览器 Web Speech——Chrome 识别走谷歌服务大陆不可达 |
| `GET /api/weather` · `POST /api/weather/sync` | 城市天气只读 feed（v2.5 参考数据域，weather_reports 快照表：高德 3 日 + Open-Meteo 14 天）；sync 开站巡检纯读表逐城回报 has_data/fresh（从不出网；抓取只属每日 08:10 管线，全量 40 城） |
| `GET /api/v1/visa/240h` | 240h 过境免签行程校验（§14.3-G2）：确定性纯函数零 LLM 零外呼——行程页绿/红横幅数据源 |
| `POST /api/v1/feedback/vote` · `/visit` · `/review` · `GET /feedback/poi` | 互动闭环（§4）：卡片👍👎 / 行中打卡 / 行后点评 / 「去过的人说」聚合——零 LLM 零外呼 |
| `GET /api/v1/booking-auto/tiers` · `POST /tasks` · `/check` · `/select` · `/order-intent` · `GET /selected` · `/shows` · `/sites` | 预约自动化三档栈（booking_design 2026-10-25）：L1 抢票日历 / L2 渠道可订性 / L3 下单闭环预填（17 馆名单+降级链）+ 🎭 演出目录（show_booking S5）+ 🎫 景点目录/热门榜/geo 分流 |
| `POST /api/v1/payments/checkout` · `GET /mine` · `GET /{id}` · `POST /{id}/confirm` · `/{id}/charge` · `POST /webhook/stripe` | 客户付款层（payments_design 2026-10-25；铁律 22 不变只收款不代交易）：pay_now/save_method 双形态、mock 网关先行（支付宝 wap 主通道待资质，stripe 预留）、webhook 验签、运营扣款 X-Operator-Token 守卫 |
| `POST /api/v1/call/orders` · `GET /packages` · `/balance` · `/records` · `POST /sessions` · `GET /sessions/{id}` · `POST /sessions/{id}/end` · `POST /orders/{id}/confirm` · 坐席 `GET /agent/queue` · `POST /agent/sessions/{id}/answer|end` · `POST /webhooks/{provider}` | 真人通话咨询（paid_call_service_design v1.2）：预付费分钟账本（$1=5min）+ 服务端权威会话（到点强结/提前挂断退整分钟/120s 未接通全退）+ X-Agent-Key 护门（未配 503 错键 401）；SQLite 侧库三表 |
| `GET/POST /api/v1/travelers` · `PUT/DELETE /{id}` · `DELETE /` · `GET /export` | 出行人资料（CLIENT_DATA_REQUIREMENTS）：代客预订实名档案 CRUD——列表/读取只回脱敏形（证件/手机打星），export 唯一明文出口带审计，DELETE / 清空本人数据（被遗忘权），consent 必须 true |
| `POST /api/v1/tasks` · `GET /tasks/{id}` · `GET /tasks` | 慢车道任务（§6.12 ③）：入队即回 202（<3s 受理口径）+ H5 轮询 done/failed + 本设备任务列表（通知兜底） |
| `GET /api/v1/metrics/lanes` | 双车道指标（§6.12 ④）：闸门统计（分类来源/快车道占比/意图缓存命中）+ 服务指标（fast TTFT p95 / slow 受理 p95 / 达标布尔） |
| `POST /api/v1/plan/{sid}/sites/confirm` · `/items/{id}/pin` · `/move` · `/retime` · `/delete` | 规划会话内条目操作：站点确认入程 / 钉住（引擎不重排）/ 移动 / 改时段 / 删除（回写「不想去」） |
| `POST /api/v1/itineraries/{id}/share` · `GET /{id}/export` · `GET /s/{token}` · `GET /api/v1/public/trips/{token}` | 行程导出/分享（feature_gap P0）：打包清单导出 + owner 开关 + token 公开只读页 |
| `GET /api/pois/detail` | POI 详情气泡数据源：intro/照片/标签/电话带字段级 source 标注（geography 列不加载规避序列化坑） |
| `GET /api/v1/amap/regeo` · `/ip` | 高德逆地理 + IP 归属城市（服务端代理；geo 分流/定位兜底） |

域服务（无路由）：`itinerary` 校验/管线/求解器、`entitlement` 权益+付费墙、`gate` 请求分类闸门、`trains` 车次服务、`restaurants` 餐厅推荐 v1（顺路度×评分，铁律 20 只插用餐空窗）；v2.4.x–v2.5 增：`poi_details` POI 详情库（内存+PG 两级，DB-down 300s 闩）、`best_visit` 时段属性三层回填、`geo_split` 地理分流、`fast_lane`/`lane_metrics` 双车道、`task_queue` 慢车道队列、`call_service`/`call_store`（SQLite 侧库）、`payments`、`travelers`（Fernet 加密+审计）、`reservation_seeds` 预约种子、`map_provider`/`baidu_client`、`ctrip_hours` 携程时长解析、`coords` GCJ-02↔WGS84。
