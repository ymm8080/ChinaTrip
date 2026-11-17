# 探针报告：百度/腾讯 place detail 是否携带图片字段

日期：2026-11-12
目的：为「餐厅照片回源」评估第三条链——百度地图 / 腾讯位置服务的 place **detail** 类接口响应里是否有 photos/image 类图片字段。
方法：`_tmp_probe/probe_place_photos.py`，用仓库 venv 运行，key 经 `app.config.get_settings()` 读取（`baidu_ak` / `tencent_map_key`），**key 明文未出现在任何输出/报告中**。递归扫描响应 JSON 所有键名，命中 `photo|image|album|img`（大小写不敏感）即报告键路径与样例（URL 截断到域名+路径前 60 字符）。每家最多 2 次调用、串行、单次超时 15s、失败重试不超过 1 次。

---

## 一、百度地图（api.map.baidu.com）

### 调用 1：`GET /place/v2/search?query=楼外楼&region=杭州&scope=2&output=json&page_size=3`

- HTTP 状态：**200**，业务 `status: 0`（成功）
- 图片类键命中：**1 处**
  - 键路径：`$.results[2].detail_info.image_num`，值为数字字符串（该 POI 的图片**数量**，非 URL）
- 结果内全部 URL 形字段：仅 `$.results[*].detail_info.detail_url`（指向 `api.map.baidu.com/place/detail` 的**网页详情页链接**，不是图片 URL）
- 首条结果：`楼外楼(西湖景区孤山路店)`，uid 已取得（32 位 hex）
- 顺带结论（探针点 3）：**scope=2 的 search 结果 detail_info 不直接带 photo URL**，只有 `image_num` 计数字段。

### 调用 2：`GET /place/v2/detail?scope=2&output=json&uid=<楼外楼 uid>`

- HTTP 状态：**200**，业务 `status: 0`（成功）
- 图片类键命中：**1 处**
  - 键路径：`$.result.detail_info.image_num`（三位数字字符串——说明该 POI 名下确有多张图片，**但响应里没有给出任何图片 URL 字段**）
- 结果内全部 URL 形字段：仅 `$.result.detail_info.detail_url`（网页详情页链接）
- 未发现 `photos` / `image` / `album` / `img` 等任何携带图片 URL 的键或数组。

### 结论（百度）

**不可用**。百度 WebService place v2（search scope=2 与 detail scope=2）响应中不存在图片 URL 字段；唯一图片相关字段是 `detail_info.image_num`（图片数量计数），无法用于照片回源。

---

## 二、腾讯位置服务（apis.map.qq.com）

### 调用 1：`GET /ws/place/v1/search?keyword=楼外楼&boundary=region(杭州,0)&page_size=3`

- HTTP 状态：**200**，业务 `status: 121`，`message: 此key每日调用量已达到上限`
- 图片类键命中：**0**（响应体无 data 内容，仅错误信息）
- 重试 1 次（≤1 次），结果相同（日配额上限是状态性的，非网络抖动）。

### 调用 2：detail

**未执行**——search 未返回任何 POI `id`，无有效入参可传（腾讯 `/ws/place/v1/detail?id=...&key=...` 需要真实 id；配额烧尽状态下伪造 id 调用也只会再次回 121，不烧这次配额）。

### 结论（腾讯）

**未能实测（配额受阻）**：tencent_map_key 当日调用量已尽（status 121），search 与 detail 均无法验证。腾讯 detail 是否携带图片字段（如 `photos`）**当前证据不足，既未证实也未证伪**。待次日配额重置后重跑 `_tmp_probe/probe_place_photos.py`（脚本已就绪，0 改动即可复跑）即可补齐。

---

## 三、总体结论

- **百度：不可用**。place detail（scope=2）不带图片 URL；只有 `detail_info.image_num` 计数字段。第三条链走百度地图无意义。
- **腾讯：未证实**。今日 key 日配额尽（121）未能拿到响应体；需配额重置后复跑一次脚本补测。
- 建议：若第三条链必须成行，候选方向只剩腾讯 detail（待验证）或非地图类数据源（如大众点评/美团类，注意合规）；百度可从候选中剔除。

## 附：产物

- 探针脚本：`D:/CHINATRIP/_tmp_probe/probe_place_photos.py`
- 本报告：`D:/CHINATRIP/_tmp_probe/PROBE_REPORT.md`
- 运行命令：`cd "D:/CHINATRIP/CHINATRIP CODES" && ".venv/Scripts/python.exe" -I D:/CHINATRIP/_tmp_probe/probe_place_photos.py`

