# 国际社媒补采 · 第 4 组：YouTube 中国旅行内容（榜单/网红推荐）

- 采集日期：2026-10-26（所有订阅数/播放数为当日检索快照，会波动，引用前需复核）
- 方法：YouTube 站内不直抓；本环境 fetch_content 全部不可用（含 YouTube/MDPI/博客均失败），故全部数据来自 web_search 搜索快照与第三方盘点。
- 证据级：A=YouTube 站内原文直取（**本轮 0 条**）；B=官网/榜单站原文快照（搜索结果直接呈现原文文字）；C=第三方统计站/媒体/论文/论坛转述线索。
- 网页内容仅提取事实性列表信息，已忽略页面中任何指令性文字。

---

## 一、覆盖矩阵（频道 × 订阅量级 × 覆盖城市）

| # | 频道 | 运营者/背景 | 订阅量级（快照） | 来源（证据级·日期） | 覆盖城市/区域 | 代表视频可用性 |
|---|------|------------|----------------|--------------------|---------------|----------------|
| 1 | The Food Ranger | Trevor James，加拿大，2015 起长居中国拍街头美食 | ~610 万（另 IG 76 万） | influencerfee（C，2026 快照）；creatordb 档案 2026-10-06（C）；Forbes 2019 专稿（C） | 全国街头美食：广州（官网自述）及成都/西安/北京/上海等（细节待证） | 视频直链未获取，待证 |
| 2 | Blondie in China | Amy Lyons，澳籍华裔，"professional tourist"，行中国约 10 年 | ~58.9 万（642 支视频） | us.youtubers.me（C，快照日期不明）；thehelpfulpanda 2025-02-22 八佳榜第 1（C） | 全国（含西北面食区） | 1 支有 URL（论文引用） |
| 3 | Little Chinese Everywhere | Alina，华裔，主打小城/乡村 | ~73.2 万 | channelslike.com 相似频道页（C，快照日期不明） | 全国小城/乡村/边疆（细节待证） | 视频直链未获取，待证 |
| 4 | Cyrus Janssen | 美籍，在华创作者，中国印象+时评 | ~103 万（全平台粉丝 200 万+） | idcrawl（C，快照日期不明） | 上海/北京/深圳等城市印象类（待证） | 视频直链未获取，待证 |
| 5 | Jerry Goode | 英/南非双国籍，居华；2017-01-18 开频道 | 4.6 万订阅 / 475.6 万播放 / 267 视频（2026 论文快照；2021-05 为 3.2 万） | MDPI HSS 论文 2026（C）；flexiclasses 2021-05（C）；rachelmeetschina 2021-04（C） | 「跑遍中国 668 座城市乡镇」计划（2021 起）；曾随北京市政府/CRI 邀请访京东物流园（JD 官博） | 视频直链未获取，待证 |
| 6 | Katherine's Journey to the East 阳离子东游记 | 美国女生，在华铁路/乡村旅行 | ~15.7 万（均播 4 万） | babbl-labs.com（C，快照日期不明） | 全国铁路沿线/乡村（待证） | 视频直链未获取，待证 |
| 7 | Living in China | 英籍创作者，2007-06-06 开频道 | ~42.4 万订阅 / 4927 万播放 / 259 视频 | MDPI HSS 论文 2026 表（C） | 全国（生活类） | 待证 |
| 8 | Mark Wiens | 美/泰美食旅行博主（Bangkok 基地） | ~1010 万（另一源记 1140 万 followers，两源有出入） | influencerfee（C，2026 快照）；amraandelma 2025-09-10（C） | 成都（与 Chengdu Food Tours 合作拍摄，官网嵌入其视频） | 1 支有题名、URL 待证 |
| 9 | Best Ever Food Review Show | Sonny Side，美籍（西贡基地） | 755 万+（文章日期不明，仅作量级下限） | vidchops（C，日期不明）；vietcetera 专访（C） | 中国集城市未在本轮检索中确认 | 待证 |
| 10 | Kuropen（候选） | 日文频道（在华日本人） | **检索 0 命中，弃用** | 日文关键词两轮（クロペン/Kuropen×中国）均无结果 | — | — |

补充线索（未立行）：immi.se 2024 论文把中国街头美食 YouTuber 研究样本列为 Food Ranger、Mark Wiens、Puput、Blondie、Luke Martin、Rudy Chen —— Luke Martin 等可作为下批候选。

