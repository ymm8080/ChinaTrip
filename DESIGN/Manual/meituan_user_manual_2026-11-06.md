# Meituan User Manual — International Travelers (Unified Edition) 美团国际旅客统一使用手册

> 版本 v1.0 ｜ 2026-11-06 ｜ 归档：`DESIGN/Manual/` ｜ 语言：正文英文（可直接发给旅客）+ 中文团队注记（📌 编者注）
> 有效性：所有事实于 **2026-11-06** 核验（来源清单见 §8）。美团迭代快，如与 App 实际不符，以 App 为准并回改本文。
> 定位：**唯一权威版（unified）**——替代散落在各指南/会话里的碎片口径。CHINATRIP 侧的 handoff（`geo_split` 美团模板、铁律 22）与坐席话术统一引用本文，不再各自维护。
>
> 📌 编者注（团队）：本项目 `booking_design_2026-10-25.md` 已拍板 geo 分流——境内 IP → 美团模板、境外 IP → Trip.com。本文就是落到美团那一跳的旅客侧操作手册；支付发生在渠道侧（铁律 22：只 handoff 不代客交易），本文只教旅客怎么在渠道内完成。

---

## 0. TL;DR — pick your route in 30 seconds

| | **Route A: Meituan App** | **Route B: Alipay mini program** |
| --- | --- | --- |
| Interface language | ✅ App has built-in **English / 日本語 / 한국어 / 简体中文** switch | ❌ Mostly Chinese only |
| Chinese phone number needed | ❌ Overseas number works (+852, +81, +1 …) | ❌ Not needed — rides on your Alipay account |
| Payment | ⚠️ International cards: **partially supported, not guaranteed** | ✅ Pay with Alipay balance or card linked in Alipay (Visa/MC/Amex/JCB) |
| Best for | Settled-in travelers staying weeks+ | **Most short-term visitors — recommended default** |

**Recommendation:** start with **Route B** (works day one, no Chinese number, foreign card via Alipay). Switch to **Route A** if you stay longer and want the full English interface.

⚠️ **Golden rule for both routes: turn OFF your VPN.** Meituan blocks requests from foreign IPs and VPN exits — the app or mini program will fail to load or place orders.

---

## 1. What Meituan covers

Meituan is China's largest "everything local" platform. As a visitor you will use it for four things:

| Scenario | What it is | Typical use |
| --- | --- | --- |
| 外卖 Food delivery | Meal/grocery/pharmacy delivery in 30–60 min | Dinner at the hotel, late-night food |
| 到店团购 In-store deals (团购/买单) | Prepaid vouchers or direct pay-at-store discounts | 30–50% off at restaurants, spas, KTV |
| 酒店 Hotels | Domestic hotel booking, often cheaper than OTAs for CN chains | Budget/mid-range city hotels |
| 门票/演出 Attractions & shows | Tickets for scenic spots, exhibitions, shows | Same-day tickets when official channels sold out |

📌 编者注：CHINATRIP 行程侧的门票/演出 handoff 卡片（三通道并排：携程/美团/官方）落到美团时，对应的就是 §4.3 / §4.4 两个剧本。

---

## 2. Route A — the Meituan App (full experience)

### 2.1 Install

- **iOS:** App Store (China or international storefront both carry it — search "美团" or "Meituan").
- **Android:** Google Play carries the international build; in China, download the APK from the official site `meituan.com`.

### 2.2 Register with an overseas number

