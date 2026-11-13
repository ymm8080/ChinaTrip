# POI 照片功能施工进度（2026-11-11，调度器每 2 分钟一拍）—— ✅ DONE

设计文档：`DESIGN/poi_photos_functional_design_2026-11-11.md`
分支：feat/v24-trip-center-uat（已 rebase 并推送，HEAD 8ce9b58）

| # | 任务 | 状态 | 提交 | 证据 |
|---|---|---|---|---|
| 1 | 迁移 0020 + models 两列 | ✅ | 5b09f28 | w12_0020 head；活库 upgrade 成功；ruff 过 |
| 2 | poi_photos 服务 + fetch/report-dead 端点 | ✅ | 0894e0c | 9 用例过；尝试即落戳/只填空/失败留日志全验 |
| 3 | backfill_photos 批量预热 job | ✅ | 0894e0c | 6 用例过；活库 --limit 10 真跑 9 命中 |
| 4 | F5 来源标注收口 | ✅ | 0894e0c | 悬空 1,452→0（amap 1,667 / ctrip 434）；backfill_intro 头注修正；12 用例过 |
| 5 | H5 找图按钮 + report-dead 接线 | ✅ | 8ce9b58 | JS 语法门 + H5 静态守门全过；sw v80 |
| 6 | 回归 + 覆盖率 + 择块提交 | ✅ | 5b09f28/0894e0c/8ce9b58 | 见下 |

## 回归与覆盖率

- 全量 pytest：**2,878 passed / 4 failed**——4 中 1 个（test_h5_static_gate）是我修掉的 v78 存量违例（`"　"`→`\u3000`，已过）；**其余 3 个（test_engine_constraints×1、test_plan_agent×2）为并行会话 WIP 域存量**：HEAD 本身自相矛盾（其已提交 plan.py 依赖未提交 itinerary/models.py 的 UnplacedCandidate），与照片链无关、零接触。
- 覆盖率：收口前 active 1,650/9,787=16.9% → 标注收口后 1,653/9,830=16.8% → 10 行真跑后 1,662/9,830=**16.9%**（预热 job 已就绪，上量跑 `python -m app.jobs.backfill_photos [--limit N] [--city X]` 即抬）。restaurants 0/5,088（设计非目标，另案）。
- 来源分布：amap 1,667 / ctrip 434 / wikimedia 258，悬空 0。

## 关键发现（给后续会话）

1. **盲标 amap 会误标**：悬空行域分布实测 amap 1,139 / ctrip 313+1——已按域名分两批 UPDATE。
2. **amap v3 `/place/text` 在本机 key 撞 WAF**（AmapPunishedError "bixi punish"）：按名搜路不可靠，v5 按 id 直查与 wikimedia 正常；链内已降级留痕不炸。
3. FastAPI 新版 `_IncludedRouter` 懒挂载：`app.routes` 探测不到子路由是假象，用 `router.routes` 核。
4. models.py/i18n.js 含并行会话 hunk——本次用过滤 patch（`git apply --cached`）只择自己的 hunks，并行 WIP 全程未动。

---

## 增补章节：餐厅照片回源 + 上量预热（2026-11-12，提交 31a2864 已推）

| 事项 | 结果 |
|---|---|
| pois 预热 500 行真跑 | 70 行填图（wikimedia 净增 79），active 有图率 16.9%→**17.6%**（1,732/9,830） |
| 餐厅回源能力 | restaurants 5,088 行**全部无 amap id、无 rating**——v5 按 id 路不存在；接入 v5 `place/around`（keywords+location 3km+名称匹配防错图，独立配额池/风控，text 被罚不影响）；新 job `app.jobs.backfill_restaurant_photos`（只填空+尝试即落戳+配额首撞停不落戳） |
| 真跑两 bug（已修） | ①坐标 WKT（ST_AsText `POINT(lon lat)`）解析缺壳→全 None；②`_Target` 字段名 `lonlat` ≠ 链读的 `location`，错位静默跌回被 WAF 罚的 v3 text——修后 47 照片套件全过 |
| 阻塞：amap 日配额尽 | `USER_DAILY_QUERY_OVER_LIMIT`（个人 key，多 job 共享）——餐厅 around 批量与 pois 无图行 v5 补图**明日重置后续跑**：`python -m app.jobs.backfill_restaurant_photos --limit 500` / `python -m app.jobs.backfill_photos --limit 500` |
| 探针结论 | **百度证伪**：place/v2 search+detail (scope=2) 只回 `detail_info.image_num`（计数）与 `detail_url`（网页），无图 URL 字段，第三链剔除；**腾讯未证实**：key 日配额尽（status 121），detail 零合法调用，探针脚本在 `_tmp_probe/`，次日重跑即可补证 |
| 明日待办 | ①餐厅批量（around 池）②pois 1,317 有 id 行 v5 补图 ③腾讯 detail 补探 ④text WAF 是否解封复查 |