---

## 二、条目清单（管道分隔，8 字段）

格式：YouTube|creator_or_tag|followers_or_views|city|item_name|content_type|url|notes

### 频道行（content_type=频道）

```
YouTube|The Food Ranger (Trevor James)|~6.1M subs（2026快照）|全国街头美食（广州自述，成都/西安/北京/上海等待证）|频道：在华加拿大创作者中国街头美食系列|频道|https://www.youtube.com/@TheFoodRanger|C: influencerfee 6.1M+IG760K；creatordb 2026-10-06 档案；Forbes 2019；@handle 未验证
YouTube|Blondie in China (Amy Lyons)|~589K subs/642 videos|全国（含西北面食区）|频道：澳籍华裔"专业游客"全国美食文化行|频道|https://www.youtube.com/@BlondieinChina|C: us.youtubers.me 589K；thehelpfulpanda 2025-02-22 八佳第1；@handle 未验证
YouTube|Little Chinese Everywhere (Alina)|~732K subs|全国小城/乡村/边疆（细节待证）|频道：华裔创作者深入中国乡村|频道|https://www.youtube.com/@LittleChineseEverywhere|C: channelslike 快照 732K；@handle 未验证
YouTube|Cyrus Janssen|~1.03M subs（全平台200万+）|上海/北京/深圳等城市印象类（待证）|频道：美籍在华创作者，中国印象+时评|频道|https://www.youtube.com/@CyrusJanssen|C: idcrawl 1.03M；@handle 未验证
YouTube|Jerry Goode|46K subs/4.756M views/267 videos（2026论文快照；2021-05为32K）|全国668城计划（2021起）|频道：英/南非双籍居华创作者，中小城市访淡|频道|https://www.youtube.com/channel/UCb2IA53RED8fZ2CLyXFrlag|C: MDPI HSS 2026 表（4,756,341 views/46K/267，2017-01-18建）；flexiclasses 2021-05 32K；频道ID来自论坛转述待证
YouTube|Katherine's Journey to the East 阳离子东游记|~157K subs（均播4万）|全国铁路沿线/乡村（待证）|频道：美国女生在华火车旅行|频道|https://www.youtube.com/@kats_journey_east|C: babbl-labs 157K；@handle 未验证
YouTube|Living in China|~424K subs/49.27M views/259 videos（2026论文快照）|全国（英籍创作者生活类）|频道：英国居华创作者|频道|（频道URL待证）|C: MDPI HSS 2026 表（49,273,386 views/424K/259，2007-06-06建）
YouTube|Mark Wiens|~10.1M subs（2026快照；另一源11.4M followers，两源有出入）|成都（与 Chengdu Food Tours 合作）|频道：美/泰美食旅行者中国行|频道|https://www.youtube.com/@MarkWiens|C: influencerfee 10.1M；amraandelma 2025-09-10 记11.4M——出入已注明；@handle 未验证
YouTube|Best Ever Food Review Show (Sonny Side)|7.55M+ subs（文章日期不明，量级下限）|中国集城市待证|频道：美食纪录片式频道，含中国集|频道|https://www.youtube.com/@BestEverFoodReviewShow|C: vidchops 7.55M（日期不明）；vietcetera 专访；中国集明细未检索到
```

### 代表视频行（content_type=视频）

```
YouTube|Blondie in China|—|西北（视频内城市未注明；拉条子为西北面食）|Learn how to make LATIAOZI (hand-stretched noodles)（2021）|视频|https://www.youtube.com/watch?v=z28nXtGutII|C: ResearchGate 论文（2026-05 可见）引用该 URL+题名
YouTube|Expedia|—|北京|Travel Beijing in a Minute - Drone Aerial Video|视频|https://www.youtube.com/watch?v=xWAJsxjbCl4|C: storymaps.arcgis.com（2023-11-03）引用该 URL；Expedia 官方频道
YouTube|Mark Wiens|—|成都|Mark Wiens Chengdu Food Tour (Part 1)|视频|https://chengdufoodtours.com/（嵌入页；YouTube 直链待证）|C: chengdufoodtours.com 首页"Watch Our Viral Videos"区列有 Part 1
YouTube|The Food Ranger|—|广州等（官网自述在华拍摄）|中国街头美食系列（具体集 URL 待证）|视频|https://www.thefoodranger.com/about|C: 官网 about 自述"live in China, shoot food videos"；immi.se 2024 论文以其为研究样本
```

