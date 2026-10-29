# 真人通话咨询 · 测试手册（Paid Human-Call Testing Guide）

> 2026-10-25 ｜ 对应设计 `DESIGN/paid_call_service_design_2026-10-25.md`（v1.2）｜ 施工清单 `DESIGN/paid_call_service_PROGRESS.md`（已 ALL COMPLETE）
> 每个场景标注：**[AUTO]** 自动化已覆盖（引用测试名，CI 可回归）｜**[MANUAL]** 需真人执行（双浏览器窗/真机/真实拨号）。
> 服务启动：`cd "CHINATRIP CODES" && .venv/Scripts/python ../scripts/dev_watch.py restart`（改 `.env` 后**必须**重启，配置不热载）；H5=`http://127.0.0.1:8000/h5/`，坐席台=`/h5/agent.html`。

---

## 1. 配置矩阵（.env 决定本轮能测什么）

| 配置 | 缺省（未配） | 配置后解锁 |
| --- | --- | --- |
| `CALL_PROVIDER` | `mock`（一键假支付，零网络） | `alipay`/`stripe` 需真实网关键（本轮不测） |
| `AGENT_CONSOLE_KEY` | 空 ⇒ 坐席端点 503、agent.html 无法登录 | 坐席台登录/接听/挂断（TC-02/03/05） |
| `CALL_HOTLINE_NUMBER` | 空 ⇒ 「立即拨打」模式自动降级为回拨（422 → 前端自动切换） | 直拨按钮 tel: 一键呼叫（TC-06） |
| 手机同 Wi-Fi 访问 `http://<电脑IP>:8000/h5/` | — | 真机 tel: 拨号体验（TC-06 真实形态） |

**清库重来**：停服后删 `CHINATRIP CODES\data\call_state.db` 再 restart（余额/订单/记录全清）。

## 2. 自动化覆盖 [AUTO]（1148 passed / 81.39% 已含）

| 用例组 | 文件 | 覆盖点 |
| --- | --- | --- |
| 存储层 | `tests/test_call_store.py` | 账本累加/原子扣减/不足拒绝、订单 provider_ref 幂等、会话列白名单、坐席队列排序、登录认领 |
| API 全链路 | `tests/test_call_api.py` | 买 10→直拨→接听→回拨 started_at 到点 exhausted 余额 0；提前挂断 3'30" 退 6 整分钟；waiting 超时全退；402/403/401/422/503 语义；设备隔离 404；records 起止时刻+mm:ss+分钟流水 |
| 网关 | `tests/test_call_gateway.py` | Mock 形状；支付宝/Stripe 键未配 503 provider_not_configured；webhook 幂等不重复入账 |
| 服务端冒烟 | `devlogs` + E2E 记录 | 2026-10-25 真实 HTTP E2E 12/12（见 PROGRESS 验收记录） |

回归命令：`.venv/Scripts/python -m pytest --cov=app --cov-fail-under=75`（全绿）+ `-m ruff check app tests`（干净）。

## 3. 手工场景 [MANUAL]

### TC-01 买分钟与余额（零配置即可测）
- **步骤**：H5 → 📞 咨询 → 点套餐「10 min · ¥16 / $2」
- **预期**：toast「购买成功 +10 分钟」；余额 chip 变 💰10；通话记录页上方订单状态 paid；中文环境按 ¥ 扣、切换 🌐 EN 后按 $ 显示
- **mock 语义**：不产生真实扣款；收银台 URL 型网关（配置真实键后）会改为新开收银台页

### TC-02 回拨全链路双窗（需 AGENT_CONSOLE_KEY）
- **前置**：`.env` 配 `AGENT_CONSOLE_KEY=test123` 并 restart；双浏览器窗：A=H5 旅客、B=`/h5/agent.html`
- **步骤**：B 输入员工键 test123 进入 → A 买 10 分钟 → 选 10 min + 「等坐席回拨」+ 手机号 → 「📞 实时通话」→ A 覆盖层「🟡 等待接听」→ B 队列出现该会话（显示号码 + tel: 外呼链接）→ B 点「✅ 接听」
- **预期**：A、B 同步变「🟢 通话中」；A 显示「开始时刻 · 已用时 · 剩余 09:5x」三要素且随轮询跳动；B 计时条同步；余额已划入会话=0