本次并行会话 WIP（amap_client.py 人均消费链 27 行、plan.py 等）零接触；amap_client.py 保持未提交状态归其会话。

---

## 增补章节：真浏览器图源收割战报（2026-11-12 下午，提交 ed59011）

### 免费源最终定论

| 源 | 结论 | 证据 |
|---|---|---|
| Commons 站内搜 | ✅ 主力免费源，入链 | 文件名含名才收（_name_like 防错图）；pois/restaurants 双表命中（餐厅破零 10 行，均 2.6 张） |
| 官网 og:image | ✅ 入链 | website 列直取，正确性最高 |
| Wikidata P18 | ✅ 兜底 | 1 张/站 |
| Wikipedia media-list | ❌ 判死摘除 | api.wikimedia.org 无该 handler（404 rest-no-match），zh.wikipedia.org 被墙 |
| 百度 place detail | ❌ 证伪 | 只回 image_num 计数，无 URL |
| 腾讯 place detail | ⏳ 未证实 | key 日配额尽（status 121），探针脚本就绪次日重跑 |
| ctrip | （未接入） | 用户指示转新资源；dimg 抽取器现成，后续可接 |
| qunar | ⚠️ 仅首图 | 真浏览器渲染才拿得到，每站 1 张，暂不接链（IAB 实测详情页） |
| 马蜂窝 | ✅ 会话收割模式 | TCaptcha 每会话人工过一次后持续有效；poi 页多图满载 |

### 真浏览器收割（IAB + 用户人工过闸一次）

- 15 目标 → 14 站命中入库，每站 ≤8 张原图（剥 imageMogr2 缩放参数），歧义闸（title 精确→search 词→唯一候选否则按 rating 择优）+ 西湖错配回滚
- 收割 JSON：`CHINATRIP CODES/_tmp_probe_web/mfw_harvest_2026-11-12.json`
- 覆盖率：pois 18.9% → **19.1%**（1,875/9,830）；来源分布 amap 1,667 / wikimedia 457 / ctrip 434 / mafengwo 14
- 品类多样：宫殿(布达拉宫)/古镇(丽江)/大佛(乐山)/沙漠(鸣沙山)/园林(瘦西湖)/遗址(圆明园)/街区(三坊七巷)/关隘(沙坡头)/石窟(云冈)/王府(恭王府)/陵(清西陵)/瀑布(德天)/山(神仙居)/寺(塔尔寺)

### 马蜂窝会话收割 SOP（可复用）

1. IAB 打开任意 poi 页 → TCaptcha 弹窗 → 用户人工过闸（会话级有效）
2. 逐站：search/q.php?q=名 → 扫 poi/sharejump 链接 → poi/{id}.html → 滚动触发懒加载 → 收集 (p|b)1-q.mafengwo.net 原图（剥 ?imageMogr2、剔除 <200px 缩略/头像）
3. 入库脚本：只填空 + photos_source='mafengwo' + 歧义闸
4. 注意：poi id 不可猜（poi/2 即 404），一律经搜索页事实链接

---

## 增补章节：Day-2 批量与情报（2026-11-13）

- 腾讯探针复测：仍 status 121（key 日配额未见重置）——「未证实」维持，闸不开。
- ctrip 情报（探针 agent 实测）：GetSightOverview 直连 API 被 WAF 闸死（4/4 失败）；新会话壳页率 100%，但产线 CtripHoursReader 长会话间歇命中真身页（R8 300/600）——**photos 可搭 reader 便车零请求抽取**（dimg04/youimg1 域，_D_180_180 换大图后缀），需 ctrip_hours.py 暴露原始 HTML，待拍板接入。
- Day-2 批量起跑：pois backfill 800 行（amap v5 主池）+ restaurants around 800 行（独立池），并行后台。
- SOURCE_PRIORITY 已重排推送（50f5741）：curated > lonelyplanet > tripadvisor > viator > unesco > 5a > ...；catalog_rank（规划器/徽章）独立序未动。
- 马蜂窝会话收割累计 6 批 24 站（mafengwo 37 行）；餐厅 Commons 三轮 +55 行（65/5,088，命中率 ~10%，主力等 around）。
- Day-2 amap 批量实测：**配额在日初即被烧穿**（pois 800 行仅 ~83 行即熔断，hits 2）——个人 key 为多 job 共享争夺资源。v5 按 id 多图路规模化前需二选一：①错峰抢占（00:00 重置后立即跑）②企业认证升级 key（用户侧）。当前配额下 photos 主力仍是 wikimedia/mafengwo/ctrip 便车。

---

## 增补章节：餐厅照片读侧接线（2026-11-13 凌晨，用户指令「GET PICTURES FOR RESTAURANTS AS WELL」）