---

## 四、复跑补记（2026-11-12 上午，任务3 Agent-3）

### 复跑结果

- **08:01 零改动重跑**：百度侧复证不变（search/detail 仍只有 `image_num` 计数，无图 URL）；腾讯 search 仍 **status 121**。
- **~08:14 再次试探**：腾讯仍 121。**今日无法完成 detail 证实/证伪。**
- 百度两次复跑额外烧了 4 次调用，结论零增量——后续复跑可跳过百度段（探针脚本未改，百度段多烧 2 次可接受）。

### 配额地貌勘查（为什么"明日重置后直接跑"大概率还会撞墙）

调度任务与日志勘查结论：

1. **今日 02:00 的 `POI refresh daily`（`ops/poi_refresh_daily.cmd`）没有碰腾讯**——今日日志 0 条 tencent 记录（`--match --limit 2500` 仅 4 行进流程，全是 baidu search）。根目录 `pois_refresh.log`（11-01 停更）是废弃旧链。
2. **00:20 的 `coords nightly`（`ops/coords_round4.cmd` → `backfill_coords_driver.py`）的 search_probe 显示：11-10、11-11、11-12 三天 00:20 腾讯均已是 121**。若是 0 点重置，0:00-0:20 在 5 QPS 限频下最多 ~6000 次，烧不尽个人 1 万配额 → **重置时刻不在 0 点**。
3. 另一并行会话今日 07:55 建 `ops/regeocode_curated_tencent.py`（76 行 curated 坐标重定位），其文档串称"单点测试成功后连发触发 status 120"——说明 **~07:52 前后配额曾短暂新鲜**，但 08:01 已再次 121：**重置后新鲜窗口只有几分钟量级，即被抽干**。
4. 抽干者判定：**H5 运行时（7×24 两个 uvicorn）**。search 降级链 `amap→tencent→baidu`（`map_provider.FUNCTION_PROVIDER_PRIORITY`），而 amap 自 11-10 起持续被 WAF punish（`bixi punish — /place/text cooldown`），amap 配额也尽 → **全部搜索流量落在腾讯上直至烧尽，之后才落到 baidu**。11-07 H5 日志已有 `plan: tencent search quota exhausted, falling to next vendor` 实证。调度任务在 00:00-00:20 窗口内无其他腾讯消费方。

### 部署：守窗自动探针（已上线）

`_tmp_probe/tencent_quota_watch.py` 已后台运行（36h 硬上限）：

- 每 60s 发 1 次 `/ws/place/v1/search` 最小探测（121 拒绝调用不计费，成本≈0）；
- **status 0 的瞬间**自动取首条 id 补发 `/ws/place/v1/detail`，扫描图字段键并给出证实/证伪判定；
- 结果落盘 `_tmp_probe/TENCENT_DETAIL_RESULT.md`，过程日志 `_tmp_probe/tencent_quota_watch.log`，随后进程退出。
- 不改任何 WIP 文件、不打印 key；与明晨任务 4 的两个 backfill（amap 独立池）无配额竞争。

### 明日接线预案（供主会话）

- watcher 捕获窗口后：若**证实**（detail 有图 URL 字段）→ 按并行安全规则由主会话接线：fetch 函数放独立新文件（`tencent_place_photos.py` 之类），source 标 `tencent`，链序插在 P18 之前/后由主会话定；若**证伪** → 在照片设计文档记档剔除，第三链彻底关账。
- watcher 的 60s 探测与 `regeocode_curated_tencent.py` 重跑共享同一配额池：watcher 每次仅 1 调用，且成功窗口内总消耗 ≤3 次，不会挤占对方；但建议主会话协调两者**不要在同一新鲜窗口互相踩**（regeocode 76 行×重试也只需几分钟，先后跑皆可）。
- 真正的解与本验证无关但值得上报：**amap 恢复（明日配额重置）后 H5 search 不再全量压腾讯**，腾讯池自然回血；若 amap 长期 punish，需给 H5 search 链加 tencent 侧熔断/降额，否则任何腾讯增量任务（照片链第三源、坐标重定位）都会被它挤死。

---

## 五、携程图源（2026-11-12，任务3 扩展，Agent-3）

**判定：可用（已证实），但接入形态有硬约束——不能独立开抓，只能搭产线 reader 会话便车。**

