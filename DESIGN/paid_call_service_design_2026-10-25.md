# 真人通话咨询服务设计（Paid Human-Call Service）

> 版本 v1.2 ｜ 2026-10-25 ｜ 状态：**已批准开工**（2026-10-25 用户开工令「每2分钟跑AUTOMATION」；施工清单与验收记录：`DESIGN/paid_call_service_PROGRESS.md`）
> v1.1 变更（评审反馈）：**旅客可直接拨打坐席**——一键 `tel:` 拨打坐席热线为主路径，留号等坐席回拨降为备选，不再「只等回拨」。
> v1.2 变更（评审反馈）：**通话计时全程可见**（开始时刻/已用时/剩余倒计时/结束时刻）+ **旅客通话记录**（日期时间、时长、状态、扣减/退还分钟）。
> 上游联动（2026-10-25 用户拍板）：生产主通道=**支付宝 wap 直连**（待个体工商户资质）；Visa/MC 直连渠道取消（无境外主体），Stripe adapter 保留为预留不上线——与本设计 §4 落地顺序一致，收款网关与客户付款层共用协议与键。
> 决策一句话：**预付费分钟账本（ledger）+ 服务端权威通话会话（到点自动结束）+ 网关可替换收款（先 mock，后支付宝/Stripe）**。
> 上游需求：「付费预约真人电话咨询：$1=5 分钟，付费后点实时通话按钮，通话到分钟数自动结束」。
> 关联文档：`DESIGN/PAYMENTS_PROGRESS.md`（并行施工的「客户付款能力」收款层）、`DESIGN/language_dual_system_design_2026-10-25.md`（双语双部署）、主设计 v2.5 铁律 0–23。

---

## 1. 背景与定位

| 事实 | 影响 |
| --- | --- |
| 平台已有并行施工的收款层（PAYMENTS_PROGRESS：Stripe hosted Checkout + mock 网关，pay_now/save_method 双形态） | 本功能的「买分钟」付款动作**复用同款网关协议与 mock 先行策略**，不另起炉灶 |
| 铁律 22「行动只 handoff 不代客交易」 | 通话咨询是**公司自有第一方服务**（公司↔客户收款），与渠道代订不同，属明确豁免场景——本节即豁免声明，与 PAYMENTS_PROGRESS 同款处理；渠道侧预订 handoff 路径完全不变 |
| 铁律 23「退改规则预订前明示」 | 购买前必须展示退款摘要（见 §3.4） |
| 主要客户 = 外国入境游客 + 国内用户 | 双币种定价（¥/$）、双语 UI（i18n）、收款通道按人群分流（见 §4） |
| 现有架构无 WebSocket / 无 WebRTC / 无支付通道 | MVP 语音走运营商电话：**旅客一键 `tel:` 直接拨打坐席热线（主路径）**，或留号等坐席回拨（备选）；系统负责**计费、计时、状态机与自动结束**；语音传输层留替换缝（§7.4） |

## 2. 结论（定稿）

**新模块「通话咨询」：旅客预购通话分钟（$1=5 分钟，¥8=5 分钟，余额可累积叠加），点击「实时通话」按钮创建服务端权威的计费会话（所选时长一次性从余额划入会话），**主路径=一键 `tel:` 直接拨打坐席热线**（留号等坐席回拨为备选），坐席在员工台接听，通话到点由服务端强制结束；提前挂断退还未用整分钟；无人接听超时全额退款。收款走网关协议（MVP=mock 零网络；生产=支付宝手机网站支付为主 + Stripe 结账为辅）。**

## 3. 产品规则（定价 · 余额 · 会话 · 退款）

### 3.1 定价（config 可调，不写死）

| 包 | 分钟数 | 价格 CNY | 价格 USD |
| --- | --- | --- | --- |
| call_m5 | 5 | ¥8 | $1 |
| call_m10 | 10 | ¥16 | $2 |
| call_m20 | 20 | ¥30 | $4 |
| call_m60 | 60 | ¥90 | $12 |

- 单价 ≈ $0.2/分钟；`usd_cny_rate` 仅用于展示换算，订单落库时锁定单币种（`currency` + `amount_yuan`，repo 惯例 yuan float）。
- 起充 = 5 分钟；余额**累积**（「expanding by minutes」），无有效期（MVP；过期策略留配置位）。

