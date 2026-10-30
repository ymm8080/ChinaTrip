# MAP ENGINE DESIGN — 图商引擎与配额策略

- 日期：2026-10-30
- 状态：已落码（`map_provider.py` / `refresh_pois.py` / `poi_backfill.py` / `tencent_client.py` / `backfill_locations` / `agent/plan.py`），全量 pytest 1555 绿 + ruff 绿
- 决策人：用户（2026-10-23 / 10-27 / 10-29 / 10-30 四次拍板，见 §2 决策史）
- 关联：`app/services/map_provider.py`（工厂+优先级）、`app/services/refresh_pois.py`（链①②③④）、`app/services/poi_backfill.py`（回源升级）、`app/services/tencent_client.py`（第三兜底）、`ops/poi_refresh_daily.cmd`（夜间任务）

---

## 1. 结论速览

**POIS 表是唯一真相。** 页面/规划展示地址一律表读，零图商调用；图商只在「表里没有」时被调，产出一律 `upsert` 回表。图商调用按**功能分池、按富裕度排优先级、逐家配额 latch 降级**，不是某家通吃。

| 功能 | 优先级（先→后） | 依据 |
|---|---|---|
| POI 搜索（place search） | amap → tencent → baidu | 高德 5,000/月 > 腾讯 200/日 > 百度 ~100/日 |
| 逆地理 regeo（地址） | baidu → amap → tencent | 百度 regeo 池宽裕（10-30 单日 1300+ 次零熔断）> 高德基础 LBS 15万/月 > 腾讯 6,000/日 |
| 步行路线 | baidu → amap | 腾讯无 walking_route，不入链 |

缺 key 的层自动跳过；配额尽 latch 后逐行降级到下一家，**不重试不硬敲**。

---

## 2. 背景与决策史

| 日期 | 拍板 | 内容 |
|---|---|---|
| 10-23 | 宁缺勿错铁律 | 外部源骨架行仅名称/坐标/类别，不得当真相；回源升级需「名称相似度 + 距离」双闸 |
| 10-27 | 转百度 | 高德商用技术费 ¥50,000，前期小规模走百度个人免费配额；`map_provider` 工厂落成（amap\|baidu 双轴） |
| 10-29 | 月刷全面转百度 | `MAP_PROVIDER=baidu` 时 refresh_pois 不再直连高德，全走工厂 |
| 10-30 | 地址链重构 | 地址用百度；失败行回退高德；用户供腾讯 KEY 作第三兜底；44 行无城市行用正地理补城；**按功能按三家富裕度排优先级正式写进程序** |

---

## 3. 三家配额实测矩阵（口径与日期）

| 图商 / 功能 | 配额 | 口径 |
|---|---|---|
| 百度 place search | **~100–430/日**（10-28 补坐标烧尽一次、10-30 月刷后烧尽一次，两次实测熔断） | 个人认证；日配额 |
| 百度 regeo / 路线 | **宽裕**（10-30 单日 1300+ 次地址零熔断；偶发「并发量超限」为临时限速非日配额，暂停即恢复） | 个人认证；日配额 |
| 高德 search | **5,000/月 ≈166/日** | 官方配额页实抓 |
| 高德基础 LBS（地理编码/路径规划等） | **150,000/月**（regeo 10-30 单日 1,325 次零拒绝） | 官方配额页实抓 |
| 高德 WAF | QPS 超限返回 non-JSON 拦截页（bixi punish）——**限速非配额**，退避 1.5s 重试即可 | 10-30 实测 |
| 腾讯 place search | **200/日**（2025-03 个人额度调整后）；`region(全国)` 级个人 key 不可用（返回 121） | qcloudtx 配额表实抓 + 10-30 实测 |
| 腾讯 regeo / 路线 | **6,000/日** | 同上 |
| 腾讯正地理按名解析 | 质量差：POI 名常解出区县粗解（「漠河北极村景区」→「北京大兴区」）——**必须过名字闸**，否则拒绝 | 10-30 实测 |

> 经验值：日配额各家重置时点不同，任务侧**永远以 latch 信号为准**（客户端把「日配额尽」统一抛 `AmapQuotaExhaustedError`），不自己猜重置时间。

---

## 4. 正式策略：按功能优先级 + latch 降级

`map_provider.py`：

```python
FUNCTION_PROVIDER_PRIORITY = {
    "search":  ["amap", "tencent", "baidu"],
    "regeo":   ["baidu", "amap", "tencent"],
    "walking": ["baidu", "amap"],   # 腾讯无 walking_route，不入链
}
```

- `build_client_chain(settings, function)`：按优先级构建客户端链，**缺 key 自动跳过**。
- 每家客户端独立 latch：主源日配额尽 → 剩余行降级下一家；**兜底家的配额尽只停兜底，不中止主源循环**（别把下一家的池子整晚烧穿）。
- 腾讯 `TencentClient` **有意不进 map_provider 工厂**（deeplinks/导航/天气仍走 amap|baidu 双轴），只做地址富化的第三兜底；无 walking_route。

---

