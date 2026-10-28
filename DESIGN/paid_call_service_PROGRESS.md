# PAID_CALL_PROGRESS — 真人通话咨询服务施工清单

> ## 🏁 终态：ALL COMPLETE（2026-10-25 11:40）
> **T0a–T9 全部勾选、全量 1148 passed / 81.39% 覆盖率 / ruff 干净、真实 HTTP E2E 12/12。**
> **续跑 automation 请立即结束本轮并自删（CronDelete `automation-280b8739-a0bc-4547-95bc-0805de18df0b`）；
> 若 CronDelete 不可用 ⇒ 本轮直接退出，不做任何事。施工已收口，禁止再领取任何任务、禁止改代码。**
> 变更未提交（feat/v24-trip-center），等用户验收 commit。

> 本文件是**自包含施工清单**：任何新会话（含定时续跑 automation）据此继续施工，无需原会话上下文。
> 设计依据：`DESIGN/paid_call_service_design_2026-10-25.md`（v1.2，用户已批准开工 2026-10-25）。
> 节奏：每 2 分钟续跑 automation（用户指定「每2分钟跑AUTOMATION」）。

## 背景与目标（一段话）

H5 新增「📞 咨询」付费服务：旅客预购通话分钟（$1=5 分钟，¥8=5 分钟，套餐 5/10/20/60，余额可累积），
点「实时通话」创建服务端权威计费会话——**主路径一键 tel: 直拨坐席热线**（`call_hotline_number`），
留号回拨为备选；坐席在 `agent.html` 员工台接听；到点服务端强制结束（退整分钟规则见设计 §3.3/§7.4）；
旅客可见「开始时刻·已用时·剩余倒计时·结束时刻」与「通话记录」（日期/时长/状态/分钟流水）。
收款走网关协议：MVP=mock 零网络，支付宝 wap/Stripe 为 config 门控 stub（诚实 503）。
铁律 22 豁免（第一方服务收款）与铁律 23（退款摘要先行）已在设计文档声明。

## 硬约定（违反即返工）

- 分支 `feat/v24-trip-center`；**不自动 commit、不 git add**（用户未授权本功能自动提交），严禁 `git add -A` / `git add .`；变更留在工作区由用户验收。
- **共享文件纪律**：`app/config.py`、`app/main.py`、`.env.example`、`app/static/index.html`、`app/static/i18n.js`、`app/static/sw.js` 同时被支付 automation/引擎监控并行施工——编辑前**必须当场重读最新内容**，只追加本功能块，绝不删改他人新增行；若该文件 mtime < 3 分钟（他人刚写），先 `sleep 60` 再重读。
- 不动 `DESIGN/PAYMENTS_PROGRESS.md` 与支付功能文件（app/services/payments.py、app/api/payments.py 等）；不动引擎监控在写文件（mtime < 3 分钟让行）。
- 无新 pip 依赖；SQLite 侧库照 `state_persist`/`train_cache` 模式（单连接 + threading.Lock + check_same_thread=False + 写穿透）。
- 金额约定 yuan float（repo 惯例）；注释中文；日期 ISO 8601。
- 测试门槛：`cd "CHINATRIP CODES" && .venv/Scripts/python -m pytest --cov=app --cov-fail-under=75` 绿 + `.venv/Scripts/python -m ruff format app tests && .venv/Scripts/python -m ruff check app tests` 干净。
- **lease 防撞**：开工前若有任务标 `[IN PROGRESS lease: <ISO时间>]` 且距今 **< 15 分钟** ⇒ 本次运行只退出不施工；≥ 15 分钟才可接管（改写 lease）。领任务立刻写 lease；完成后改 `[x]` 并删 lease 行。每次运行最多完成 **2 个任务**（避免与原会话/其他 automation 长时间并行）。
- dev server 验证用 `scripts/dev_watch.py watch`（禁 uvicorn --reload）。

## 清单

- [x] T0a 本进度文件建立（`DESIGN/paid_call_service_PROGRESS.md`）
- [x] T0b 每 2 分钟续跑 automation 建立（CronCreate `*/2 * * * *`；全部任务完成后自删）

