# 本会话开发内容 · 测试场景手册（2026-10-25）

> 覆盖 2026-10-25 监控会话交付：G1 预约提示 / G2 免签校验 / 互动闭环 / 雨天横幅 / 周更管道 / 数据底座。
> 每个场景标注：**[AUTO]** 已有自动化覆盖（引用测试名，CI 可回归）｜**[MANUAL]** 需真人执行（H5 浏览器流/定时任务/真实外部服务）。
> 环境：`.venv/Scripts/python -m pytest` 全量门禁；H5 手工场景起 `uvicorn app.main:create_app` 后访问规划页。

---

## 场景一：G1 预约制提示（故宫类门票）

### 1.1 行程卡片出现预约提示 [AUTO]
- **前置**：库中含「故宫」（或名单兜底命中）；规划上海→北京 2 天
- **步骤**：`PlanningAgent.start(cities=["上海","北京"], days=2)` 选点含故宫
- **预期**：`VisitItem.reservation_hint` 非空且含「提前 7 天」；假设区出现「预约提醒：…」
- **自动化**：`test_plan_agent.py::test_reservation_hint_from_seed_list`

### 1.2 dict 形态名单消费（对方 booking 接缝）[AUTO]
- **步骤**：`_reservation_hint("故宫", {})`（空候选走名单兜底）
- **预期**：返回文本含 `meta['days']`=7 与渠道备注；booking_auto 三档栈读同一份 RESERVATION_V0 无漂移
- **自动化**：`test_booking_auto.py`（全文件）+ seam 批次

### 1.3 H5 卡片手工核验 [MANUAL]
- **步骤**：规划页发起含故宫的规划 → 行程卡故宫条目下方
- **预期**：🎫 行显示「需提前 7 天预约（微信小程序「故宫博物院」每日 20:00 放 7 天后门票，护照可约）——外国手机号/护照在小程序常失败…」
- **核对点**：文案与 `reservation_seeds.py` 最新校订一致（不是旧版 8:00 放票）

### 1.4 名单兜底优先级 [AUTO]
- **步骤**：候选行 `reservation_advance_days=5` + 名单 7 天并存
- **预期**：库列优先（显示 5 天）；库列为空才落名单
- **自动化**：`_reservation_hint` 分支（plan.py:708-722，随 seam 批次回归）

---

## 场景二：G2 240h 免签校验（红/黄/绿三态）

### 2.1 绿：合规行程 [AUTO]
- **步骤**：`check_240h_transit(["上海市","杭州"], entry="2026-11-01", exit="2026-11-08", entry_port="上海浦东")`
- **预期**：`status=ok`、`stay_hours=168`、消息含联程客票提醒与「以边检为准」
- **自动化**：`test_visa_check.py::test_all_allowed_cities_within_hours_is_ok` + 端点回归

### 2.2 红：超时/禁省/禁市/口岸不在名单 [AUTO]
- **子用例**：
  - 停留 336h → fail 含「超过 240h」
  - 长春（吉林省不在 24 省）→ fail
  - 阿坝（四川省级范围外）→ fail 含「允许活动范围」
  - `entry_port="某小口岸"` → fail 含「不在名单」
- **自动化**：`test_overstay_fails_with_hours` / `test_disallowed_province_fails` / `test_city_scope_sichuan_shanxi` / `test_unknown_port_fails_but_names_are_snapshot_data`

### 2.3 黄：信息不全降级 [AUTO]
- **步骤**：只给城市不给日期
- **预期**：`status=warning`、`stay_hours=None`、含「停留时钟未校验」；港澳台城市 → 警告不 fail
- **自动化**：`test_missing_dates_warn_not_fail` / `test_unknown_city_and_non_mainland_warn`

### 2.4 快照完整性钉子 [AUTO]
- **预期**：65 口岸整（47空+14水+2铁+2陆）；贵州可动、哈尔滨映射黑龙江
- **自动化**：`test_port_table_is_full_65_including_land_rail_water` / `test_guizhou_in_scope_jilin_not`

### 2.5 H5 横幅手工核验 [MANUAL]
- **步骤**：行程卡载入含大陆城市的行程（start_date 已设）
- **预期**：顶部横幅——全 ok=绿底「✅ 240h 免签校验通过 · 停留 Nh」；含阿坝=红底列出不合规城市；缺日期=黄底提醒；恒附「以边检现场认定为准」
- **核对点**：城市过滤不含港澳（`filter(c => !["香港","澳门"].includes(c))`）

---

## 场景三：互动闭环（四按钮 + 批量导入）