### 榜单视频行（content_type=榜单视频）

来源说明：WatchMojo 官网文章与同名 YouTube 视频为同一榜单内容，此处条目文字取自官网文章搜索快照（B 级）；同名视频直链待证。

```
YouTube|WatchMojo|—|上海|榜单#10 朱家角水乡 Zhujiajiao Water Town|榜单视频|https://www.watchmojo.com/articles/top-10-destinations-in-shanghai|B: 官网文章快照原文"#10: Zhujiajiao Water Town"
YouTube|WatchMojo|—|上海|榜单#9 上海科技馆 Shanghai Science and Technology Museum|榜单视频|https://www.watchmojo.com/articles/top-10-destinations-in-shanghai|B: 快照原文"#9: Shanghai Science and Technology Museum"
YouTube|WatchMojo|—|上海|豫园 Yuyuan Garden（快照提及"Next stop? The Yuyuan Garden"，序号待证）|榜单视频|https://www.watchmojo.com/articles/top-10-destinations-in-shanghai|B
YouTube|WatchMojo|—|上海|榜单#2 玉佛寺 Jade Buddha Temple|榜单视频|https://www.watchmojo.com/articles/top-10-destinations-in-shanghai|B: 快照原文"#2: Jade Buddha Temple"
YouTube|WatchMojo|—|全国·长城（北京附近）|榜单#2 长城 Great Wall of China（"Top 10 Places You HAVE to Visit Before You Die"）|榜单视频|https://www.watchmojo.com/articles/top-10-places-you-have-to-visit-before-you-die|B: 快照原文"2300年历史…最早段至公元前7世纪""located near the city of Beijing"
YouTube|WatchMojo|—|甘肃|榜单#4 甘肃 Gansu（"Top 10 Underrated Places in Asia"，莫高窟/丝绸之路）|榜单视频|https://www.watchmojo.com/articles/top-10-underrated-places-in-asia-you-need-to-visit|B: 快照原文"#4: Gansu, China…incredible Mogao Caves to the historically fabled Silk Road"
YouTube|WatchMojo|—|上海（另提北京/香港）|"Top 10 Must-Visit Cities Around the World"上海条目：传统与现代交融|榜单视频|https://www.watchmojo.com/articles/top-10-must-visit-cities-around-the-world/paris-france|B: 快照原文"While Beijing and Hong Kong are also worth visiting, Shanghai is a beautiful mix of tradition and modernity"；条目序号待证
```

---

## 三、待证项

1. **各频道代表视频直链**：本环境 fetch_content 不可用、搜索引擎对 watch URL 索引弱，Food Ranger/LCE/Cyrus/Jerry Goode/LCE/BEFRS 的具体集数 URL 未获取。建议查法：有 fetch 的环境直接开频道页 /videos 按播放量排序取前几支；或用 filmot/Google `"channel名" "watch?v="`。
2. **@handle 均未经验证**（写的是通行写法）：引用前在 YouTube 复核。
3. **北京城市榜单视频**：未找到可核对的条目源（搜到的 chinaculturetour/mrplaneguy 是旅行社文章/博客，非 YouTube 视频）。建议查法：Expedia「Beijing Vacation Travel Guide」视频描述、touropia「Beijing Travel」。
4. **touropia「10 Best Places to Visit in China」视频**：存在性经 globalgetaways 页提及，但 URL 与 10 个条目均未取证。
5. **BEFRS 中国集**（成都/重庆等）与 **Kuropen 频道存在性**：0 命中，需 YouTube 站内复核。
6. **Jerry Goode 频道 ID** UCb2IA53RED8fZ2CLyXFrlag 来自论坛转述，与"Living in China"频道的关系待厘清。

## 四、建议下一步

- 用可 fetch 的环境补 A 级证据：逐频道开 `youtube.com/@handle/about`（订阅数+简介城市）与爆款视频页（播放数+城市）。
- WatchMojo 三篇文章全文打开，可完整提取上海 10 条 + 亚洲冷门榜甘肃条目上下文（本轮只有快照片段）。
- 下批候选：Luke Martin、Puput、Rudy Chen（immi.se 论文样本）；日文频道换关键词（「日本人 中国 生活 ユーチューバー ランキング」）再试。