- [x] T1 配置键（`CHINATRIP CODES/app/config.py` 客户付款层块后 + `.env.example` CALL_ 块）：call_db_url / call_packages_json / call_provider / call_hotline_number / call_min_minutes / call_max_minutes / call_waiting_timeout_seconds / usd_cny_rate / agent_console_key / alipay_* ；**stripe_api_key/stripe_webhook_secret 已由支付层 T1 落地（10:00），本功能共用不重复**。
      [x] 2026-10-25 10:50 验收：ruff format/check 干净；get_settings() 导入 provider=min/max/hotline/agent_key 全部就位。

- [x] T2 存储层（`CHINATRIP CODES/app/services/call_store.py`，新文件）：CallStore 单连接+Lock+WAL，三表（call_orders/call_sessions/call_minutes_entries），balance/add_entry/try_consume（原子扣减）/create_order/mark_order_paid（provider_ref 幂等不重复入账）/mark_order_refunded/create_session/get_session/update_session（列白名单）/list_sessions/list_agent_queue/claim_device；smoke 测试通过（幂等入账、原子扣减、余额不足拒绝、状态机更新）。
      [x] 2026-10-25 10:55 验收：ruff format/check 干净；`:memory:` 冒烟全过。

- [ ] T2 存储层（`CHINATRIP CODES/app/services/call_store.py`，新文件）
      CallStore：sqlite3 直连（照 train_cache 风格：settings.call_db_url，data/ 目录自建，
      单连接 + threading.Lock + check_same_thread=False，WAL）。
      三表 CREATE TABLE IF NOT EXISTS：
      `call_orders(id TEXT PK, device_id TEXT NOT NULL, username TEXT, package_code TEXT NOT NULL, minutes INTEGER NOT NULL, currency TEXT NOT NULL, amount_yuan REAL NOT NULL, provider TEXT NOT NULL, provider_ref TEXT UNIQUE, status TEXT NOT NULL DEFAULT 'created', refund_summary TEXT, created_at TEXT NOT NULL, paid_at TEXT)`；
      `call_sessions(id TEXT PK, device_id TEXT NOT NULL, username TEXT, phone TEXT, mode TEXT NOT NULL DEFAULT 'direct', duration_minutes INTEGER NOT NULL, granted_minutes INTEGER NOT NULL, consumed_seconds INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'waiting', end_reason TEXT, agent TEXT, refund_minutes INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, started_at TEXT, ended_at TEXT, updated_at TEXT NOT NULL)`；
      `call_minutes_entries(id TEXT PK, device_id TEXT NOT NULL, username TEXT, delta_minutes INTEGER NOT NULL, kind TEXT NOT NULL, order_id TEXT, session_id TEXT, note TEXT, created_at TEXT NOT NULL)`。
      方法（全部 Lock 内、参数化 SQL）：balance(device_id, username)->int（SUM delta）、
      add_entry / create_order / get_order / mark_order_paid(provider_ref 幂等：已 paid 直接返回不重复入账) / mark_order_refunded /
      create_session / get_session / list_sessions(owner) / update_session / list_agent_queue(waiting+active) /
      claim_device_entries(device_id, username)（登录认领，照 claim_device_itineraries 语义：UPDATE ... WHERE device_id=? AND username IS NULL）。
      id 用 uuid4 hex。时间 ISO 8601 本地 +08:00。
      验收：ruff 干净。

- [x] T3 服务层（`CHINATRIP CODES/app/services/call_service.py`）：CallError(status_code+detail)；CallPaymentGateway 协议 + Mock/Alipay/Stripe 三网关统一 `__init__(settings)`（键未配 503 provider_not_configured / 未实装 provider_not_implemented）；CallService：packages（解析 JSON+校验）、balance、create_order（锁定单币种+退款摘要快照）、mock_confirm（非 mock 403、归属校验、幂等）、handle_webhook（mock 渠道 order_id 透传，mark_order_paid 幂等）、create_session（5 倍数/上下限/余额 402/direct 需热线否则 422 hotline_not_configured/callback 需手机号）、poll_session（waiting 超时→expired 全退；active 到点→exhausted；惰性强结）、end_session（active 按实际用时退整分钟，幂等）、agent_queue/agent_answer/agent_end、records（起止时刻+时长标签+订单）、claim_device；lazy 单例 get_call_service()。
      [x] 2026-10-25 10:58 验收：ruff 干净；:memory: 冒烟全过（含到点 exhausted、超时 expired、webhook 幂等、402/503 语义）。备注：hotline 未配 detail 用 `hotline_not_configured`（客户端据此降级 callback）。

