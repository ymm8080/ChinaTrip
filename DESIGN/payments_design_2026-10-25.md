# 客户付款层设计 — ChinaTrip（Payments Design，2026-10-25）

> 决策一句话：**公司↔客户的独立收款层——`pay_now` 立即支付 + `save_method` 存卡代订扣款（concierge），网关协议 mock 先行（零网络联调）、生产 Stripe hosted Checkout 或支付宝直连二选一；原始卡号/CVV 永不经服务器、不落库；铁律 22 渠道 handoff 完全不变，本层即收款豁免声明。**

> 关联文档：`DESIGN/PAYMENTS_PROGRESS.md`（施工清单与验收记录）、`DESIGN/paid_call_service_design_2026-10-25.md`（通话咨询复用本网关协议）、`DESIGN/booking_design_2026-10-25.md`（L3 下单意图/订单回填——渠道侧路径不变）、主设计 v2.5 铁律 0–23。

## 0. 与铁律的关系（豁免声明）

- **铁律 22（行动只 handoff 不代客交易）**：渠道侧订票（12306/携程/美团…）支付仍由用户在渠道完成，**一个字不变**。本层是「公司 ↔ 客户」的资金关系：公司作为服务方收款（服务费/代订垫付/通话咨询），不是替用户在渠道交易。与 paid_call 设计同款豁免处理。
- **铁律 23（退改摘要先行）**：每条 PaymentRecord 恒带 `refund_summary`（服务端默认文案 + 调用方可覆盖），H5 记录卡随卡展示。
- **合规红线（有意设计）**：**不代录、不存储原始卡号与 CVV**——酒店式「传真卡号担保」模式明确不做（CVV 事后存储被卡组织一概禁止；触 PAN 即 PCI-DSS SAQ D 全量审计）。存卡走 PSP token 保险库（hosted 页面 tokenization），服务器只见 token 与品牌+末四位，PCI 负担最小化。

## 1. 双形态

| 形态 | 场景 | 流程 | 终态 |
| --- | --- | --- | --- |
| `pay_now` | 客户按报价立即付款（服务费/单笔代订） | H5 表单（金额/币种/说明/可选关联 handoff_id）→ checkout URL → 托管收银台 → 回跳 `?pay_return=<id>` 前端轮询 | `succeeded`（webhook/confirm 落账） |
| `save_method` | 存卡供公司代订后扣款（5 星酒店式担保的合规等价物） | H5 表单（email）→ Setup Mode 收银台 → token 入保险库 | `method_saved`（存品牌+末4位标签） |

运营侧扣款：`POST /payments/{id}/charge`（`X-Operator-Token` 共享密钥守卫，未配置=整体禁用 403）→ 对已存 token off-session 扣款 → 生成新的 `pay_now` 记录（复制 device_id 归属，客户「我的付款」可见）。

## 2. 网关协议（可替换）

`PaymentGateway` 协议三方法：`create_checkout` / `charge_saved` / `describe_payment_method`。

| 适配器 | 状态 | 说明 |
| --- | --- | --- |
| `mock`（默认） | ✅ 已落地 | 假收银台 `/h5/?mockpay=<id>` + `/confirm` dev 确认（SMTP echo 同款豁免），**零网络全流程** |
| `stripe` | ✅ 已落地（待 key） | hosted Checkout（`mode=payment`/`mode=setup`）+ payment_intents off-session + webhook 验签；httpx 手写 REST 无新依赖。**启用只需 .env 填 `STRIPE_API_KEY`**（需境外主体：HK/US/SG…） |
| 支付宝直连 | 留位 | 个体工商户可开手机网站支付；外国游客 Visa/MC/Amex/JCB 可绑支付宝钱包（≤¥200 免手续费、以上约 3%，单笔上限 $5,000 量级）——见 paid_call §4 联网核查，走同一协议并列 |
| Airwallex 等跨境 PSP | 留位 | 同一协议替换；仅主体资质差异 |