### 3.2 余额与账本（ledger）

- 余额 = `SUM(delta_minutes)`，账本只追加不改写。条目类型：`purchase`（购买入账）/ `consume`（开会话划出，负）/ `refund`（提前挂断退回整分钟，正）/ `adjust`（客服调整）/ `expire`（预留）。
- 所有权：`device_id` 恒有，登录用户带 `username`；登录时按 `claim_device_itineraries` 同款规则认领设备账本。

### 3.3 通话会话（两种发起方式，状态机同一套）

- **直接拨打（默认 `mode=direct`，主路径）**：点击「实时通话」→ 选时长（5 的整数倍，≥5 分钟，≤ min(余额, `call_max_minutes`=60)）→ 确认 → 会话 `waiting` + 通话覆盖层出现**一键「📞 拨打坐席」`tel:` 按钮**（号码 = `call_hotline_number` 坐席热线；桌面端展示号码供手动拨打）；旅客点击即直接呼出；坐席台按「接听」→ `active` 开始计时。
- **坐席回拨（备选 `mode=callback`）**：同上但提交回拨手机号，坐席台展示号码由坐席外呼，接听后同状态机——适合桌面端/无 SIM 场景。
- 状态机：`waiting → active → ended`；分支终态 `expired`（无人接听）/ `failed`。
- `waiting` 超时 `call_waiting_timeout_seconds`=120s ⇒ 全额退款转 `expired`。
- `active` 起服务端计时：`consumed = now - started_at`；**到点（consumed ≥ granted_minutes×60）服务端强制结束**，`end_reason=exhausted`——这正是「付 10 分钟就聊 10 分钟」的保证。旅客端与坐席台每 ~3s 轮询会话状态，任一侧轮询即触发惰性强制判定（无需后台线程；双端都停轮询的最坏情形由下次任一读取兜底）。
- **计时全程可见**：通话覆盖层常驻显示「开始时刻（接通时间）· 已用时 · 剩余倒计时」三要素，均以服务端 `started_at`/`consumed` 为唯一口径（防本地时钟漂移）；结束时展示「结束时刻 + 本次实际时长」。
- **通话记录**：每次会话落 `call_sessions`（发起 `created_at`、接通 `started_at`、结束 `ended_at`、实际时长 `consumed_seconds`、状态/结束原因、划入/退还分钟），旅客端「通话记录」列表可回查——无需新表，直接读会话表（§6）。
- 提前挂断（旅客或坐席）：退回未用**整分钟**（`floor`），`end_reason=user|agent`。

### 3.4 退款摘要（铁律 23，购买前明示，双语）

> 通话分钟为预付费虚拟权益：通话开始后按分钟消耗；提前挂断退回未用整分钟；下单未接通（120 秒无人接听）全额原路退回；到点自动结束不退当次已选时长中已消耗部分。如有争议联系 service@chinatrip.example。

## 4. 收款通道可行性研究（2026-10-25 联网核查）

| 通道 | 主体要求 | 覆盖人群 | 结论 |
| --- | --- | --- | --- |
| **支付宝 手机网站支付（wap）** | **个体工商户即可**（需同名营业执照 + 门头/经营场所照片）；企业账号更顺 | 国内用户 ✅；**外国游客 ✅**——外国卡（Visa/MC/Amex/JCB 等）可绑定支付宝钱包，护照实名，≤¥200 免手续费、以上约 3%，单笔上限高（央行 2024 放宽至 $5,000/笔量级） | **主力通道**。一个通道同时覆盖国内 + 大多数外国游客（外国游客赴华普遍装支付宝） |
| 支付宝 当面付（扫码） | 企业或个体工商户（门头照） | 同上 | 备选（wap 更贴合 H5 流程） |
| **Stripe Checkout** | **不受理中国大陆主体**；需美/英/港/新等境外实体；Alipay/WeChat Pay 方法需在 Stripe 后台手动申请开通 | 境外纯外卡用户（未装中国钱包者） | **辅助通道**，待境外主体/MoR 就绪后启用；适配器位预留 |
| Merchant-of-Record（Paddle/FastSpring 等） | 个人可签，MoR 承担税务 | 纯外卡 | Stripe 不可行时的替代位，协议已兼容 |