1. Open app → **登录 / Log in** → enter your **overseas phone number** (pick your country code from the dropdown).
2. Receive SMS code → set up the account.
3. Caveats (per Meituan's official user rules):
   - Some **security verifications or promotions may be unavailable** to overseas numbers.
   - If SMS never arrives → see §5.2, or fall back to Route B.

### 2.3 Switch the interface to English

Path: **我的 (Me/Profile) → 设置 (Settings) → 语言 (Language)** → choose **English / 日本語 / 한국어**.

Coverage reality check:

- ✅ Translated: main tabs, order flow, hotel/takeout/group-buy pages, help center.
- ❌ Stays Chinese: **merchant names, dish photos/menus, user reviews**, many merchant descriptions.
- Workaround for the Chinese parts: long-press to copy → paste into your translation app, or screenshot-translate (WeChat/Alipay both have built-in scan-translate).

### 2.4 Payment — the honest picture

- International cards (Visa/Mastercard) inside the Meituan app: **partially rolled out — some eligible non-mainland users can bind cards at qualifying merchants, but many reports say binding fails.** Do not plan around it.
- **Reliable in-app path:** bind international card to **Alipay** first (§3), then in Meituan App choose **Alipay 支付宝** as the payment method at checkout (this option appears for most orders; if it doesn't, use Route B).
- Fees: Alipay/WeChat charge ~**3% on transactions above ¥200** paid with foreign cards. Small orders are fee-free.

---

## 3. Route B — Alipay / WeChat mini program (no Chinese number, works day one)

### 3.1 Alipay route (recommended)

1. Install **Alipay** → register with your overseas number → **bind your foreign card**: *Me → Bank Cards / Cards → Add* (Visa / Mastercard / Amex / JCB; passport verification may be prompted).
2. On the Alipay home search bar, type **美团** (or "Meituan") → open the **美团 mini program**.
3. First entry authorizes login with your Alipay identity — no separate registration, no Chinese phone number.
4. Order as usual; at checkout the payment goes through **Alipay** automatically.

### 3.2 WeChat route (backup)

Same idea inside WeChat: search **美团** in the mini-program search. Works, but WeChat's foreign-user English support is weaker than Alipay's — use Alipay first.

### 3.3 What Route B gives up

- The mini program interface is **mostly Chinese** (no language switch) — rely on Alipay's English shell + scan-translate for merchant pages.
- Some app-only promos are missing. Prices for the same SKU are usually identical.

---

## 4. Scenario playbooks

### 4.1 Food delivery to your hotel (外卖)

1. Search cuisine ("pizza", "ramen") or paste a restaurant name (ask hotel staff, or get the Chinese name from a map app).
2. On the restaurant page check: **起送 (minimum order)**, **配送费 (delivery fee)**, **预计时间 (ETA)**.
3. Cart → checkout → **收货地址 (delivery address)**:
   - Paste: `[Hotel English name] + [hotel Chinese name] + [district]`, e.g. `Hotel Nikko Chengdu 成都日航酒店 锦江区人民南路二段` — add the **hotel Chinese name**; riders navigate by it.
   - In **备注 (note to rider)**: `请送至酒店前台 (please bring to hotel front desk)` + room number if allowed.
4. Pay (§2.4 / §3.1). Track on the map; the rider will call — a Chinese auto-dial from a translator app or just wait at the front desk.
5. Tip culture: none. Delivery fees are shown upfront.

### 4.2 In-store voucher (团购券)

1. On the merchant page pick a **团购 (deal)** → buy → you get a **券码 (voucher code)**, valid usually 30–90 days.
2. At the store, show the code (or say 团约) **before** ordering; staff scan it. Some places require in-app **到店核销** tap by their scanner.
3. Refund: unused vouchers are **随时退 (refund anytime)** in order details → 申请退款.

### 4.3 Hotels (酒店)

1. Search area/landmark → filter (price, rating, 免费取消 free cancellation).
2. Guest name: enter **exactly as on your passport**; passport is the check-in ID for foreigners.
3. Pay online or **到店付 (pay at hotel)** where offered. Bring the same passport to check-in.

### 4.4 Attractions & shows (门票/演出)

1. Many tickets are **实名制 (real-name)**: each ticket must be bound to a **passport number** — add travelers in the order form (证件类型 → 护照).
2. Entry is by the **passport itself** at the gate for most scenic spots; shows/e-tickets may need the in-app QR.
3. If a listing shows no passport option, that channel genuinely can't sell to you — fall back to the official mini program or Trip.com/Klook (the CHINATRIP booking card already geo-picks the right channel for you).

📌 编者注（与 `booking_design` 口径一致）：预约制馆（故宫类免费票）配额在官方小程序，美团查不到——旅客侧看到"无可售"不是 bug，是 L2 诚实返回 official_quota 的对应体验。

---

## 5. Troubleshooting / FAQ

| Symptom | Cause | Fix |
| --- | --- | --- |
| App won't load / search always empty / pay fails | **VPN on** | Turn VPN **off** completely (not split-tunnel), reopen |
| SMS code never arrives (overseas number) | Carrier filtering | Retry after 60s; try voice code; else use Route B (no registration needed) |
| Card declined at checkout | Meituan in-app intl-card binding not enabled for you | Pay via Alipay (§3) — bind card in Alipay, choose Alipay at checkout or use mini program |
| Merchant page all Chinese | Merchant content isn't translated | Screenshot-translate, or long-press copy → translate |
| "该商品不支持当前地区" / region-blocked item | Some SKUs are mainland-ID only | Same product is often bookable via Trip.com/Klook — ask in CHINATRIP chat, we re-route the channel |
| Rider can't find you | Address too vague | Re-check §4.1 step 3: hotel **Chinese** name + landmark; meet at front desk |
| Refund / dispute | — | Order detail → 申请退款 / 客服; Meituan in-app customer service responds in Chinese — hotel front desk or CHINATRIP support can assist |

---

## 6. Rules of thumb (print-worthy)

1. VPN off, always.
2. Short trip → Alipay mini program; long stay → Meituan App in English.
3. Foreign card lives in **Alipay**, not in Meituan.
4. Every address gets the hotel's **Chinese name** + "front desk" note.
5. Real-name tickets = passport numbers of every traveler, entered at purchase.
6. Prices are the same on App and mini program; don't chase promos you can't reach.

---

## 7. CHINATRIP integration (team only 📌)

- **Handoff 对应**：`geo_split` 判定为境内 → booking 卡片给美团模板 URL；本文 §4 即落地后的操作剧本，H5 帮助页可直接引用 §0/§4/§6（英文部分）。
- **铁律 22 不变**：本文只描述旅客在渠道内的自助操作；CHINATRIP 不代客在美团支付、不托管美团账号。
- **坐席话术引用**：旅客问"美团怎么用/为什么支付失败"→ 按 §5 表格逐行答复，勿即兴承诺国际卡直绑（§2.4 明确不可保证）。
- **维护约定**：美团侧事实变动（语言覆盖/支付政策/注册规则）→ 更新本文 §8 核验表日期，版本号 +0.1，INDEX.md 链接不变。

---

## 8. Validity & sources (checked 2026-11-06)

| Fact | Status | Source |
| --- | --- | --- |
| App multi-language UI (zh/en/ja/ko), takeout/hotel/group-buy covered | ✅ verified | [Google Play – Meituan listing](https://play.google.com/store/apps/details?id=com.sankuai.meituan) |
| Overseas phone number registration (with caveats on some verifications/promos) | ✅ verified | [Meituan rules center](https://rules-center.meituan.com/m/detail/guize/2); [journeytochina.org guide](https://journeytochina.org) |
| In-app international card binding: partial / not guaranteed | ⚠️ mixed reports | [Wise – Meituan guide (updated 2026-10)](https://wise.com/en-cn/blog/meituan-in-china); [chinatour.bswen.com (2026-04)](https://chinatour.bswen.com/blog/2026-04-24-meituan-food-delivery) |
| Alipay/WeChat linked foreign cards (Visa/MC/Amex/JCB) as the reliable payment path; ~3% fee over ¥200 | ✅ verified | [Trip.com Meituan guide](https://us.trip.com/guide/info/meituan-app.html); [Wise](https://wise.com/en-cn/blog/meituan-in-china) |
| Alipay 美团 mini program usable without Chinese number | ✅ verified | [traveltochina.net](https://www.traveltochina.net/guides/how-to-use-meituan-foreigner); [chinatour.bswen.com](https://chinatour.bswen.com/blog/2026-08-10-order-meituan-takeout-via-alipay) |
| VPN must be off | ✅ verified | [r/chinatravel reports](https://www.reddit.com/r/chinatravel/); [hiddenchinatravel.com](https://hiddenchinatravel.com/how-to-use-meituan) |
| Mini program lacks English switch (Chinese-only UI) | ✅ verified | [chinaguidelines.com – food delivery](https://chinaguidelines.com/en/posts/food-delivery) |

**Re-verify cadence:** quarterly, or upon any user report conflicting with this manual. Meituan has been iterating monthly for inbound users since 2025 — expect §2.4 to converge first (in-app intl cards).

---

*Next version candidates: v1.1 = H5 帮助页摘编版（仅 §0/§4/§6，纯英文，供前端直嵌）；v1.2 = 若美团开放国际卡直绑，改写 §2.4。*