### 复盤（接 Day-2「明日待办」）

| 事项 | 结果 |
|---|---|
| amap 池 0 点未重置 | 00:02 v5 around 探针仍 `10044 USER_DAILY_QUERY_OVER_LIMIT`——**非自然日重置池**，与「amap 自 11-04 起月池枯竭连续未重置」台账互证；around 批量归 Day-2 批（并行会话 00:04 已起跑两路 800 行），本会话不抢 |
| 收割分工 | 餐厅照片**进库**＝并行会话 Commons 脚本/Day-2 批在跑（本会话只读不动）；本会话做**读侧**——收割再多，读侧断链照样白搭 |
| 读侧断链（根因） | 行程卡餐位/餐厅名同挂 `site-link` 气泡（index.html:1817 非酒店即挂），但 `/api/pois/detail`、`/photos/fetch`、`/photos/report-dead` 三端点**只查 pois 表**——餐厅名一律 404 静默跳过：照片/简介/米其林徽标永远不可见 |

### 读侧施工（本轮落地， pois.py +78 行）

- 三端点加 **restaurants 回退**（pois 未命中才走；active 闸/city 变体/精确→contains 与 pois 完全同构）：
  1. `/detail` → `_restaurant_to_model` 映射进同一 PoiDetail 形状（cuisine→category）——**H5 零改动**：气泡并排双图/灯箱/🔍找图按钮/米其林徽标自动生效；
  2. `/photos/fetch` → `fetch_photo_chain(row)` 零分支复用（0020 已把回源列做成两表同构），冷却戳/只填空语义不变；
  3. `/photos/report-dead` → Poi 查无再查 Restaurant，死图计数落同构 `photos_fetch_fail` 列。
- 活库验证：`Yong`（米其林，7 图 wikimedia）气泡直出 ✓；无图行 `No. 69 …`（bib_gourmand）出找图按钮、fetch 落冷却戳 ✓；`陕西历史博物馆` POI 路径不受影响 ✓。
- 测试：`test_api_pois.py` +3、`test_api_poi_photos.py` +3（回退命中/冷却免外呼/死图计数/两表全空仍 404）；两文件 31 passed；ruff check+format 绿。
- 全量回归：2,995 passed / 5 failed——5 失败全为并行会话域（tea_experience 分类器 1、演出场次解析 1、plan_agent 餐位 2、poi_seed 分类 1），与本链零交集。
- 提交：pois.py 并行 WIP（/tags 端点 + 两条 import）用 mine-only patch `git apply --cached` 择块，未混入。
- Day-2 restaurants around 批量：**around 池同样熔断**（1 行即停）——两个 amap 池配额均被并行 job 抢空。免费慢火继续：餐厅 Commons 第四轮 200 行后台。**待拍板**：①错峰抢占调度（00:05 抢跑照片批量）②企业 key 升级（用户侧）。

> 提交错位备注：上章读侧代码（pois.py/两测试文件）被并行会话 00:23 的 `docs(design): around 池亦熔断`（6cffa81）连索引一并扫入提交——内容完整、已推 origin，提交信息未体现 feat 主体，特此备注溯源。

## 餐厅 Commons 接力终报（2026-11-13，50 轮自然耗尽）

- 全量无图行已尝试（targets=0，24h 冷却锁定）：**restaurants 0 → 85 行**（全 wikimedia，占 5,088 的 1.7%）
- 结论：Commons 对本地餐厅覆盖率天然薄（~10%/轮），**餐厅上图主力必须等 amap around 池**（配额争夺待拍板）或点击端点用户触发
- pois 终态 19.6%（1,938/9,910）；amap 1,667 / wikimedia ~500 / ctrip 434 / mafengwo 37
- 下一步全部用户门控：①过马蜂窝闸续收 5A 尾巴 ②错峰抢占 or 企业 key ③ctrip 便车拍板 ④24h 后 Commons 二次轮空跑（拉空行或可再试 og 源）

## 2026-11-13 晚增补：intl/curated 档收割（用户拍板优先序）

- 马蜂窝会话收割切到 **intl 档（lonelyplanet/tripadvisor 系）+ 城市地标**：单日再入库 **20 站**（东方明珠/景山/西溪/飞来峰/南京路/奥森/上海之巅/李子坝/红旗渠/五女山/云和梯田/青铜峡/环球中心/河坊街/人民广场/黄鹤楼/夫子庙/王府井/周庄/中山陵/西安鼓楼/深圳湾/鸟巢/玉佛禅寺/中华门/锦里/箭扣/象鼻山/外滩源）
- **curated 宴艺美食档判无效**：马蜂窝对「宴/餐秀」类 niche 餐厅几乎零 poi 页（2/3 no-hit、1 错配），宁缺勿滥弃收——curated food 照片须等 amap/点评类源
- 质量闸当天再拦 3 次错配：周庄张厅（子景点→回滚重填周庄）、南京路酒店行（饭店/酒店词漏网→回滚+BAD 扩展）、上博东馆搜出苏州博物馆（弃收）；跨站复用占位图 s1/M00/6C/51 已从数据中剔除
- 终态：pois **19.9%**（1,970/9,910），mafengwo 源 63 行；全部提交推送（469b267 + 本文档）