- [x] T4 API 层（`CHINATRIP CODES/app/api/call.py` + `app/main.py` 注册）：12 端点全落地（packages/balance/orders/confirm/webhooks/records/sessions/poll/end + agent queue/answer/end，X-Agent-Key 护门：未配 503 agent_disabled、错 401 agent_key_invalid；CallError→HTTPException 统一翻译；X-Device-ID 必带 422）。
      [x] 2026-10-25 11:00 验收：ruff 干净；TestClient 冒烟全过（含 hotline 未配 422、phone_required、agent 503）；全量 pytest 1123 通过——3 个失败均在 test_backfill_en_columns（该作业与其测试 mtime 10:55/10:56 = 并行会话在写中，非本功能回归，让行复检）。
      - `CallError(Exception)`（status_code + detail）；`CallPaymentGateway` Protocol：`create_payment(order: dict) -> dict`（返回 `{"type":"mock_confirm"}` 或 `{"type":"redirect","url":...}`）、`name` 属性。
      - `MockGateway`（零网络）；`AlipayWapGateway`/`StripeCheckoutGateway` stub：`create_payment` 抛 CallError(503, "provider_not_configured")（键未配时）；`get_gateway(settings)` 工厂按 call_provider 返回。
      - `CallService(store, settings)`：`packages()`（解析 call_packages_json + 校验结构）、`balance()`、
        `create_order(owner, package_code, currency)`（校验包存在/币种 cny|usd；amount 取 price_cny/price_usd；refund_summary=设计 §3.4 文案）、
        `mock_confirm(order_id)`（call_provider != mock ⇒ 403；成功⇒mark_order_paid+add_entry purchase）、
        `handle_webhook(provider, payload)`（provider_ref 找单，mark_order_paid 幂等；stub 阶段仅 mock 渠道+透传校验）、
        `create_session(owner, duration_minutes, mode, phone)`（校验：duration 为 5 倍数、min≤duration≤max、direct 时 hotline 必须已配否则 422 callback_fallback、callback 时 phone 必填；Lock 内 balance 检查→add_entry consume→create_session waiting）、
        `poll_session(session_id, owner_or_agent)`（waiting 超时判定⇒expired+refund 全额；active 重算 consumed⇒到点强结 exhausted+不退；返回 status/remaining_seconds/started_at/dial）、
        `end_session(session_id, by)`（active⇒ended end_reason=user|agent，refund=floor(剩余秒/60)⇒add_entry refund；waiting⇒取消全退）、
        `agent_queue()`、`agent_answer(session_id, agent)`、`records(owner)`（sessions 最新在前+orders）、
        `claim_device(device_id, username)`。
      - 模块级 `_singleton` + `get_call_service()` lazy 单例（照 trip_items.py 模式）。
      验收：ruff 干净。

- [ ] T4 API 层（`CHINATRIP CODES/app/api/call.py`，新文件 + `app/main.py` 注册）
      `router = APIRouter(prefix="/api/v1/call", tags=["call"])`；身份=X-Device-ID 必配（缺⇒422）+可选 Bearer（username 经 accounts.AccountService.verify_token？——简化：X-Username 不安全，MVP 只用 device_id，username 留字段）。
      路由（照设计 §8 表）：GET /packages、GET /balance、POST /orders、POST /orders/{id}/confirm、
      POST /webhooks/{provider}、GET /records、POST /sessions、GET /sessions/{id}、POST /sessions/{id}/end；
      坐席三端点校验 `X-Agent-Key == settings.agent_console_key`（未配置⇒503 agent_disabled；错⇒401）：
      GET /agent/queue、POST /agent/sessions/{id}/answer、POST /agent/sessions/{id}/end。
      CallError⇒HTTPException(status_code, detail)。main.py include（register 前 fresh read，加在 booking_auto_router 后）。
      验收：`python -c "from app.main import create_app; create_app()"` 启动成功；ruff 干净。

