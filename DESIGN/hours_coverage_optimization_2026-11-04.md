# 营业时间覆盖率优化（2026-11-04）

用户指令：「HOURS coverage rate is too low. go to optimization」。

## 基线 → 当日结果

| 口径 | 会话开始 | 第一轮结束 | 高德 around 通道打通后 |
|---|---|---|---|
| active 有 opening_hours | 2,373 / 14,784 = **16.06%** | 2,495 / 14,783 = 16.88% | **3,667 / 14,783 = 24.81%** |
| hours_source='amap' | 122 | — | **1,294** |

第一轮 = 修 WAF 降级 + 变体匹配（+122）；第二轮 = 修「无坐标首行熔断」
后，amap `place/around` 连续 4 批 150 行 + 2 批 600 行稳定产出：
150 行批分别填 104/107/98/91/91；600 行批第一批 matched 462/600、
填 **410**（match 77%），第二批 matched 314/600、填 **267**（match 52%，
剩余行明显更难）。全程无配额/WAF 中断。

来源分布（active，hours_source）：amap 1,294 / ctrip 473 / baidu 150。

> 注：以上为本次会话实跑；日批任务每日会继续按此机制推进。

## 根因（按影响排序）

1. **amap text 端点整族被 WAF deny**（2026-11-03 起，bixi punish）。
   `search_hours` 原来只在 10021（配额尽）时降级 `/v5/place/around`，
   **WAF punish 不在降级条件里** → 每日 amap 引擎第一行就 `quota_stop=waf`，
   实际日产出为 0。实测 `/v5/place/around` 与 text 是独立风控/配额池，
   text 被 deny 时 around 仍正常返回（故宫博物院 opentime_week 实测成功）。
2. **每行按名称变体逐次检索，配额放大 3–5 倍**。5A/4A 名录长名（如
   「阿坝藏族羌族自治州九寨沟县九寨沟景区」）有多个变体，旧实现每个变体
   各发一次请求；no_match 行必须把全部变体试完。
3. **变体只剥一层行政区前缀**。旧正则对
   「黔南布依族苗族自治州荔波县樟江景区」只剥到「荔波县樟江景区」，
   县名仍在，回源必空。
4. **10002 SERVICE_NOT_AVAILABLE 未分类**：around 连发约百次后开始返
   10002，旧代码按普通 AmapError 逐行计数，整批 150 行继续敲死端点；
   且 302/配额类同样没有整批短路。
5. **日批 2 并发无间隔**，加剧 WAF/10002。

## 改动

### `app/services/amap_client.py`
- `search_hours`：text 遇 **10021 或 WAF punish** 且有坐标时都降级 around；
  降级成功后置 `_text_hours_disabled`（本轮粘住），后续调用**直接走
  around**，不再白敲被处罚的 text。
- 新增 `AmapServiceUnavailableError`（infocode 10002），三处状态解析统一
  分类，避免与普通错误混同。
- 新增 `search_hours_around_best(variants, location)`：**一次** around
  请求 `page_size=10` 取候选，本地按名称变体匹配；全名召回为空时用最短
  核心名再补一发（≤2 请求/行）。
- `_search_hours_around` 支持 `page_size` / `match_terms`。

### `app/jobs/enrich_baidu_map.py`
- `_variants` 重写：
  - 行政区前缀**逐层剥离**（自治州→县→…），每层都留变体；
  - 景区尾缀**可叠层剥离**（「世界雕塑公园景区」→「世界雕塑公园」→
    「世界雕塑」）；
  - 组合名分段后再剥尾缀。

### `ops/fill_hours_rating_driver.py`
- amap text 不可用时走 `search_hours_around_best`（单请求多变体匹配）。
- 10002 计入停批；配额/WAF/10002 首撞即 `asyncio.Event` **整批短路**，
  不再逐行重试死端点；只有已尝试的确定性失败行写 miss 台账。