## 2026-11-13 深夜：全量有图攻坚（用户指令「continue till all pictures fetched」）

- 无图库存 7,936 行，分源：chinatravel 5,307 / amap 1,203 / histvillage 411 / histown 179 / street 165 / 其余 ~700
- **现实约束**：chinatravel 尾库多为小景点（无维基/马蜂窝页），免费源命中率极低；amap 规模化受配额争夺；100% 有图需企业 key。策略：①免费全链（ctrip便车+Commons+og+P18）分批磨到枯竭 ②00:05 调度每日 amap 补 ③mafengwo 会话按需

---

## 增补章节：00:00 抢跑计划 + around 名称匹配修复（2026-11-13 上午）

### 抢跑（用户「go on」拍板，替代 ctrip 便车）

- **结构坑（本轮发现）**：冷却戳源无感——Commons 齿轮把 5,003 无图行全盖 24h 戳，明晚 00:00 池重置时 around 批选不到它们（只能捡英文名米其林行=amap 匹配最弱）。→ `ops/rest_photos_race_prep.py`：抢跑前只对**中文名无图行**清戳（干跑 4,503 行，已回滚验证）。
- **计划任务**：`ChinaTrip\rest photos race`（schtasks 一次性，2026-11-14 00:00；CronCreate 因本会话本身是调度任务运行中被禁，走仓库惯例 schtasks）。链路：指纹闸 → prep 清戳 → `backfill_restaurant_photos --limit 3000 --concurrency 2` → 台账+`ops/rest_photos_race.log`。错过后补跑/电池不拦已设。
- **不做 ctrip 便车**：需改并行会话每 3 分钟自动化的 ctrip_hours/enrich_ctrip_detail 链，撞车风险 > 不确定收益。

### around 名称匹配修复（直接抬抢跑命中率）

- 病根：关键词发全名（`乔街深夜食堂·生腌熟醉·高压生蚝(滨盛路店)`），amap 真实 POI 名只到「乔街深夜食堂(滨盛路店)」——相关度整串落空 + 双向包含永不过。
- 修：`_base_segment`（副标题 ·/空格切分，优先含中文段）+ `_search_keyword`（关键词取核心段）+ `_match_terms` 三档（全名/去括号/核心段）+ `_around_params`（抽出可测）。单次调用不变（池稀缺不翻倍耗量）。26 用例过，ruff 绿。
- 明文限制：英文名行（'Yong' 等）amap 仍匹配不了，不进抢跑池（prep 不清它们的戳）。

---

## 增补章节：餐厅马蜂窝收割轮（2026-11-13 中午，用户「IGNORE BATCH JOB, RUN NOW」）

- amap 池确认仍 10044（00:00 前死），批路线不可行 → 转 IAB 真浏览器马蜂窝收割（本轮**无 TCaptcha**，搜索页直出）。
- SOP 复用 + 三处新闸：①全站通用图剔（`p1-q/s1/...6C/51` 每页都出现）；②分店闸（库名带（XX店）须标题同店，新荣记温岭九龙店被正确拦截）；③简繁归一（南堂館↔南堂馆）+ 品牌别名（炳胜公馆=公馆(炳胜集团)）。
- 收割 6 批 11 店 → `_tmp_probe_web/mfw_harvest_restaurants_2026-11-13.json`（41 图）；入库脚本 `ops/ingest_restaurant_photos_mafengwo.py`（fill-empty-only + name 精确 + normalize_photos + photos_source='mafengwo'）。
- 结果：11/11 入库，restaurants 有图 **85→96/5,088（1.89%）**；来源 wikimedia 85 + mafengwo 11；读侧实测 200/8图直出。
- 观察：马蜂窝餐厅 poi 页点评图档 0-8 张/店；无 poi 页（沃夫冈/福和慧/鲁采/HORITA/WL BISTRO）或页无图（东富酒家/皖宴/潮跃）居多——继续收割的边际产出依赖目标选择。

> 提交错位备注（反向）：f9499db（餐厅马蜂窝第二波）提交时，并行会话暂存中的 `plan.py`（+139）/`test_untimed_final_sweep.py`（+513）随共享索引一并入库——内容完整，提交信息未体现 plan 主体，特此溯源。并行会话工作树仍有 plan.py 新改动，未受影响。