### 3.1 👍/👎/打卡 [AUTO + MANUAL]
- **AUTO**：`test_feedback_api.py`（vote/visit 端点、poi_feedback store 计数、DB 失败静默降级）
- **MANUAL**：行程卡点 👍 → toast「已记录，谢谢反馈」、按钮变淡；点 ✅到了 → toast「已打卡」；重复点击幂等不报错

### 3.2 行后点评卡 [AUTO + MANUAL]
- **AUTO**：`test_feedback_api.py` review 端点（星级 1-5、REVIEW_TAGS 白名单校验、未知标签 422）
- **MANUAL**：点 ✍️点评 → 对话气泡出星级+9 标签 chips+一句话输入 → 提交 → 卡片变「✅ 已收到」；勾「外卡支付可用」「护照预订友好」等入境标签应被接受

### 3.3 批量链接导入 [AUTO + MANUAL]
- **AUTO**：`test_feedback_api.py` / links 端点（accepted/rejected 分拣）
- **MANUAL**：规划输入框一次粘 ≥2 条 URL → 自动进批量流「📥 批量导入 N 条链接（入库 X，坏链 Y）」逐条解析；单条解析失败不中断后续

### 3.4 离线可用（G5）[MANUAL]
- **步骤**：加载过 H5 后断网刷新
- **预期**：SW v24 外壳回退可开；最近一次行程数据从缓存回落展示

---

## 场景四：雨天对调横幅（8.1.4）

### 4.1 数据透传 [AUTO]
- **步骤**：库候选 rain_ok=no/yes 各一 → 规划
- **预期**：VisitItem.rain_ok 分别为 "no"/"yes"
- **自动化**：`test_plan_agent.py::test_rain_ok_passthrough_for_rain_banner`

### 4.2 纯函数建议句 [AUTO]
- **自动化**：`test_geo_cluster.py`（`rain_swap_advice` 有雨×露天→建议句；无雨/无露天→None）

### 4.3 H5 横幅 [MANUAL]
- **前置**：当日行程含 rain_ok=no 点位；当日天气预报含「雨」（可用 `/api/weather` 真数据或等自然降雨日）
- **预期**：天头下方蓝底横幅「🌧️ 预报有雨：X、Y 为露天点位（可与 Z 对调）——回复「雨天调整」可帮你重排」；次日无雨时横幅消失（wxSync 刷新重绘）
- **核对点**：多雨日多天各自独立横幅（`data-rain-day` 隔离）；替换卡片（拖拽/retime/钉住）后横幅重建

---

## 场景五：周更管道（预约规则全量核对）

### 5.1 五关校验 [AUTO]
- **用例**：合法规则通过；`advance_days=0/99/"7"` 拒、`release="25:00"` 拒、`source` 非 URL 拒
- **自动化**：`test_refresh_reservation_rules.py::test_gates_*`（4 用例）

### 5.2 mock 跳过 / dry-run 不碰表 [AUTO]
- **自动化**：`test_main_skips_on_mock_backend` / `test_main_reports_diff_and_skips_db_on_dry_run`

### 5.3 表行刷新 [AUTO]
- **步骤**：stub session 工厂 + name_zh=故宫命中行
- **预期**：`reservation_required=True`、`advance_days=7`、`booking_url=官方URL`
- **自动化**：`test_apply_db_updates_matching_rows`

### 5.4 真跑首跑核验 [MANUAL — 今晚 21:00 自动触发]
- **步骤**：schtasks「ChinaTrip_reservation_rules_weekly」触发后查 `devlogs/reservation_rules_weekly.log`
- **预期**：JSON 摘要含 `venues≈16`（17 减别名）、`errors` 少量可接受（单馆失败不拖批）、`DESIGN/reservation_rules_snapshot_2026-10-25.json` 落盘；`diffs` 非空时人工评审后改 `reservation_seeds.py`（作业不改码）；DB 中 `SELECT name_zh, reservation_advance_days FROM pois WHERE reservation_required` 出现命中行
- **附**：`--with-visa` 段 `match=true`（65 口岸数量对上）；不一致时 hint 指向人工核对

### 5.5 调度核验 [MANUAL]
- **步骤**：`schtasks /Query /TN "ChinaTrip_reservation_rules_weekly"` + 同法查 poi_stats_nightly
- **预期**：就绪状态、下次运行时间正确（周日 21:00 / 每日 03:40）

---

## 场景六：数据底座与回归闸门

### 6.1 露天属性端到端 [AUTO]
- `test_rain_ok_passthrough_for_rain_banner`（见 4.1）