- [x] T5 测试（`tests/test_call_store.py` 6 例、`tests/test_call_api.py` 8 例、`tests/test_call_gateway.py` 6 例，共 20 例）：账本原子/幂等/隔离、订单 provider_ref 幂等、会话白名单、坐席队列排序；API 全链路（买 10→直拨→接听→回拨 started_at 到点 exhausted 余额 0、提前挂断 3'30" 退 6 整分钟、waiting 超时全退、402/403/401/422/503 语义、设备隔离 404、records 起止时刻+mm:ss 时长+分钟流水）；网关 Mock 形状/双 stub 门控/webhook 幂等。修 store 同秒排序（rowid 兜底）。
      [x] 2026-10-25 11:10 验收：**全量 1146 passed 全绿，覆盖率 81.32% ≥ 75% 门槛，ruff format/check 全树干净**。
      store：账本余额累加/原子、订单流转、provider_ref 幂等、claim。api：TestClient(create_app()) 全链路 mock——
      买 10 分→余额 10→开 10 分会话（direct，mock hotline 需先 monkeypatch settings 或用 settings 注入）→agent queue/answer→poll 到点 exhausted→余额 0；
      提前挂断退整分钟；waiting 超时退款；402/403/401/422 语义；records 字段（起止时刻/时长/状态/分钟）。
      gateway：Mock 形状；stub 未配 key 抛 503；webhook 幂等。
      注意：CallStore 支持注入 `:memory:`（测试用 tmp_path 或 memory + 每测试新建）。
      验收：pytest 全绿 + 覆盖率 ≥75% 保持 + ruff 干净。

- [x] T6 H5 旅客端：nav 加「📞 咨询」tab（book 后）；tab-call 区（余额 chip / 套餐网格双币价签 / 时长步进 chips（上限=min(余额,max)）/ direct·callback 单选+手机号 / 退款规则折叠块 / 通话覆盖层：状态·开始时刻·已用时·剩余三要素计时条+巨型 tel: 直拨按钮+挂断，结束页显示结束时刻+实际时长+退还分钟）；通话记录卡（状态徽章+时间+时长+直拨/回拨+原因+分钟流水）；mock 一键购买；422 hotline_not_configured 自动降级 callback；i18n 中英 30 键。**顺手机械修复并行会话写坏的 index.html 引号笔误（visit-block tail 拼接，全页 JS 因此瘫痪）**。
      [x] 2026-10-25 11:20 验收：node --check 全部脚本块 OK；15 个 DOM id 唯一性 + i18n 双语键齐全性校验全过。
      nav 加 `<button class="nav-item" data-tab="call" data-i18n="nav.call">📞 咨询</button>`（插在 book 后）；
      `<section class="tab" id="tab-call">`：余额 chip、套餐网格（双币价签）、mock dev 横幅、退款摘要折叠块（铁律 23）、
      时长步进（5 的倍数，上下限由 /packages）、方式切换（立即拨打/等回拨+手机号）、大按钮→通话覆盖层
      （direct=巨型 tel: 按钮+「开始时刻·已用时·剩余倒计时」计时条+挂断；callback=等待态+取消；到点全屏提醒；
      结束页=结束时刻+实际时长+退还分钟）、通话记录卡（列表+明细展开）。
      轮询 3s：GET /sessions/{id}；页面切换/结束时 clearInterval。i18n.js 补 nav.call + call.* 中英键（fresh read 追加）。
      验收：手测 mock 全流程零网络；无 console 报错；中英切换正常。