### TC-03 提前挂断退整分钟
- **步骤**：TC-02 通话进行到约 1~2 分钟 → A 点「挂断 / 结束」（或 B 点「⛔ 挂断」）
- **预期**：覆盖层变「⚫ 通话已结束」并显示结束时刻 + 实际时长 + 「↩️ 已退回 N 分钟」（N = 剩余整分钟，不足 1 分钟不退）；余额 = N；记录行原因「旅客挂断/坐席挂断」

### TC-04 waiting 120 秒无人接听全退
- **步骤**：A 开会话后**不接听**，等 120 秒（期间保持覆盖层开着轮询）
- **预期**：变「⚪ 未接通已退款」；余额全额返还；记录原因「未接通全退」；坐席台该会话消失（expired 不在队列）

### TC-05 到点强结（「付 10 分钟就聊 10 分钟」）
- **步骤**：TC-02 接听后**双方都不挂**，等满所选时长
- **预期**：到点瞬间 A、B 同步弹「⚫ 通话已结束」+ 原因「到点自动结束」；实际时长=所选分钟；**不退款**；B 蜂鸣黄色横幅提醒挂机

### TC-06 直拨（需 CALL_HOTLINE_NUMBER；真机最真实）
- **步骤**：桌面：A 选「立即拨打」开会话 → 覆盖层巨型「📞 立即拨打坐席」按钮 href=tel:热线；手机同 Wi-Fi 开 `http://<电脑IP>:8000/h5/` 重复上述
- **预期**：手机点击直接拉起拨号盘拨热线；坐席台显示「📲 旅客直拨呼入」并 >90s 黄色高亮；接听后计费与 TC-02 一致
- **核对点（诚实边界）**：到点后**系统只结束计费会话并双端强提醒**，物理通话需坐席挂机——退款摘要口径已写明「到点自动结束」

### TC-07 通话记录三要素与明细
- **步骤**：完成几通不同结局的通话后查看「通话记录」卡
- **预期**：最新在前；每条含日期时间（发起/接通）、mm:ss 实际时长、状态徽章（🟢⚫⚪）、直拨/回拨标注、结束原因、分钟流水（↩︎+退 / −耗）；点开明细可见接通/结束时刻与关联订单

### TC-08 中英切换与双币种
- **步骤**：点 🌐 EN 切语言后再走 TC-01/TC-06
- **预期**：全部文案切换（nav.call=📞 Call 等 30 键）；下单币种随环境自动 cny/usd；订单锁定下单时币种

### TC-09 边界与诚实语义
| 操作 | 预期 |
| --- | --- |
| 余额 5 分钟却开 10 分钟会话 | 402 `insufficient_minutes`，前端 toast |
| 时长 7/3/65 分钟 | 422 `invalid_duration`（5 的倍数、≤60） |
| 热线未配却点「立即拨打」 | 前端自动切「等坐席回拨」+ toast（API 422 `hotline_not_configured`） |
| agent.html 员工键输错 | 401 回登录页「员工键不正确」 |
| 未配 AGENT_CONSOLE_KEY 直接开 agent.html | 503「服务端未启用坐席台」 |
| 另一设备开同一会话链接 | 404（设备隔离，看不到别人会话） |
| 重复 mock 确认同一订单 | 余额只加一次（provider_ref 幂等） |

### TC-10 PWA 离线壳（sw v27）
- **步骤**：H5 正常访问一次后断网刷新
- **预期**：app-shell 缓存命中可打开（API 数据 NetworkFirst 回落）；`agent.html` 已入壳离线可开；应用图标更新无残留旧缓存（v26→v27 自动清）

## 4. 快速 curl 冒烟（不开浏览器验证服务活着）

```bash
curl http://127.0.0.1:8000/api/v1/call/packages          # 套餐目录
curl -H "X-Device-ID: t1" http://127.0.0.1:8000/api/v1/call/balance   # 余额
curl -H "X-Device-ID: t1" http://127.0.0.1:8000/api/v1/call/records   # 记录
curl http://127.0.0.1:8000/api/v1/call/agent/queue       # 未配键 ⇒ 503 agent_disabled
```

## 5. 验收记录（手测时填写）

| 用例 | 结果（✅/❌） | 执行人 | 时间 | 备注 |
| --- | --- | --- | --- | --- |
| TC-01 | | | | |
| TC-02 | | | | |
| TC-03 | | | | |
| TC-04 | | | | |
| TC-05 | | | | |
| TC-06 | | | | |
| TC-07 | | | | |
| TC-08 | | | | |
| TC-09 | | | | |
| TC-10 | | | | |