### 6.2 评测集 P0 闸门（15 用例）[AUTO]
- **命令**：`pytest tests/test_engine_constraints.py`
- **覆盖**：同站不重复 / 每日≤4 裁剪 / 铁律 6 / 时间不重叠 / 库优先无占位 / 晚餐窗挂窗 / evening 开窗端到端 / 午休 gap 不排站 / 时链不缩水 / 预约 hint 不干扰求解
- **闸门语义**：任何引擎改动改红此文件 = 不可合入

### 6.3 迁移与库状态 [MANUAL]
- **步骤**：`alembic current` → `w12_0010 (head)`；查 `pois` 新列与 `poi_reviews`/`poi_stats` 表存在
- **预期**：与 0009/0010 一致（本会话已实测确认）

---

## 附：一键回归命令

```bash
cd "CHINATRIP CODES"
.venv/Scripts/python -m pytest -q                    # 全量（当前 1125+ 绿）
.venv/Scripts/python -m ruff check app tests         # lint
.venv/Scripts/python -m pytest tests/test_engine_constraints.py  # P0 闸门单独跑
```

---

## 场景七：booking 按钮 geo 分流（境外→Trip.com / 国内→美团，2026-10-25 第十四批）

> 实现：`services/geo_split.py`（XFF 首段 → APNIC CN 段表 `data/cn_ip_ranges.txt` 8,797 段判定，mtime 热更）；order-intent 服务端分流，前端零判断。**安全侧默认**：私网/回环/未知/段表缺失 → 一律境外侧（主要客户=外国人，宁绕国际站不错推国内站）。

### 7.1 段表判定 [AUTO]
- **步骤**：`is_mainland_ip("1.0.1.5")`（APNIC CN 委派段）/ `is_mainland_ip("8.8.8.8")` / 私网与 None
- **预期**：CN 段 True→meituan；海外/私网/回环/None/not-an-ip 全 False→tripcom
- **自动化**：`test_booking_auto.py::test_geo_split_mainland_vs_overseas`

### 7.2 XFF 首段优先 [AUTO]
- **步骤**：`client_ip("8.8.8.8, 10.0.0.1", "1.0.1.5")`（反代链路）与 `client_ip(None, "1.0.1.5")`
- **预期**：XFF 首段优先；无 XFF 退化 client.host
- **自动化**：同上用例

### 7.3 order-intent 端到端分流 [AUTO]
- **步骤**：同 body `{"name":"故宫","city":"北京","tier":"L3"}` 三次请求
  - XFF `8.8.8.8` → `geo_channel=tripcom` 且 authorization_url 含 trip.com
  - XFF `1.0.1.5` → `geo_channel=meituan` 且含 meituan.com
  - 带 `booking_url="https://mp.weixin.qq.com/x"`（无 XFF 头）→ URL 原样返回（**库列优先不被 geo 覆盖**）
- **自动化**：`test_order_intent_geo_routes_by_request_ip`

### 7.4 段表热更 [MANUAL]
- **步骤**：`echo "203.0.113.0/24" >> data/cn_ip_ranges.txt`（TEST-NET-3 文档段）→ 不重启直接打 API（XFF: 203.0.113.7）→ 验完删该行
- **预期**：立即 `geo_channel=meituan`（mtime 缓存键自动失效）；坏 CIDR 行跳过并 WARNING 不炸

### 7.5 H5 端到端 [MANUAL]
- **前置**：`uvicorn app.main:app --port 8000`；浏览器开 `/h5/` 规划页
- **步骤**：规划「北京 2 天」→ 行程生成 → 点故宫行「抢票直达 →」
- **预期**：
  - 新标签打开 Trip.com（**本机 127.0.0.1 = 境外侧默认——设计行为非 bug**）；toast 引导回填
  - 行程卡顶部同卡区：🎫 抢票日历金黄卡 + 免签红/绿横幅互不遮挡
  - handoff 留痕 opened（GET /api/v1/backfill 可查）
- **真实双网络**（可选）：国内手机热点 → meituan；境外 VPN → tripcom。**反代部署必查**：`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` 未配则恒走境外侧
- **Swagger 快验**：/docs → POST /api/v1/booking-auto/order-intent + XFF 头三次对比（7.3 同款）

### 7.6 排障 [MANUAL]
- 分流不符先查段表：`findstr "1.0.1." data\cn_ip_ranges.txt`
- 段表缺失（文件删了）→ 全部境外侧 + WARNING 日志（`geo_split: region file missing`）
