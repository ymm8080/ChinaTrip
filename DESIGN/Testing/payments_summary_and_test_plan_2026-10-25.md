# ChinaTrip Payment Layer — Summary & Draft Test Plan（客户付款层 · 总结与测试草案）

> **Doc:** `payments_summary_and_test_plan_2026-10-25` · v1.0 DRAFT · 2026-10-25
> **Scope:** 客户付款层（company↔client payment collection）delivered on `feat/v24-trip-center`
> **Related:** `payments_design_2026-10-25.md` · `PAYMENTS_PROGRESS.md` · `paid_call_service_design_2026-10-25.md` §4

---

## Part 1 · Summary（总结）

### 1.1 What was delivered

A standalone **company↔client payment collection layer** — it does **not** touch the channel-booking handoff flow (铁律 22 unchanged; channel-side payments stay on 12306/Ctrip/Meituan). Two collection forms:

| Form | Use case | Outcome |
| --- | --- | --- |
| **pay_now** | Client pays a quoted amount immediately (service fee / one-off booking) | `succeeded` after hosted-checkout or mock confirm |
| **save_method** | Client saves a payment method once; operator charges later for concierge bookings（代订扣款） | `method_saved` with brand + last-4 label |

**Stack (all committed on `feat/v24-trip-center`):**

- **Service** `app/services/payments.py`: `PaymentStore` (in-memory dict + SQLite write-through `data/payments.db`, restart-safe, corrupt-row tolerant) · `PaymentGateway` protocol · `MockGateway` (offline fake checkout `/h5/?mockpay=<id>`) · `StripeGateway` (httpx REST: hosted Checkout `mode=payment`/`mode=setup`, off-session `payment_intents`, HMAC-SHA256 webhook signature verification — no new pip deps).
- **API** `app/api/payments.py` (router `/api/v1/payments`): `POST /checkout` · `GET /{id}` · `GET /mine` · `POST /{id}/confirm` (mock-only dev echo; 403 under non-mock backend) · `POST /webhook/stripe` (signature-verified, no device auth) · `POST /{id}/charge` (operator-only, `X-Operator-Token`; disabled when unconfigured).
- **Data**: `payments` table (PG parity via alembic `w12_0012`); amounts in **yuan float** (repo convention), cents only inside the Stripe adapter; every record carries `refund_summary`（铁律 23）.
- **H5** (`app/static/index.html` + `i18n.js`): 「💳 支付 / 代订收款」card in the booking tab — pay-now form (amount / currency cny·usd·eur / description / optional handoff link), save-card form, "my payments" bilingual status list, mock checkout sheet, return hooks (`?mockpay=` / `?pay_return=`), L3 order-intent auto-prefill of `handoff_id`.
- **Config** (`app/config.py` + `.env.example`): `PAYMENTS_BACKEND` (mock\|stripe) · `STRIPE_API_KEY` · `STRIPE_WEBHOOK_SECRET` · `PAYMENTS_DEFAULT_CURRENCY` · `PAYMENTS_SUCCESS_URL`/`CANCEL_URL` · `PAYMENTS_OPERATOR_TOKEN` (empty ⇒ charge endpoint disabled) · `PAYMENTS_DB_URL`.

### 1.2 Quality record（质量记录）

- **18 new automated tests** (`tests/test_payments.py`) all green: store round-trip / restart reload / corrupt-row skip · mock full flow · 5 validation cases · 5 signature cases · webhook event settlement (paid / setup / expired / refunded) · Stripe gateway payload & error mapping · API guards.
- **Full regression: 1,126 passed / 0 failed** · coverage **80.98%** (gate ≥75%; payments service 96%, API 88%) · `ruff check` clean.
- **Live smoke on dev :8000**: checkout → mock URL → confirm → `method_saved` (`pm_mock_4242`) → `mine` lists both records.
- Commits: `93550d7` checklist · `5496fc1` config · `72aa5c4` service · `efe6cb7` API · `8bbf96a` model+migration · `1f4526f` env · `b3382c5` tests · `d38f641` docs · `669e784` closeout · `058ce7a` channel decision.

### 1.3 Channel decision record（渠道决策）