**落地顺序**：MVP 全流程用 `mock` 网关跑通（dev 一键确认，零网络零资质）；生产接 `alipay_wap`（先办个体工商户）；`stripe_checkout` 预留。与 PAYMENTS_PROGRESS 的 `PaymentGateway` 协议同构（mock + hosted checkout + webhook 验签），接线方案见 §10。

> 核查来源：Stripe 官方 Alipay/WeChat Pay 指南（stripe.com/resources/more/alipay-an-in-depth-guide 等，明确「businesses based outside of China」）、支付宝开放文档 opendocs.alipay.com（当面付 03ai9o / 电脑网站 03ah5w：企业或个体工商户；APP 支付 03ajjb：企业）、Trip.com/mychina.guide 外国卡绑定支付宝实测口径（≤¥200 免费/3%）、Antom（Stripe 不受理大陆主体）。

## 5. 目标架构

```
┌ H5 旅客端（static/index.html · tab-call）────────────┐
│ 套餐购买卡 → checkout（mock 一键 / 支付宝跳转）      │
│ 余额 chip · 实时通话按钮 → 通话覆盖层（倒计时/挂断）  │
└───────────────┬─────────────────────────────────────┘
                │  /api/v1/call/*（X-Device-ID + 可选 Bearer）
┌ H5 坐席台（static/agent.html，员工键登录）────────────┐
│ 等待队列 · 接听 → 计时 · 挂断（含回拨号码展示）        │
└───────────────┬─────────────────────────────────────┘
                │
┌ FastAPI ── app/api/call.py ──▼───────────────────────┐
│ CallService（app/services/call_service.py）           │
│  ├ 余额/账本/订单/会话状态机（唯一写入口）             │
│  ├ CallPaymentGateway 协议                            │
│  │   ├ MockGateway（dev confirm，零网络）             │
│  │   ├ AlipayWapGateway（stub，key 未配=诚实 503）    │
│  │   └ StripeCheckoutGateway（stub，同上）            │
│  └ CallStore（app/services/call_store.py）            │
│      SQLite 侧库 sqlite:///data/call_state.db         │
│      （照 state_persist/train_cache 模式：单连接 +     │
│       Lock + 写穿透；单测零 PG 可跑）                  │
└──────────────────────────────────────────────────────┘
```

- 三表 SQLite 侧库沿用既有模式（PG 未上车的业务 store 均走 SQLite 写穿透，见 config 注释与 `database_design.md`）；PG 化迁移路径记录于 §12。

## 6. 数据模型（call_store 三表）

**call_orders（订单）**
`id PK · device_id · username? · package_code · minutes · currency(3) · amount_yuan float · provider(mock|alipay|stripe) · provider_ref? UNIQUE（幂等键） · status(created|paid|failed|refunded) · refund_summary 文本快照 · created_at · paid_at`

**call_sessions（会话）**
`id PK · device_id · username? · phone(30) · duration_minutes · granted_minutes · consumed_seconds · status(waiting|active|ended|expired|failed) · end_reason?(user|agent|exhausted|timeout|error) · agent?(坐席标识) · refund_minutes · started_at? · ended_at? · created_at · updated_at`

**call_minutes_entries（账本，只追加）**
`id PK · device_id · username? · delta_minutes(+/-) · kind(purchase|consume|refund|adjust|expire) · order_id? · session_id? · note? · created_at`

## 7. 关键机制

### 7.1 购买流
`POST /orders {package_code, currency}` → 建 `created` 订单 → 网关 `create_payment(order)`：
- mock ⇒ 返回 `{type:"mock_confirm"}`，dev 调 `POST /orders/{id}/confirm` 模拟成功（`call_provider != "mock"` 时 403，与 PAYMENTS_PROGRESS T3 同款豁免逻辑）；
- alipay/stripe ⇒ 返回 hosted checkout URL；`POST /webhooks/{provider}` 验签回调置 `paid`（provider_ref 幂等，重复回调 200 不重复入账）。

`paid` ⇒ 账本写 `purchase` 入账。

### 7.2 通话流
`POST /sessions {duration_minutes, mode?, phone?}` → 校验（余额≥时长、5 的倍数、≤上限）→ 账本 `consume` → 会话 `waiting`：
- **direct**：响应携带 `dial:{type:"tel", number:热线}`，旅客端一键拨打；坐席台也可看到该会话正在呼入。
- **callback**：旅客号码进坐席台队列，坐席外呼。
→ 坐席 `POST /agent/sessions/{id}/answer`（`active`，`started_at=now`）→ 双端轮询 `GET /sessions/{id}`（服务端重算 consumed、到点强结）→ 挂断 `POST /sessions/{id}/end`（退整分钟）。`waiting` 120s 无人接听 ⇒ `expired` + 全额退款。