## 5. 数据流架构：POIS 表是唯一真相

### 5.1 读路径（用户可见的一切）＝纯表读，零图商
- `api/pois.py` `_COLS` 直接 SELECT `Poi.address` 等列；行程单 📍 读行程项自身 address 快照。
- 规划器地点解析先查库（`PoiDetailStore.search_keyword`），**库候选足够就不出门**。

### 5.2 写路径 A：夜间回填（refresh_pois，02:00 schtasks，`--match --limit 2500`）
链序（每行）：
1. **①携程先**（不同供应商，不占图商配额）：hours/时长/评分/门票。
2. **②图商 detail 直查**：仅当前 provider 命名空间的行（高德 ID / 百度 uid）；百度下 amap 行由高德 detail 兜底直查。
3. **③搜索兜底 + 降级链**：主源关键词搜索（首条）→ 空手/报错 → fallback 高德重试（quota latch 分家）。
4. **④地址兜底**：搜索链全空且行有坐标 → regeo 三层 baidu→amap→tencent（formatted_address 即门址；regeo 是独立配额池，place 熔断不影响本链）。
   - **④b 无城市且无坐标行**：腾讯正地理（`address=名称`，无需城市）→ 补 city + GCJ-02 坐标；title 与行名互含才采信。
   - **④c 无坐标行**：腾讯按名地点搜索补地址（城市在 ④b 后即有）——包含闸（归一化互含、短侧≥3 字）替代距离闸；命中顺带回填坐标，行此后即可参与距离闸升级。
5. **`--match` 骨架升级**（每轮前置）：source≠provider 的骨架行走图商关键词匹配 → 命中（相似度≥0.75 且距离≤500m）升级 `source→provider`、顺手回填 address/phone/rating/photos；命中后行进入 ②③④ 常规链。

护栏：
- **upsert 必须 `source=poi_source` 原位更新**——缺省 "amap" 会在骨架行上查无此行 → 新建幽灵重复行（10-30 实锤 +48 行，已合并置 inactive）。
- **miss 冷却**：未命中行盖 `hours_updated_at` 戳进 30 天静默，防每轮重复烧配额。
- **缺坐标行不烧搜索配额**（match 前置检查直接 miss）。

### 5.3 写路径 B：规划实时搜索（agent/plan.py `_search_poi` 链）
仅当库候选不够/用户点名表外景点时触发；**命中即 upsert 回表**——同一点下次就是表读。配额死在链内逐家降级，空手归占位。

### 5.4 坐标系铁律
库存统一 GCJ-02；各家换算收敛在客户端边界：高德 `lon,lat` 序；百度/腾讯 `lat,lng` 序且百度需 BD-09↔GCJ-02 换算；腾讯原样 GCJ-02 只调序。写 `location` 必须成对写 WGS84 副本（store.upsert 已封装）。

---

## 6. key 管理（.env，gitignored，服务端 only）

| 变量 | 状态（10-30） | 备注 |
|---|---|---|
| `MAP_PROVIDER=baidu` | ✅ | API 平面/规划器/天气/deeplinks/前端步行外链全跟随；**对运行中进程生效需重启 H5 任务** |
| `BAIDU_AK` | ✅ | 10-29 .env 重写时丢失，10-30 从 `D:\YMM\YMM ID & PW.docx` 找回 |
| `AMAP_API_KEY` | ✅ | 同次重写中丢失（曾是 10-28/10-30 高德链全灭 matched=0 的真因），同源找回 |
| `TENCENT_MAP_KEY` | ✅ | 用户直供；与 `TENCENT_BASE_URL` 配套 |

key 丢失教训：**.env 被模板重写时密钥全灭**——找回源固定记在 `D:\YMM\YMM ID & PW.docx`（百度地图/AMAP WEB 行）。

---

## 7. 遗留与后续

1. **~360 行无坐标骨架行**（5a 318 + show 45 等）待腾讯搜索配额重置后由夜间任务 ④c 自动补（2026-10-31 起）。
2. 冷门点 **角抵塚**（无城市无坐标）：④b 正地理质量闸可能拒绝——宁可留着，等人工确认位置或 ④c 按名命中。
3. **通济渠郑州段**：city=郑州 已确定性补（名字自带），地址待 ④c。
4. 若未来接入商用档：只需改 `FUNCTION_PROVIDER_PRIORITY` 顺序 + 补 key，链路零改动。

---

## 8. 实弹验证记录（10-30）

- 检索链 dry-run：三家真实降级路径全走通（tencent/baidu search 当日配额死 latch、baidu 补 1 行后死、amap 活但命中校验未过记 miss）。
- 地址回填实弹：单日 **3559/3988（89.2%）**（早间 43%），chinatravel 1681/1681 全量、unesco 81/83、高德 regeo 1,325 行、百度 regeo 425 行、腾讯 geocode/search 因当日配额尽自动 latch（零浪费）。
- 全量 pytest **1555 passed** + ruff 10 文件绿；8000/8443 两 H5 实例已重启带新 env（`/api/v1/amap/provider` → `{"provider":"baidu","ready":true}`）。