- 10002 属短时限速：整批短路前先等 30s 重试一次，避免一次抖动打断整晚。
- **amap 选行强制要求坐标**（`Poi.location IS NOT NULL`）。这是 11-04
  下午实盘抓到的单点熔断：队列首行「海南省博物馆」无坐标，text 又已被
  WAF 封，`search_hours` 直接抛 punish 把整批 150 行带走（0 产出）；
  无坐标行本轮本就走不了 around，过滤即可。`_process_one` 另加
  `loc_str is None + text 已死 → skip` 的兜底（不写台账，坐标补上后可重入）。
- 新增 `--delay`（请求间隔），amap 日批默认 1 并发 + 0.7s。

### `app/services/amap_client.py`（第二批）
- 请求头从仅 UA 升级为浏览器式 `User-Agent + Referer + Accept +
  Accept-Language`，降低 place 族 WAF 命中率。

### `ops/poi_hours_rating_daily.cmd`
- amap 段改为 `--concurrency 1 --delay 0.5`。

## 当日实跑（amap engine）

| 批次 | 选中 | matched | 写入 opening_hours | 结束原因 |
|---|---|---|---|---|
| 修复前 03:55 日批 | 150 | 0 | 0 | WAF（text 不可用，无 around 兜底） |
| 修复后 60 行（首 60 高优先） | 60 | 12 | 11 | 正常结束 |
| 清台账后重试 40 行（同一批硬名） | 40 | 3 | 2 | 正常结束 |
| 后续 60 行 | 60 | 40 | 32 | 正常结束 |
| 后续 150 行 | 150 | 84 | 77 | around WAF（冷却后自动恢复） |

## 百度配额现状（同日核查）

- `.env` 的 `BAIDU_AK` 与 `BAIDU_MAP_KEY` 是**同一个 key**（32 位，值相同）。
- 今日**地点检索日配额已尽**：`status=302 天配额超限，限制访问`（零点重置）。
  03:55 日批约 47 行（≈74 次请求）后触发；06:11 手动冒烟再试，仅 5 行即 302。
  与 `DESIGN/MAP ENGINE DESIGN.md` 记录的「place search ~100–430/日」一致，
  当日池约百次量级。
- **地理编码/逆地理/路线是独立配额池且宽裕**（历史单日 1,300+ 次不熔断），
  所以地址与坐标回填不受此限；被卡住的只有「地点检索」这一个服务。
- 配额按行摊：旧实现逐名称变体各发一次检索，no_match 行最贵（台账统计
  约 1.5 变体/行 → ~65 行/日）。本次已改为**一行一次检索取 20 个候选 +
  本地变体匹配**（未召回再用核心名补一发，≤2 次/行），同等配额下
  预计行数提升约 30–50%。
- 真正的量级杠杆仍是**百度企业认证**（设计文档估 ×10）：12,388 行缺口
  从约 6 个月缩短到约 3 周，属用户侧动作。

## 结构性上限（未变）

amap 个人 key 搜索池约 5,000/月（≈166 请求/日），按当前命中率
（约 50–60%，受行难度影响）≈ **50–100 行/日**。其余增量仍来自
baidu 日批（~100 次/日）与 ctrip PoC（9 城、量小）。
要把 12,388 行缺口在数周内吃下，仍需开发者认证/企业档或换源；
本次优化解决的是「每日配额被 WAF 归零」和「配额浪费」两个问题。

## 验证

- `tests/test_amap.py`：新增 WAF→around 降级、无坐标不降级、text 粘住、
  多变体单请求匹配、10002 专用异常 5 例。
- `tests/test_enrich_variants.py`：新增多层前缀/叠层尾缀/短名保持 3 例。
- `pytest tests/test_amap.py tests/test_baidu.py tests/test_ctrip_hours.py
  tests/test_poi_details.py tests/test_plan_agent.py` → **230 passed**。
- `ruff check`（6 个改动文件）→ 全绿。

## 运维注意

- around 被 WAF/10002 打下后**冷却数十分钟~数小时自动恢复**；日批
  首撞即停，次日续跑，无需人工干预。
- miss 台账 `ops/fill_hours_rating_missed_amap.txt` 记录已确定性失败的
  行；若后续改了匹配逻辑想重试，先备份并移走该文件。