### 7.3 坐席鉴权
`X-Agent-Key: <agent_console_key>`；config 未配置 ⇒ 坐席端点整体 403、坐席台显示「未启用」。MVP 单键共享；员工账号体系后置（§13）。

### 7.4 语音传输替换缝与「到点强结」的诚实语义
会话 API 与计费对「声音怎么传」零假设，两种 MVP 传输共用同一状态机：
- **tel: 直接拨打 / 回拨（运营商电话）**：服务端到点强制结束的是**会话与计费**（余额预扣、到点即止）；运营商物理通话无法被服务端远程挂断——到点时双端同步弹全屏「通话时间到」（旅客端置顶强提醒 + 坐席台蜂鸣横幅），由坐席执行挂断、旅客端引导结束。此为 MVP 已知边界，写入退款摘要口径（到点即止）。
- **后续升级 WebRTC（浏览器对讲）或 telephony 回拨桥**：传输层接管 `answer/active/ended` 事件后，到点由服务端真正远程挂断——账本与状态机零改动，只换传输实现。

## 8. API 契约（/api/v1/call）

| 方法/路径 | 说明 |
| --- | --- |
| `GET /packages` | 套餐目录 + min/max 分钟数 |
| `GET /balance` | 余额分钟数（device/bearer 身份） |
| `POST /orders` | 建单 → `{order_id, pay:{type,url?}}` |
| `POST /orders/{id}/confirm` | **仅 mock 后端**（403 otherwise） |
| `POST /webhooks/{provider}` | 网关回调，验签 + provider_ref 幂等 |
| `GET /records` | **我的通话记录 + 订单记录**：每条会话含日期时间（发起/接通/结束）、实际时长、状态徽章、划入/退还分钟；分页（最新在前） |
| `POST /sessions` | 开会话 `{duration_minutes, mode:"direct"(默认)\|"callback", phone?}`（direct 模式 phone 可选仅留档） |
| `GET /sessions/{id}` | 轮询：`{status, remaining_seconds, granted_minutes, agent, dial?}`；direct 模式附 `dial:{type:"tel",number}`；内含到点强结 |
| `POST /sessions/{id}/end` | 旅客挂断 |
| `GET /agent/queue` | 坐席：等待中 + 进行中列表（含 mode 与回拨号码——callback 时展示供外呼；direct 时提示「旅客正呼入热线」） |
| `POST /agent/sessions/{id}/answer` | 接听（waiting→active） |
| `POST /agent/sessions/{id}/end` | 坐席挂断 |

错误语义：余额不足 402 `insufficient_minutes`；参数 422；mock confirm 越权 403；坐席键错 401；网关未配置 503 `provider_not_configured`（诚实降级，同 booking_auto L1/L2 风格）。

## 9. 前端（H5）

- **tab-call「📞 咨询/Call」**：余额 chip + 套餐网格（双币种价签）+ 买分钟按钮 → checkout；mock 模式显示 dev 提示横幅；时长步进选择（5 的倍数）+ 发起方式默认「立即拨打」（可选「等坐席回拨」+手机号）+ 大按钮「实时通话/Real-time Call」→ **通话覆盖层**：direct 模式 = 巨型「📞 立即拨打坐席」`tel:` 按钮 + **「开始时刻 · 已用时 · 剩余倒计时」常驻计时条** + 挂断按钮（轮询 3s）；callback 模式 = 「等待坐席回拨」状态 + 计时 + 取消；到点全屏「通话时间到」强提醒；**结束页展示「结束时刻 + 本次实际时长 + 退还分钟」**。
- **「通话记录」卡**（tab-call 内、余额下方）：最新在前列表——日期时间、实际时长、状态徽章（已完成/提前结束/未接通已退/进行中）、划入/退还分钟；点开单条展开明细（接通/结束时刻、结束原因、关联订单）。双语键 `call.records.*`。
- **static/agent.html 坐席台**（不进底部导航，员工书签直达）：员工键登录（localStorage）、等待队列自动刷新（direct 呼入置顶提示「旅客正呼入热线」；callback 显示号码 + `tel:` 外呼链接）、接听→计时条、挂断；到点蜂鸣横幅提醒挂机。
- i18n.js 补 `nav.call` + `call.*` 中英键；sw.js `VERSION` 升 v27、SHELL 加 `./agent.html`。
- 双语双部署兼容：纯 i18n 文案 + 金额字段化展示，无硬编码中文进逻辑（language_dual_system 纪律）。

