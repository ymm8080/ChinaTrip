# 标签体系实施决策记录（2026-11-12）

- 背景：DESIGN/user_tag_two_level_2026-11-10.md 实施三步（二级 TAG / price_level / Review Tag）已完成；本轮为后续三件事（景点选择器接口、meal_periods、外部 review tags）的**拍板记录**。
- 数据来源侦察实证见对话记录 2026-11-11~12（探针明细）；本文件只记结论与执行路径，防止后人重探。

## D1 price_level：baidu place v2 scope=2 为唯一引擎（已实施）

- **实证**（2026-11-12 探针 3/3 命中）：detail_info 自带 `price`（人均 70.4/108.0/132.8）+ `classified_poi_tag` 类目链 + `shop_hours` + `overall_rating`。
- **决策**：`app/jobs/fill_restaurant_price.py` 重写为 baidu-only；amap 备胎移除（text 整族被 WAF deny、around 须坐标+熔断，性价比不值）；携程国内美食页判死不用。
- **纪律**（照 fill_hours_rating_driver 四条铁律）：fill-empty-only / miss 台账 `ops/fill_restaurant_price_missed.txt` / 302/401/402 首撞整批短路 / 名称双向包含复核。
- **状态**：机制验证通过（今日 baidu 池被 03:55 日批耗干 → 302 熔断如实生效），明日配额重置后续跑灌数。默认 --limit 20（≤40 次/轮，与日批礼貌共享 ~100/日池）。

## D2 餐厅 hours/rating：baidu 引擎顺车扩展（新决策，待实施）

- **背景**（meal_periods 代理实测发现）：`restaurants.opening_hours` **5088 行全 NULL**——baidu/amap/ctrip/show 富化链全部只写 pois 表，餐厅 hours 富化从未存在。meal_periods 回填今日 selected=0，机制就绪待喂。
- **决策**：baidu scope=2 对餐厅同样返回 `shop_hours`（探针实证 "10:30-22:30"/"10:00-07:00"）与 `overall_rating` → **扩展 D1 同一轮请求**（零额外配额）同时回填 restaurants 的 opening_hours + hours_source='baidu'；rating 按仓库口径（百度为实证源，×0.9 折算可选，后续拍板）。
- **产出**：改 `fill_restaurant_price.py` 为 `fill_restaurant_baidu.py`（一次请求收割 price+hours+类目），或并列任务共享同一请求——实施时定。
- **连锁**：hours 灌进来后 `python -m app.jobs.backfill_meal_periods` 即产 meal_periods（代理已交付，18+33+67 测试全绿，`_allowed_slots_for` 显式优先切换完成）。

## D3 meal_periods：机制完成，显式优先（已实施）

- 枚举 early_tea/breakfast/lunch/afternoon_tea/dinner/late_night；解析器（`app/services/meal_periods.py`）在 pois 真实语料验证 70.8% 解析率（baidu 58/58、ctrip 451/470≈96%），散文/季节日程正确拒绝不猜。
- `restaurants.py::_allowed_slots_for` 显式优先：行有 meal_periods 直接映射槽位（lunch ← {early_tea,breakfast,lunch,afternoon_tea}；dinner ← {dinner,late_night}），无值走原推断逐行不变。
- 待 D2 灌 hours 后跑 `python -m app.jobs.backfill_meal_periods`。

## D4 外部 review tags：trip.com moments POI 页评论正文规则抽取（拍板实施）

- **可行性裁决**（2026-11-12 侦察）：结构化点评标签通道**全部不存在**——携程国内美食列表/详情/dianping 子页 JS 壳（两家店同字节数 2,006,128 空壳）；trip.com `/restaurants/*` 404；toplist 1.9KB 壳；大众点评/美团反爬墙（仓库 11-03 已判）；baidu/amap 无评论标签字段。
- **唯一活口**：trip.com moments POI 页（如 `us.trip.com/moments/poi-jin-xuan-chinese-restaurant-16954049`，SSR 1MB 实证）评论**正文**富含场景词（「建議有重要約會或者紀念日來」「人均400+坐擁外灘夜景」）。
- **决策**：抓该页评论正文 → **关键词规则抽取**（不用 LLM，零配额依赖）→ restaurants.review_tags，`review_tags_source='trip'`：
  - 约会/纪念日/romantic → 约会氛围
  - 江景/夜景/河景/view/Bund/外滩 → 江景夜景位
  - 老字号/百年/老店 → 老字号
  - 深夜/凌晨/宵夜/late night → 深夜营业
  - 本地人/local → 本地人常去
  - 商务/宴请/business → 商务宴请
  - 家庭/带娃/kids/family → 家庭聚餐
  - 命中 ≥2 条独立评论正文才算（防单条噪声），阈值内不猜
- **先例**：11-11 网红餐厅补证调研已实际使用 trip.com 页作证据源；robots.txt 无 restaurant 限制。
- **URL 发现通道裁决（2026-11-12 探针）**：公开发现端点不存在——`/moments/searchlist`、`/moments/search` 404；`restapi/soa2 GlobalSearch` 403；搜索引擎无公开索引端点。POI 页 URL 形态 `trip.com/moments/poi-{slug}-{id}` 必须知道数字 id。
- **落地状态**：抽取器已交付 `app/services/trip_review_tags.py`（extract_prose + extract_review_tags，≥2 条独立正文命中才落标，繁简英同表，6 测试全绿）；**自动采集任务暂不建**——URL 发现走人工 seed（curated 76 行可逐步补 URL）或携程联盟 API 到位后再接，避免无发现通道烧探测请求。

## D5 景点选择器接口：物化列 + GET /pois/tags（✅ 完成，2026-11-12）

- 决策：pois 加 `user_family`(String50) + `user_groups`(JSONB) 物化列（alembic **w12_0022**，接 w12_0021），映射唯一来源 `app/services/poi_tag_selector.py`（7 一级/25 二级，DESIGN §一），回填 fill-empty-only。
- 回填实测：total=14291，**有标签 7707**，hotel/food/transport 排除 3900、category=None 排除 57、未命中留空 2627；每 poi ≤3 标签（1/5528、2/1468、3/711）；25 组全非零（自然山水 2768/历史人文 3081/亲子 591/滨海水上 529/园林街区 538/演艺夜游 197/休闲度假 3——末组数据薄，待 ctrip review_tags 增量）。
- API：GET `/api/pois/tags` 两级树带计数实测 200/342ms；group 过滤参数未加（现有 /search 委托 poi_details 引擎，后续接 user_groups 时一并做）。
- 已知噪声（模块 docstring 已记）：名字语素规则无类目门（渣滓洞→瀑布溶洞、云澜湾→海滨海岛类误判）——扩词表/加类目门为后续打磨项，不阻塞。
- 测试：15（新）+ 16/21（api 回归）+ 45（合并）全绿。

## 执行顺序（按本文件继续）

1. D5 代理收工验收（分布数字 + 测试）
2. ✅ D2：`app/jobs/fill_restaurant_baidu.py`（price+hours+cuisine 一轮收割，台账迁移 `fill_restaurant_baidu_missed.txt`）——baidu 配额重置后实跑；随后 D3 `backfill_meal_periods` 跟跑
3. ✅ D4：抽取器交付；自动采集等 URL 发现通道（人工 seed / 联盟 API）
4. 全链 DESIGN/user_tag_two_level_2026-11-10.md 实施状态区更新