| Channel | Status | Notes |
| --- | --- | --- |
| **Alipay wap direct（支付宝手机网站支付）** | **Production main channel — pending 个体工商户 qualification** | Sole registration needed (no foreign entity). Foreigners pay via Alipay wallet bound to Visa/MC/Amex/JCB (≤¥200 free / ~3% above, ~$5,000 cap). RSA2 signing will add the `cryptography` dependency (first new dep, when credentials arrive). |
| Visa/Mastercard direct acquiring | **CANCELLED (user decision, 2026-10-25)** | No overseas entity; card acquiring needs licensed cross-border PSP + company entity + ICP; highest chargeback/PCI/reserve risk. Not to be re-started without a new user decision. |
| Stripe hosted checkout | Built · **dormant reserved** | `payments_backend` stays `mock`; adapter activates only if `STRIPE_API_KEY` is configured (requires overseas entity). Zero runtime cost while dormant. |
| WeChat Pay merchant | Deferred | Same license as Alipay; second channel after Alipay proves out; needed for mini-program scenarios（故宫类预约）. |
| Concierge charging shape | **Per-order Alipay payment link preferred** | Saved-card charging (`save_method` + operator charge) stays dormant until a card PSP exists. |

### 1.4 Hard boundaries（恒挂红线）

- Raw card numbers / CVV **never** touch or persist on our servers (hosted tokenization only; hotel-style "card imprint" collection explicitly rejected — CVV storage is prohibited by card networks, PAN handling = full PCI-DSS scope).
- Refund summary（退改摘要）is shown before payment and stored on every record（铁律 23）.
- Operator charge endpoint is **disabled by default**; enabling requires `PAYMENTS_OPERATOR_TOKEN` and an agreed client agreement + reconciliation process.

---

## Part 2 · Draft Test Plan（测试草案 v0.1 — for review）

### 2.1 Environments & entry criteria

| Env | Config | Entry criteria | Covers |
| --- | --- | --- | --- |
| **E1 Mock/dev**（current） | `PAYMENTS_BACKEND=mock`, no keys, dev server via `dev_server.cmd` | None — works today | E2E flow logic, H5 UX, persistence, guards |
| **E2 Alipay sandbox** | `PAYMENTS_BACKEND=alipay` + sandbox `app_id`/RSA keys（pending 个体工商户 + 开放平台） | Adapter implemented; sandbox buyer wallet | Real wallet pay, async notify, refund notify |
| **E3 Production** | Real keys, `PAYMENTS_SUCCESS_URL`/`CANCEL_URL` = production domain, operator token set | E2 exit criteria met; client agreement + refund SOP written | Real money, reconciliation |

### 2.2 Automated regression — already passing（自动化回归，18 例）

| ID | Covers (tests/test_payments.py) | Status |
| --- | --- | --- |
| AUT-01 | Store round-trip + restart reload + account/device listing | ✅ Pass |
| AUT-02 | Corrupt DB row skipped without crashing | ✅ Pass |
| AUT-03 | Mock full flow: pay_now → confirm → `succeeded` + `paid_at` | ✅ Pass |
| AUT-04 | save_method → confirm → `method_saved` + label + pm ref | ✅ Pass |
| AUT-05 | Operator charge of saved method → new `succeeded` record | ✅ Pass |
| AUT-06 | Validation: missing/zero/oversized amount, bad currency, bad kind → 400 | ✅ Pass |
| AUT-07 | `confirm` rejected on non-mock gateway | ✅ Pass |
| AUT-08 | Webhook signature: valid / wrong / expired / malformed / empty secret | ✅ Pass |
| AUT-09 | Webhook settlement: completed(paid) / expired→canceled / setup→method_saved / refunded | ✅ Pass |
| AUT-10 | Stripe payload: `mode=payment`, `unit_amount=55300`, Bearer header, success/cancel URLs | ✅ Pass |
| AUT-11 | Stripe setup mode creates customer; pm describe → `VISA ••4242` | ✅ Pass |
| AUT-12 | Stripe off-session charge; missing saved method → 409; HTTP 402 → PaymentError | ✅ Pass |
| AUT-13 | API: mock E2E incl. missing device header → 400, 404 on unknown id | ✅ Pass |
| AUT-14 | API: `/confirm` → 403 under stripe backend config | ✅ Pass |
| AUT-15 | API: operator charge guard — no token / wrong token / disabled → 403; non-saved-method → 400 | ✅ Pass |
| AUT-16 | API: webhook signature reject 400 + valid sign 200 + record settled | ✅ Pass |
| AUT-17 | Default return URLs carry `pay_return=<payment_id>` | ✅ Pass |
| AUT-18 | yuan→cents conversion (553→55300, 12.5→1250) | ✅ Pass |

### 2.3 Manual UAT cases on H5 / E1（手工验收，待执行）