## 10. 与 PAYMENTS_PROGRESS（并行收款层）的协同

- 本模块自带 `CallPaymentGateway` 协议 + Mock 网关，**不阻塞、不依赖**收款层合入顺序，可独立交付全流程。
- 收款层 T2/T3（PaymentGateway + checkout API）合入后，新增 ~30 行适配：`CallOrder → payments.checkout(kind=pay_now, amount_yuan, refund_summary)`，webhook 由收款层统一验签后回写 call 订单（provider_ref=payment_id）。届时支付宝/Stripe 键只配一处。
- 防撞纪律：本模块文件（call_*、agent.html）与 PAYMENTS_PROGRESS 清单文件零交集；两 automation 并行时各自只 add 自己的文件（同款「禁 git add -A」铁约）。

## 11. 测试计划（门槛：pytest --cov-fail-under=75 保持 + ruff 干净）

- `tests/test_call_store.py`：账本原子性（并发扣减不超余额）、余额累加、订单状态流转、provider_ref 幂等、重启重载（写穿透）。
- `tests/test_call_api.py`：全链路 mock —— 买 10 分钟 → 余额 10 → 开 10 分钟会话 → 坐席接听 → 轮询到点自动 `exhausted` → 余额 0；提前挂断退整分钟；waiting 超时退款；余额不足 402；mock confirm 越权 403；坐席键 401/403；时长非 5 倍数 422；**`GET /records` 返回起止时刻/实际时长/状态/分钟流水，多笔记录按最新在前**。
- `tests/test_call_gateway.py`：MockGateway 形状；Alipay/Stripe stub 未配 key 503；webhook 坏签名 400（HMAC 手写验证与 PAYMENTS_PROGRESS T2 同款实现对拍）。
- H5 手测清单（dev_watch 起服后）：mock 全流程零网络可走通、中英切换、坐席台接听/挂断、到点自动结束双端同步、**覆盖层计时三要素正确、结束页显示结束时刻与实际时长、通话记录列表与明细正确**。

## 12. 配置新增（config.py + .env.example，键块注释对齐现有风格）

`call_db_url="sqlite:///data/call_state.db"` · `call_packages`（JSON，§3.1 默认）· `call_provider="mock"`（mock|alipay|stripe）· `call_hotline_number=""`（**坐席热线，tel: 一键拨号目标；空=direct 模式按钮降级为展示文案并引导 callback**）· `call_min_minutes=5` · `call_max_minutes=60` · `call_waiting_timeout_seconds=120` · `usd_cny_rate=7.2`（仅展示）· `agent_console_key=""`（空=坐席端点禁用）· `alipay_app_id/alipay_private_key/alipay_alipay_public_key/alipay_gateway=""`（stub 位）· `stripe_api_key/stripe_webhook_secret=""`（stub 位，与 PAYMENTS_PROGRESS 键名对齐，合并后共用）。

PG 化路径：`call_store` 表结构同时维护一份 alembic 草案（不动 0012，预留 0013），PG 上车日一次迁入；迁移前 SQLite 侧库为唯一事实源。

## 13. 本轮不做（后续轮次）

真实 WebRTC/telephony 语音桥 · 通话中 GLM 翻译（ASR 已有，叠加即「翻译坐席」卖点）· 员工账号/排班/话务分配 · 退款自助 UI 与对账导出 · 分钟有效期策略 · 会员/套餐折扣。

## 14. 实施顺序（review 通过后）

0. 建每 20 分钟续跑 automation（用户既定要求；完成自删）→ 1. 本文档转正 + INDEX.md 补行 → 2. call_store + call_service（含网关协议/mock）→ 3. api/call.py + main.py 注册 + config → 4. 三测试文件过门槛 → 5. tab-call + agent.html + i18n + sw v27 → 6. dev server 全链路手测 → 验收记录回写、删 automation、交付总结。