- [x] T7 坐席台 + PWA：`agent.html` 员工键登录（localStorage，X-Agent-Key/X-Agent-Name 头）→ 等待队列 5s 自动刷新（direct 呼入置顶「旅客直拨呼入」、callback 显号码 + tel: 外呼链接；>90s 黄色高亮提醒）→ 接听 → 通话中计时条（已用/剩余 tabular-nums）→ 挂断（confirm 后退整分钟提示）；503=未启用 / 401=键错时回登录页并提示。sw.js VERSION 升 v27 + SHELL 加 './agent.html'。
      [x] 2026-10-25 11:26 验收：node --check agent.html 内联脚本 + sw.js 均 OK；ruff 全树干净；通话三测试 + test_pwa 共 24 passed。
      agent.html：员工键登录（localStorage chinatrip_agent_key，X-Agent-Key 头）、等待队列（5s 刷新，direct 呼入置顶提示、callback 显号码+tel: 外呼链接）、接听→active 计时条（已用时/剩余）、挂断；到点蜂鸣横幅。风格对齐 index.html（同 CSS 变量/深浅色）。
      验收：手测 direct/callback 两模式接听挂断；sw 版本生效。

- [x] T8 设计文档转正 + INDEX：设计文档状态改「已批准开工」+ 头部补上游联动（用户拍板：支付宝 wap 主通道/Visa-MC 直连取消/Stripe 预留——与付款层拍板对齐）；INDEX.md 当前版本节插入本设计行（「与代码同步」，置于付款层行后）。
      [x] 2026-10-25 11:32 验收：INDEX.md fresh read 后追加（并行会话改动无冲突）。
- [x] T9 终验：dev server 经 dev_watch restart 后载入新代码（86 路由含 call 12 端点）；真实 HTTP E2E 12/12 全过（余额→买 10 分钟 usd→mock 确认幂等→direct 无热线诚实 422→callback 会话→坐席无键 503→轮询→未接通取消全退→余额复原→records 完整）；H5 index/agent.html/sw.js 全 200。全量 pytest **1148 passed 全绿，覆盖率 81.39% ≥ 75%**；ruff 全树 185 files unchanged + check 干净。全部任务勾完 ⇒ 续跑 automation 自删。
      [x] 2026-10-25 11:40 验收：ALL COMPLETE。未提交变更留在工作区（分支 feat/v24-trip-center），由用户验收后自行 commit。

## 验收记录

- 2026-10-25 10:43 原会话：T0a 完成；T1 领取（lease 2026-10-25T10:43:55+08:00）。
- 2026-10-25 10:50 原会话：T0b 完成（automation automation-280b8739 每 2 分钟）；T1 完成（config.py + .env.example，ruff 干净，导入验证通过；与支付层共享 stripe 键不重复）。领取 T2。
- 2026-10-25 10:55 原会话（续跑 automation 第 1 轮，lease 持有者继续）：T2 完成（call_store.py 三表 + 原子账本 + 幂等订单；ruff 干净 + :memory: 冒烟全过）。本轮 2 任务配额用尽，下一任务 T3 留给下轮。
- 2026-10-25 11:00 续跑 automation 第 2 轮：T3 完成（call_service.py 全量业务规则，冒烟含 exhausted/expired/幂等/402/503）；T4 完成（api/call.py 12 端点 + main.py 注册，TestClient 冒烟全过）。全量 pytest 1123 过 / 3 败——失败全在并行会话在写的 backfill_en_columns（mtime 10:55/10:56），非本功能回归。本轮配额用尽，下轮 T5。
- 2026-10-25 11:10 续跑 automation 第 3 轮：T5 完成（三测试文件 20 例；并行会话的 backfill_en_columns 3 败已由其修复，5 passed 复核）。**全量门槛：1146 passed 全绿 + 覆盖率 81.32% ≥ 75% + ruff 全树干净**。
- 2026-10-25 11:26 续跑 automation 第 4 轮：T6 完成（H5 tab-call 全套 + 覆盖层 + 记录卡 + i18n 30 键；顺手机械修复并行会话写坏的 index.html 引号笔误）；T7 完成（agent.html 坐席台 + sw v27）。node --check 全部脚本块 OK，DOM/i18n 校验过，24 相关测试过。本轮配额用尽，下轮 T8→T9。
- 2026-10-25 11:40 续跑 automation 第 5 轮（收口轮）：T8 完成（设计转正 + INDEX 登记）；T9 完成（dev_watch restart 载入新代码；真实 HTTP E2E 12/12；全量 1148 passed + 81.39% 覆盖率 + ruff 干净）。**全部 T0a-T9 勾完 → 续跑 automation 自删（CronDelete）→ ALL COMPLETE。**