Visa/MC 等外卡**不绑定 Stripe**：卡组织之上任选收单方，换网关只改一个 adapter。

## 3. 数据与 API

- 表 `payments`（迁移 `w12_0012`，PG 对齐）；热路径 = SQLite 写穿透 `data/payments.db`（state_persist 同款：内存 dict + 逐变更 upsert + 坏行跳过）。金额 **yuan float**（repo 惯例），cents 只在 Stripe adapter 内部换算。
- `POST /api/v1/payments/checkout`（X-Device-ID 必填，Bearer 可选）→ `{payment_id, checkout_url, status, refund_summary}`
- `GET /payments/{id}` / `GET /payments/mine`（设备+账号双归属去重）
- `POST /payments/{id}/confirm` —— 仅 mock 后端（stripe 配置下 403）
- `POST /payments/webhook/stripe` —— 无设备鉴权，`Stripe-Signature` HMAC-SHA256 验签（±300s 防重放、常时比较）；处理 `checkout.session.completed`（payment→succeeded / setup→method_saved）/ `expired`→canceled / `charge.refunded`→refunded
- `POST /payments/{id}/charge` —— 运营守卫见上；金额/币种/存卡三重校验（409 no_saved_method / 400 not_a_saved_method）

## 4. H5（预订 tab「💳 支付 / 代订收款」卡）

pay_now 表单（金额/币种 cny·usd·eur/说明/关联单号）+ save_card 表单 + 「我的付款」状态列表（pending/succeeded/refunded/method_saved 双语徽章 + 退改摘要随卡展示）。回跳钩子：`?mockpay=`（假收银台）/ `?pay_return=`（Stripe 回跳轮询，处理后清参防刷新重放）。booking-auto L3 下单意图成功后自动预填 `handoff_id` 并提示。i18n 键 `pay.*` 中英双语。

## 5. 测试与验收（2026-10-25）

- 18 例全绿：store 往返/重启重载/坏行跳过；mock 全流程（pay_now → succeeded；save_method → method_saved → 运营扣款 88/66.5 元）；参数校验 5 组；验签 好/坏/过期/畸形 5 组；webhook 事件落账 4 类；StripeGateway payload（mode/unit_amount=55300/Bearer 头/customer 建档/off_session）/错误映射（402→PaymentError、缺存卡→NoSavedMethodError）；API 守卫（缺设备头/confirm 403/operator 403×3）。
- 全量回归 1123+ 通过（1 例 plan_agent LLM-mock 偶发 flake 与本域无关，复跑即绿），覆盖率 **payments.py 96% / api 88% / 全仓 80.98% ≥ 75%**；ruff 干净。
- 实机冒烟（dev 8000）：checkout → mock 收银台 URL → confirm → method_saved（pm_mock_4242）→ mine 双记录可见。

## 6. 边界与诚实声明（恒挂）

- 默认 `PAYMENTS_BACKEND=mock`：未配置 Stripe key 前所有「支付」都是本地模拟，不产生真实资金流；上线前必须 (a) 注册收单方（Stripe 境外主体 / 支付宝直连）(b) .env 填 key + webhook secret (c) 生产 `PAYMENTS_SUCCESS_URL`/`CANCEL_URL` 配绝对域名。
- 运营扣款端点默认禁用（`PAYMENTS_OPERATOR_TOKEN` 空 ⇒ 403）；启用即代表公司承诺「代订后扣款」的客户协议与对账流程。
- 明确不做：代录/传真原始卡号、CVV 存储、把卡数据转发给酒店/渠道（卡组织规则禁止 + PCI 全量负担）；酒店若需卡担保，走酒店自己的安全通道或由客户直接提供。

## 变更记录

- 2026-10-25 v1：初版（pay_now/save_method 双形态 + mock/stripe 双网关 + 验签 + 运营扣款；T1-T7 落地，T6 H5 实机验收，T7 18 例 + 80.98%）。