| ID | Title | Steps | Expected | Status |
| --- | --- | --- | --- | --- |
| UAT-01 | Pay-now happy path | 预订 tab → 💳 卡 → 类型=立即支付, 金额 553, CNY, 说明 → 去支付 | Mock 收银台 opens; 模拟支付成功 → toast; mine shows `已支付 Paid` | ☐ |
| UAT-02 | Save-card happy path | 类型=保存银行卡, email → 去支付 → confirm | mine shows `已存卡 Saved` + `Mock Card ••4242` | ☐ |
| UAT-03 | Refund display | (dev) webhook/refund event simulated | record flips to `已退款 Refunded` in mine | ☐ |
| UAT-04 | Cancel path | open mock sheet → 取消 | record stays `pending`（canceled only via expired event） | ☐ |
| UAT-05 | Validation UX | amount empty / 0 / negative → 去支付 | toast「请输入大于 0 的金额」, no API call | ☐ |
| UAT-06 | Return hook | visit `/h5/?mockpay=<id>` directly | mock sheet opens; after pay, URL params cleared (no replay on refresh) | ☐ |
| UAT-07 | Persistence | create records → restart server (`dev_server.cmd restart`) → my payments | records still listed（SQLite write-through） | ☐ |
| UAT-08 | i18n | toggle 🌐 EN / 中 on pay card | all pay labels/notes bilingual, badges consistent | ☐ |
| UAT-09 | L3 prefill | plan card → 抢票直达 (order-intent) | toast + `关联跳转单` input prefilled with handoff_id | ☐ |
| UAT-10 | Refund summary presence | open any payment row | 退改 summary line present（铁律 23） | ☐ |
| UAT-11 | Operator charge via API (dev) | `curl` `/charge` with/without `X-Operator-Token` | 403 without/wrong; 200 + new succeeded record with correct token | ☐ |
| UAT-12 | Rate limiting & auth sanity | rapid checkout calls; no token/anonymous device | 429 per config; device scoping intact（mine 只见本设备/账号） | ☐ |

### 2.4 Alipay wap acceptance — blocked on credentials（E2，资质到位后执行）

| ID | Title | Expected |
| --- | --- | --- |
| ALI-01 | Sandbox pay-now E2E | Checkout redirects to Alipay wap cashier; sandbox wallet pays; return to `pay_return` URL; record `succeeded` |
| ALI-02 | Async notify settlement | `trade_status=TRADE_SUCCESS` notify → RSA2 verify → record settled; idempotent on duplicate notifies |
| ALI-03 | Foreign-card path | Sandbox/bound intl card wallet payment succeeds; fee schedule noted in reconciliation |
| ALI-04 | User cancel at cashier | Return via cancel URL; record stays `pending`（或 canceled per notify `TRADE_CLOSED`） |
| ALI-05 | Refund notify | Merchant-console refund → notify → record `refunded` |
| ALI-06 | Signature/amount guards | Tampered notify → 400; amount mismatch → rejected + logged |
| ALI-07 | Currency & cap | cny default; usd/eur rejected or converted per final design decision |
| ALI-08 | Per-order payment link (concierge) | Operator sends link (prefilled amount/description/handoff) → client pays → both sides see same record |

### 2.5 Go-live exit criteria（上线出口条件）

1. AUT-01…18 green in CI; UAT-01…12 signed off on E1.
2. ALI-01…08 passed on E2 sandbox.
3. 个体工商户 license + 支付宝 wap product signed; production `PAYMENTS_SUCCESS_URL`/`CANCEL_URL` on the real domain; webhook/notify URL reachable over HTTPS.
4. Refund SOP + client agreement published（退改摘要文案 confirmed by business, 铁律 23）.
5. `PAYMENTS_OPERATOR_TOKEN` set only if saved-card charging is enabled; otherwise endpoint stays disabled.
6. Monitoring: payment failures & notify mismatches logged with trace ids (TraceIdMiddleware already stamps all requests).

### 2.6 Out of scope / known limitations

- No automatic refund orchestration engine（退款走商户后台/客服流程，状态经 notify 回写）.
- No invoices/receipts PDF; no multi-currency pricing beyond the currency field.
- Saved-card charging & Stripe adapter dormant (reserved code, zero runtime footprint).
- H5 files (`index.html`, `i18n.js`) intentionally uncommitted — they ride with the in-flight UI work of a parallel session; commit them together with that work.

---

## Part 3 · Open items（待办）

| # | Item | Owner | Blocked on |
| --- | --- | --- | --- |
| 1 | 个体工商户 registration → 支付宝开放平台 app + 手机网站支付 product | User | Business registration |
| 2 | Build `alipay_wap` adapter + notify verify + tests (+`cryptography` dep) | ZCode | Item 1 credentials |
| 3 | Production `PAYMENTS_SUCCESS_URL`/`CANCEL_URL` + operator token policy | User | Domain + SOP |
| 4 | Refund SOP + client agreement wording（铁律 23 customer-facing copy） | User | — |
| 5 | Delete 「支付功能施工续跑」 automation on Automations page | User | One click |
| 6 | Commit `index.html`/`i18n.js` alongside parallel-session UI work | Parallel session | Their feature commit |