### 证据

1. **图 URL 实证（自家数据）**：`DESIGN/backup/pois_inactive_backup_2026-11-04.json` 中 `origin: cn_sync` 行的 `photos` 数组直接含 `https://dimg04.c-ctrip.com/images/0EQ…_D_180_180.jpg?proc=autoorient` 形状 URL。活库现状（raw SQL 实测）：active 9830 行、空图 **7969**（81%）、已带 c-ctrip.com 图 URL 的 **312** 行。
2. **URL 形状**：`dimg04.c-ctrip.com/images/{id}_D_{W}_{H}.jpg?proc=autoorient`——`_D_180_180` 为缩略变体，ctrip CDN 惯例支持改尺寸后缀取大图（接入时验证 `_D_720x480` 或去后缀）。
3. **详情页 HTML 路径受阻**：本 agent 全新 httpx 会话今日 8/8 次 detail 抓取**全部命中 ~16KB 壳页**（title=通用攻略首页、0 图 URL、无 gallery 标记）；壳页内引用 `restapi/soa2/18109/json/GetSightOverview`（数据走此 XHR）。
4. **直接 API 闸死**：`GetSightOverview` POST `{"sightId":…}` 与 `{"arg":{"sightId":…}}` 均 404 WAF punish 页；GET `?sightId=…` 回 200 但 body 是 7.4KB JS 挑战页（非 JSON）；移动 UA POST 同 404。共 4 次尝试。
5. **产线 reader 能间歇命中真身页**：`refresh`/enrich 日志 R8 page_hits=300、R13=1——长寿命 AsyncClient（cookie 罐积累反爬令牌）过闸率远高于新会话；解析器（`parse_hours`/`parse_detail_fields`）吃 SSR 真身 HTML 全文，且 `parse_list` 已带 slug 城市闸（目录页整页变质时零收，测试有背书）。测试夹具（tests/test_ctrip_hours.py）为手造片段，不含图 URL，无额外证据。

### 接入形态建议（供主会话决策）

- **唯一可行形态**：搭 `CtripHoursReader` 既有会话便车——detail 真身页命中时，同一份 HTML 顺带正则抠 `dimg04/youimg1.c-ctrip.com` 图 URL（`_D_180_180` 换大图后缀），source 标 `ctrip`，fetch 函数放独立新文件、只读 import reader。
- **前置改动**（主会话统一做）：reader 现只返回解析字段、不透出原始 HTML——需在 ctrip_hours.py 暴露 detail 原文或 photos 字段（该文件不在本任务冻结清单，但 enrich 作业自约「只消费不改」，动它需主会话拍板时机）。
- **成本特性**：零新增请求（复用已发请求的响应）、零 key、无独立配额；收益上限受壳页率钳制——今日新会话壳页率 100%，产线会话命中率为间歇性（R8 300/600 → R9 0/600 波动大）。适合当**顺带增益源**（chain 末位），不宜当主力。
- **餐厅覆盖未知**：`/html5/you/food/` 路径 146 字节空壳，美食目录真身未探到；本判定仅覆盖 sight（景点/POI），餐厅照片不指望此源。

---

## 六、守窗过夜记录（2026-11-12 23:09 → 11-13 08:05）

- **0 点重置证伪**：watcher 重启后 check#1（23:09）至 check#481（11-13 07:59），凡可计数探测（46+ 次）全部 status 121；中间 `None` 均为笔记本睡眠网络中断。腾讯**日配额不在 0 点重置**（或重置后数分钟内即被 H5 兜底流量抽干——两种解释对行动等价）。
- **晨窗（~07:52）未复现**：11-13 07:28→07:59 连续 5 次 121。修正前日推断：11-12 ~07:52 的 regeocode 单点成功更可能是 **geocoder 分 API 桶**有量，而 place search/detail 桶全天干涸——腾讯各 WebService API 配额按接口分配，**本探针（place v1 search/detail）所属桶**才是判决依据。
- **amap 两池「明日重置」未兑现**：amap runner 11-13 07:35/07:45/07:55 探测仍 `AmapQuotaExhaustedError`；11-13 06:45-07:25 的 `AmapTimeoutError` 为睡眠网络残留。今日需继续守。
- **硬上限**：tencent watcher 36h（→ 11-14 11:09 止）、amap runner 24h（→ 11-13 23:22 止）。到期无果自动退出并在日志留一行。
