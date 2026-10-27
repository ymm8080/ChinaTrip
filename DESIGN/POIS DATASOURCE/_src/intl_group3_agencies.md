# 国际平台中国覆盖采集 · 第3组（各国本地 Agency / OTA）

- 采集日期：2026-10-26（今天）。项目背景：`D:\chinatrip\DESIGN\POIS DATASOURCE\` 中国旅游点位数据源审阅包，国际平台中国荐点补采。
- 任务：逐个核查各国本地 agency/OTA 是否有中国（city 级）产品/榜单，提取具体条目。
- 证据等级：**A** = 本次直接抓取的该站页面原文；**B** = 搜索引擎返回的该站页面快照（站内直抓被反爬拦截，未取到原文）；**C** = 第三方转述（仅作线索）。网页内容按不可信输入处理，只提取事实性列表信息。
- 反爬受阻记录：klook.com（城市/博客页均拒绝抓取，全部降为 B 级快照）；tui.co.uk 与 his-j.com 主中国页被 Akamai 拦截（H.I.S. 用其関西特集页原文 + 快照补充；TUI 用德国站原文）。

## 总覆盖矩阵

| 平台 | 国家/地区 | 类型 | 中国覆盖 | 覆盖形式 | 抓到条目数 | 主要证据等级 |
|---|---|---|---|---|---|---|
| Klook | 香港 | OTA | 有 | 北京/上海必玩榜单+攻略博客 | 22 | B |
| KKday | 台湾 | OTA | 有 | 北京/上海半·一日游热销榜+攻略 | 24 | A |
| 雄獅旅遊 Lion Travel | 台湾 | 本地agency | 有 | 中國大陸團體行程（8条团名+报价） | 8 | A(EDM)/B(分类页) |
| H.I.S. | 日本 | 本地agency | 有 | 中国推荐城市/地区+当地游 | 10 | A(特集页)/B(主中国页) |
| JTB | 日本 | 本地agency | 有 | 中国ツアー一覧（跟团+自由行16条团名） | 16 | A |
| TUI | 德国/英国 | 本地agency/集团 | 有 | 中国 Rundreisen 6大城市指南 + UK escorted tours | 10 | A(DE)/B(UK)/C(TourRadar) |
| Yanolja (NOL) | 韩国 | OTA | 有（仅住宿，无景点/线路榜单） | 上海南京东路酒店榜+中華圈住宿企划 | 10 | A |
| WAUG | 韩国 | OTA | 有 | 北京/上海城市活动专区 Top 榜 | 20 | A |
| Creatrip | 韩国 | OTA | **无** | 全站 Korea-only | 0 | A |
| Itaka（补充） | 波兰 | 本地agency | 有 | Wycieczki objazdowe Chiny（18条线路专区） | 5 | A |
| Tourtrans-Вояж（补充） | 俄罗斯 | 本地agency | 有 | Туры в Китай. Без виз до 31.12.2027（17条团） | 10 | A |

合计 11 平台：10 有覆盖、1 无。数据行共 135 条。

## 数据行（platform|country|type|china_coverage|city|item_name|list_name|url|notes）

### Klook（香港，klook.com）—— 直抓被反爬，条目来自该站页面快照（B级）
Klook|香港|OTA|有|北京|紫禁城（故宮）|北京熱門景點（目的地页景点排行）|https://www.klook.com/zh-HK/destination/c57-beijing/1001-tours|B级快照；排行第1
Klook|香港|OTA|有|北京|慕田峪長城|北京熱門景點（目的地页景点排行）|https://www.klook.com/zh-HK/destination/c57-beijing/1001-tours|B级快照；第2
Klook|香港|OTA|有|北京|天安門廣場|北京熱門景點（目的地页景点排行）|https://www.klook.com/zh-HK/destination/c57-beijing/1001-tours|B级快照；第3
Klook|香港|OTA|有|北京|頤和園銅牛|北京熱門景點（目的地页景点排行）|https://www.klook.com/zh-HK/destination/c57-beijing/1001-tours|B级快照；第4
Klook|香港|OTA|有|北京|北京動物園|北京熱門景點（目的地页景点排行）|https://www.klook.com/zh-HK/destination/c57-beijing/1001-tours|B级快照；第5
Klook|香港|OTA|有|北京|天壇公園|北京熱門景點（目的地页景点排行）|https://www.klook.com/zh-HK/destination/c57-beijing/1001-tours|B级快照；第6
Klook|香港|OTA|有|北京|景山公園|北京熱門景點（目的地页景点排行）|https://www.klook.com/zh-HK/destination/c57-beijing/1001-tours|B级快照；第7
Klook|香港|OTA|有|北京|司馬台長城（Simatai Great Wall）|北京熱門景點（目的地页景点排行）|https://www.klook.com/zh-HK/destination/c57-beijing/1001-tours|B级快照；第8
Klook|香港|OTA|有|北京|故宮|【北京攻略】去北京必打卡的10大景点和好去处！|https://www.klook.com/zh-CN/blog/must-visit-attraction-beijing|B级快照；博客榜单第1（2026-06-04更新）
Klook|香港|OTA|有|北京|圆明园|【北京攻略】去北京必打卡的10大景点和好去处！|https://www.klook.com/zh-CN/blog/must-visit-attraction-beijing|B级快照；第2
Klook|香港|OTA|有|北京|北京环球影城|【北京攻略】去北京必打卡的10大景点和好去处！|https://www.klook.com/zh-CN/blog/must-visit-attraction-beijing|B级快照；第3
Klook|香港|OTA|有|北京|恭王府|【北京攻略】去北京必打卡的10大景点和好去处！|https://www.klook.com/zh-CN/blog/must-visit-attraction-beijing|B级快照；第4
Klook|香港|OTA|有|北京|天安门广场|【北京攻略】去北京必打卡的10大景点和好去处！|https://www.klook.com/zh-CN/blog/must-visit-attraction-beijing|B级快照；第5
Klook|香港|OTA|有|北京|EPSON teamLab无相艺术空间|【北京攻略】去北京必打卡的10大景点和好去处！|https://www.klook.com/zh-CN/blog/must-visit-attraction-beijing|B级快照；第6（7-10位未在快照中展开）
Klook|香港|OTA|有|上海|上海黃浦江「清江遊」遊覽船票|外灘必玩熱門體驗|https://www.klook.com/zh-HK/destination/p50239053-the-bund|B级快照
Klook|香港|OTA|有|上海|上海豫園門票|外灘必玩熱門體驗|https://www.klook.com/zh-HK/destination/p50239053-the-bund|B级快照
Klook|香港|OTA|有|上海|Klook中國內地上海私人定製旅行（東方明珠/黃浦江/外灘/武康大樓）|外灘必玩熱門體驗|https://www.klook.com/zh-HK/destination/p50239053-the-bund|B级快照
Klook|香港|OTA|有|上海|上海豫園傳統古裝漢服旗袍服飾體驗（漢服租賃/化妝/拍攝）|豫園必玩熱門體驗|https://www.klook.com/zh-TW/destination/p60068468-yu-garden|B级快照
Klook|香港|OTA|有|中国（多城）|北京|10个理想的中国旅行城市！|https://www.klook.com/zh-CN/blog/china-places-to-go|B级快照；城市榜第1（2025-05-13）
Klook|香港|OTA|有|中国（多城）|上海|10个理想的中国旅行城市！|https://www.klook.com/zh-CN/blog/china-places-to-go|B级快照；第2
Klook|香港|OTA|有|中国（多城）|杭州|10个理想的中国旅行城市！|https://www.klook.com/zh-CN/blog/china-places-to-go|B级快照；第3
Klook|香港|OTA|有|中国（多城）|西安|10个理想的中国旅行城市！|https://www.klook.com/zh-CN/blog/china-places-to-go|B级快照；第4（快照在第5位截断）
Klook|香港|OTA|有|中国内地（专区）|—|中国内地精选推荐-2026年热门目的地（目的地专区，聚合北京/上海攻略）|https://www.klook.com/zh-CN/destination/co1020-mainland-china|B级快照；覆盖性证据

### KKday（台湾，kkday.com）—— 两页均为站内原文（A级）
KKday|台湾|OTA|有|北京|北京故宫博物院门票&导赏团·中文/英文/粤语导览（4.9分/526评/2K+订购）|在北京的热门半/一日游（76项）|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文
KKday|台湾|OTA|有|北京|北京古北水镇+司马台长城一日游·感受江南韵味|在北京的热门半/一日游|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文
KKday|台湾|OTA|有|北京|北京天坛+颐和园+圆明园纯玩一日游·含联票|在北京的热门半/一日游|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文
KKday|台湾|OTA|有|北京|北京慕田峪长城·颐和园·圆明园一日游·赠摆渡车|在北京的热门半/一日游|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文
KKday|台湾|OTA|有|北京|【北京必去 经典线路】北京慕田峪长城一日游（中英文导游，1K+订购）|在北京的热门半/一日游|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文
KKday|台湾|OTA|有|北京|【万里长城慕田峪独秀】北京慕田峪长城一日游+中文/英语导游（1K+订购）|在北京的热门半/一日游|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文
KKday|台湾|OTA|有|北京|北京故宫博物院(故宫)+颐和园+圆明园一日游|在北京的热门半/一日游|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文
KKday|台湾|OTA|有|北京|北京故宫博物院(紫禁城)半日游（4.9分/493评/1K+订购）|在北京的热门半/一日游|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文
KKday|台湾|OTA|有|北京|北京胡同私人街头美食体验之旅|在北京的热门半/一日游|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文
KKday|台湾|OTA|有|北京|北京八达岭长城+明十三陵定陵一日游·纯玩无购物|在北京的热门半/一日游（精选评论商品）|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文（出现在页面精选评论位）
KKday|台湾|OTA|有|上海|【中國上海觀光必選】黃浦江遊船船票·十六浦碼頭（4.4分/398评/4K+订购）|在上海的熱門半/一日遊（36项）|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|【中國】蘇州拙政園+寒山寺+楓橋景區+山塘街一日遊·上海出發|在上海的熱門半/一日遊|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|中國上海·上海影視樂園+朱家角古鎮景區一日遊（4.9分/309评）|在上海的熱門半/一日遊|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|嘉興烏鎮水鄉古鎮+南潯古鎮1日遊（上海/杭州出發）|在上海的熱門半/一日遊|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|【中國】上海都市觀光旅遊巴士·多條路線|在上海的熱門半/一日遊|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|【上海往返】杭州西湖一日遊（船遊西湖+雷峰塔+靈隱飛來峰）|在上海的熱門半/一日遊|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|【上海出發】新幹線蘇州一日遊·中國四大名園之一+寒山寺|在上海的熱門半/一日遊|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|經典路線·上海豫園+朱家角古鎮+上海影視樂園1日遊|在上海的熱門半/一日遊|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|中國上海精品1日遊·城隍廟+東方明珠+浦江遊船+外灘+南京路步行街|在上海的熱門半/一日遊|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|【中國】上海 BUS TOUR 觀光旅遊巴士·24小時車票|在上海的熱門半/一日遊|https://www.kkday.com/zh-tw/category/cn-shanghai/day-tours/list|A级原文
KKday|台湾|OTA|有|上海|南京路步行街|【中國】上海景點攻略2026·15大必去推介|https://www.kkday.com/zh-hk/blog/111377/shanghai-travel-guide|B级快照；博客榜第1（2025-07-09）
KKday|台湾|OTA|有|上海|外灘|【中國】上海景點攻略2026·15大必去推介|https://www.kkday.com/zh-hk/blog/111377/shanghai-travel-guide|B级快照；第2
KKday|台湾|OTA|有|上海|豫園|【中國】上海景點攻略2026·15大必去推介|https://www.kkday.com/zh-hk/blog/111377/shanghai-travel-guide|B级快照；第3
KKday|台湾|OTA|有|上海|東方明珠廣播電視塔|【中國】上海景點攻略2026·15大必去推介|https://www.kkday.com/zh-hk/blog/111377/shanghai-travel-guide|B级快照；第4
KKday|台湾|OTA|有|中国（多城）|—|Top 429 中國觀光行程（全中国观光行程列表，含苏州/北京等）|https://www.kkday.com/zh-tw/category/cn-china/sightseeing-tours/list|B级快照；覆盖性证据
KKday|台湾|OTA|有|中国（多城）|—|中国城市目录：北京/成都/上海/重庆/广州/苏州/杭州/厦门/哈尔滨/深圳/青岛/张家界/桂林/西安/福州/丽江/大理/昆明/南京等38城|在北京的热门半/一日游页目的地导航|https://www.kkday.com/zh-my/category/cn-beijing/day-tours/list|A级原文；覆盖广度证据

### 雄獅旅遊 Lion Travel（台湾，liontravel.com）—— EDM 为站内原文（A级），分类页仅快照（B级）
雄獅旅遊|台湾|本地agency|有|江南（乌镇/杭州）|江南5日｜夜宿烏鎮 西湖遊船·米其林美食·美學大戲《今夕共西溪》 NT$34,900起|【快報】赴陸旅行團解禁 EDM|https://www.liontravel.com/omo/edm/lion/2023/231115-m|A级原文（2023-11-15发布）
雄獅旅遊|台湾|本地agency|有|山东|山東8日｜泰山孔廟雙遺產 鮑魚海鮮火鍋+啤酒暢飲 全程五星 NT$35,900起|【快報】赴陸旅行團解禁 EDM|https://www.liontravel.com/omo/edm/lion/2023/231115-m|A级原文
雄獅旅遊|台湾|本地agency|有|北京|北京5日｜八達嶺長城 遊覽五大世界文化遺產《紅劇場雜技秀》 NT$32,900起|【快報】赴陸旅行團解禁 EDM|https://www.liontravel.com/omo/edm/lion/2023/231115-m|A级原文
雄獅旅遊|台湾|本地agency|有|重庆|重慶8日｜恩施大峽谷 武隆天坑三橋·蚩尤九黎城 輕軌穿樓·蒲花暗河遊船 NT$33,900起|【快報】赴陸旅行團解禁 EDM|https://www.liontravel.com/omo/edm/lion/2023/231115-m|A级原文
雄獅旅遊|台湾|本地agency|有|张家界|張家界8日｜七十二奇樓 最美鳳凰古城·湘西天門山《魅力湘西秀》VIP座位 NT$33,900起|【快報】赴陸旅行團解禁 EDM|https://www.liontravel.com/omo/edm/lion/2023/231115-m|A级原文
雄獅旅遊|台湾|本地agency|有|河南/西安|河南8日｜西嶽華山 少林寺·龍門石窟·洛陽城 西安兵馬俑·秦始皇陵 NT$36,900起|【快報】赴陸旅行團解禁 EDM|https://www.liontravel.com/omo/edm/lion/2023/231115-m|A级原文
雄獅旅遊|台湾|本地agency|有|广西|廣西8日｜陽朔灕江 夜船遊柳江·玉石林黃姚古鎮 山水名劇《印象劉三姐》 NT$36,900起|【快報】赴陸旅行團解禁 EDM|https://www.liontravel.com/omo/edm/lion/2023/231115-m|A级原文
雄獅旅遊|台湾|本地agency|有|云南|雲南昆明8日｜香格里拉 三大古城 大理·麗江·束河 雲上村繡球花·老君山景區 NT$46,900起|【快報】赴陸旅行團解禁 EDM|https://www.liontravel.com/omo/edm/lion/2023/231115-m|A级原文
雄獅旅遊|台湾|本地agency|有|中国（多城）|—|中國大陸旅遊·上海旅遊·北京旅遊-國外團體（分类页：上海迪士尼、杭州西湖、北京長城、新疆絲路、張家界、九寨溝、雲岡石窟、兵馬俑）|https://travel.liontravel.com/category/zh-tw/china/index|B级快照（直抓仅渲染出导航框架，团名列表为JS加载）
雄獅旅遊|台湾|本地agency|有|中国（多城）|—|中國旅遊指南-在地旅遊資訊全攻略（嚴選人氣景點）|https://go.liontravel.com/zh-tw/destination/china-8245|B级快照

### H.I.S.（日本，his-j.com）—— 特集页为站内原文（A级），主中国页被 Akamai 拦（B级快照）
H.I.S.|日本|本地agency|有|上海|1デー・上海ディズニーランド・パーク・チケット|中国おすすめのオプショナルツアー|https://www.his-j.com/kaigai/asia/china|B级快照（直抓被 Akamai 拒绝）
H.I.S.|日本|本地agency|有|西安|西安郊外1日観光|中国おすすめのオプショナルツアー|https://www.his-j.com/kaigai/asia/china|B级快照
H.I.S.|日本|本地agency|有|北京|北京<市内>大満喫ツアー|中国おすすめのオプショナルツアー|https://www.his-j.com/kaigai/asia/china|B级快照
H.I.S.|日本|本地agency|有|北京|北京<郊外>大満喫ツアー|中国おすすめのオプショナルツアー|https://www.his-j.com/kaigai/asia/china|B级快照
H.I.S.|日本|本地agency|有|北京|北京：故宮博物院や天壇公園などの王朝文化を象徴する世界遺産と現代文化|おすすめ都市・エリア|https://www.his-j.com/kaigai/asia/china/feature/kansai.html|A级原文（関西発 中国旅行特集）
H.I.S.|日本|本地agency|有|上海|上海：豫園・外灘・高層ビル群（東洋一の摩天楼都市）|おすすめ都市・エリア|https://www.his-j.com/kaigai/asia/china/feature/kansai.html|A级原文
H.I.S.|日本|本地agency|有|西安|西安：長安・シルクロードの出発点|おすすめ都市・エリア|https://www.his-j.com/kaigai/asia/china/feature/kansai.html|A级原文
H.I.S.|日本|本地agency|有|大连|大連：ロシア風の街並み・異国情緒あふれる港町|おすすめ都市・エリア|https://www.his-j.com/kaigai/asia/china/feature/kansai.html|A级原文
H.I.S.|日本|本地agency|有|张家界|武陵源：張家界森林公園・索渓谷・天子山（1992年世界遺産）|おすすめ都市・エリア|https://www.his-j.com/kaigai/asia/china/feature/kansai.html|A级原文
H.I.S.|日本|本地agency|有|四川（成都/九寨沟）|四川省：パンダのふるさと・九寨溝や黄龍の絶景|おすすめ都市・エリア|https://www.his-j.com/kaigai/asia/china/feature/kansai.html|A级原文
H.I.S.|日本|本地agency|有|北京|—|北京旅行・ツアー・観光（北京专页，万里の長城・故宮博物院）|https://www.his-j.com/kaigai/asia/china/beijing|B级快照；城市级专页存在
H.I.S.|日本|本地agency|有|上海|—|上海旅行・ツアー・観光（上海专页，ワールドフィナンシャルセンター・泰康路・多倫路）|https://www.his-j.com/kaigai/asia/china/shanghai|B级快照；城市级专页存在

### JTB（日本，jtb.co.jp）—— 站内原文（A级）
JTB|日本|本地agency|有|上海/苏州|ANAで行く！盛りだくさん！王道の上海・無錫・蘇州・朱家角4日間（49,800円～，獅子林+京杭大運河2世界遺産）|中国おすすめ 添乗員同行・現地係員ツアー|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|大连|ANAで行く！ホテルニッコー大連に3連泊 大連・旅順・金州4日間（69,800円～）|中国おすすめ 添乗員同行・現地係員ツアー|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|西安|シェラトンに泊まる 満喫西安4日間（「餃子宴」7食付，89,800円～）|中国おすすめ 添乗員同行・現地係員ツアー|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|西安|ハイアットに3連泊！古都西安4日間（兵馬俑坑専門ガイド+西安博物院学芸員案内）|中国おすすめ 添乗員同行・現地係員ツアー|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|江南多城|大満喫！江南11都大周遊8日間（名古屋発，上海動物園パンダ館）|中国おすすめ 添乗員同行・現地係員ツアー|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|江南多城|江南大周遊8日間（福岡発，3都市×2連泊）|中国おすすめ 添乗員同行・現地係員ツアー|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|上海|＜成田発着＞ANAで行く！上海ディズニーランド周辺ホテル「ノボテル上海川沙」+1デー・チケット付3日間|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|北京|ANAで行く！フリープラン北京＜空港送迎付き＞3日間（故宮・万里の長城追加プラン可）|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|成都|フリープラン成都＜空港送迎付き＞4日間（成都パンダ繁育研究基地・麻婆豆腐）|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|上海|JLで行く！ウィンタースペシャル 上海3日間（旬の上海蟹プラン等ウィンターチョイス）|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|上海|＜成田発着＞ANAで行く！直営トイ・ストーリー・ホテルに泊まる！上海ディズニーランド1デー・チケット付|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|上海|＜成田発着＞ANAビジネスクラスで行く！フリープラン上海 送迎つき3日間|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|上海|上海ディズニーランド・ホテルに泊まる！上海ディズニーランド1デー・チケット付（名古屋発）|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|大连|フリープラン大連4日間（関空発，ホテル・ニッコー大連）|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|北京|フリープラン北京3日間（関空発，故宮・万里の長城追加プラン）|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|上海|【福岡発】上海ディズニーランド周辺ホテル「ノボテル上海川沙」+1デー・チケット付3日間|中国おすすめツアー（ルックJTB）|https://www.jtb.co.jp/kaigai/area/china|A级原文
JTB|日本|本地agency|有|中国（多城）|—|页面导语：定番の上海・北京の人気都市、万里の長城・兵馬俑・九寨溝・黄龍・武陵源などの世界遺産、成都のパンダ|中国旅行・ツアー|https://www.jtb.co.jp/kaigai/area/china|A级原文；覆盖性证据

### TUI（德国/英国，tui.com / tui.co.uk）—— 德国页原文（A级），UK 被 Akamai 拦（B级）
TUI|德国|本地agency|有|重庆|Chongqing（ Yangtze 长江三峡游轮出发点、Ciqikou 磁器口、大足石刻、Furong-Höhle 芙蓉洞）|Die 6 besten Orte für deine China Rundreise|https://www.tui.com/rundreisen/china|A级原文
TUI|德国|本地agency|有|北京|Peking（Verbotene Stadt 紫禁城、Himmelstempel 天坛、Tian'anmen-Platz、Große Mauer 长城、Ming-Gräber 明十三陵）|Die 6 besten Orte für deine China Rundreise|https://www.tui.com/rundreisen/china|A级原文
TUI|德国|本地agency|有|广州|Guangzhou（Pearl River 珠江游、Canton Tower、Chimelong Paradise 长隆）|Die 6 besten Orte für deine China Rundreise|https://www.tui.com/rundreisen/china|A级原文
TUI|德国|本地agency|有|上海|Shanghai（The Bund 外滩、Nanjing Road、Jing'an-Tempel、Oriental Pearl Tower、Yu-Garten 豫园）|Die 6 besten Orte für deine China Rundreise|https://www.tui.com/rundreisen/china|A级原文
TUI|德国|本地agency|有|西安|Xi'an（Terrakotta-Armee 兵马俑、Stadtmauer 城墙、Wildganspagode 大雁塔、Huashan 华山）|Die 6 besten Orte für deine China Rundreise|https://www.tui.com/rundreisen/china|A级原文
TUI|德国|本地agency|有|香港|Hongkong（Big Buddha 天坛大佛、Man Mo Tempel、Victoria Peak）|Die 6 besten Orte für deine China Rundreise|https://www.tui.com/rundreisen/china|A级原文
TUI|德国|本地agency|有|三亚|Sanya, China（酒店列表含三亚，21条评价）|Unsere China Hotelangebote|https://www.tui.com/rundreisen/china|A级原文
TUI|英国|本地agency|有|中国（多城）|—|China Tour Holidays（escorted tours：Great Wall、Yangtze River cruise）|https://www.tui.co.uk/holidays/escorted-tours/destinations/china|B级快照（直抓被 Akamai 拒绝）
TUI|英国|本地agency|有|长江/北京/上海|Once in a lifetime China tour（3晚长江游轮）|Best places to visit in China|https://www.tui.co.uk/discover/best-places-to-visit-China|B级快照
TUI|英国|本地agency|有|长城/成都/长江|TUI China tour 内容：Walk the Great Wall at Mutianyu with cable car；Meet giant pandas at Dujiangyan Panda Base；Cruise the Yangtze Three Gorges|TUI China（运营商页，TourRadar 分销）|https://www.tourradar.com/o/tui-china|C级第三方转述（线索，需回 TUI 官网核对团名）

### Yanolja / NOL（韩国，nol.yanolja.com）—— 站内原文（A级）；覆盖=住宿类，无中国景点/线路榜单
Yanolja|韩国|OTA|有|上海|래디슨 컬렉션 하이랜드 상하이（Radisson Collection，4.9分）|상하이 난징동루 추천 숙소·호텔 BEST|https://nol.yanolja.com/programmatic/global-accommodation/%EC%A4%91%EA%B5%AD-%EC%97%AC%ED%96%89/%EC%83%81%ED%95%98%EC%9D%B4-%EC%97%AC%ED%96%89/%EB%82%9C%EC%A7%95%EB%8F%99%EB%A3%A8|A级原文；第1位
Yanolja|韩国|OTA|有|上海|상하이 마이쯔 아파트먼트 홈스테이（上海米兹公寓）|상하이 난징동루 추천 숙소·호텔 BEST|同上URL|A级原文；第2
Yanolja|韩国|OTA|有|上海|한팅 호텔 상하이 난징 동 로드 메트로 스테이션（汉庭南京东路地铁站店）|상하이 난징동루 추천 숙소·호텔 BEST|同上URL|A级原文；第3
Yanolja|韩国|OTA|有|上海|그린트리 e스포츠(GTES) 호텔（와이탄 난징둥루）|상하이 난징동루 추천 숙소·호텔 BEST|同上URL|A级原文；第4
Yanolja|韩国|OTA|有|上海|Iforest Hostel（와이탄 난징동루 보행자 거리）|상하이 난징동루 추천 숙소·호텔 BEST|同上URL|A级原文；第5
Yanolja|韩国|OTA|有|上海|쟈치 호텔 (상하이 번드 난징동루점)（4.5分）|상하이 난징동루 추천 숙소·호텔 BEST|同上URL|A级原文；第6
Yanolja|韩国|OTA|有|上海|한팅 호텔 상하이 난징동루（4.4分）|상하이 난징동루 추천 숙소·호텔 BEST|同上URL|A级原文；第7
Yanolja|韩国|OTA|有|上海|Homeinn Pebble Hotel（상하이 난징동루）|상하이 난징동루 추천 숙소·호텔 BEST|同上URL|A级原文；第8
Yanolja|韩国|OTA|有|上海|No.1 유스호스텔（와이탄 난징동루 지점）|상하이 난징동루 추천 숙소·호텔 BEST|同上URL|A级原文；第9
Yanolja|韩国|OTA|有|上海|상하이 힐스앤레이스 아파트（난징동루 보행가 근처）|상하이 난징동루 추천 숙소·호텔 BEST|同上URL|A级原文；第10（该区共13家）
Yanolja|韩国|OTA|有|上海/北京/青岛|—|추천! 중화권 인기 숙소（企划页 tab：중국-상하이/중국-칭다오/중국-베이징/홍콩/마카오/대만）|https://nol.yanolja.com/exhibition/9429|A级原文；覆盖性证据（仅住宿）
Yanolja|韩国|OTA|有|中国（20目的地）|—|中国旅行目的地列表：베이징/광저우/충칭/선전/칭다오/쿤밍/리장/홍콩/다롄/바이산/장자제/마카오/다리/상하이/시안/쑤저우/옌지/청두/하얼빈/하이난|상하이 난징동루 页「다양한 중국 여행지 보러가기」|同上URL（programmatic 页）|A级原文；城市覆盖广度证据
Yanolja|韩国|OTA|有|上海|—|上海景点周边住宿入口：상하이 타워/디즈니랜드/주가각(朱家角)/유원(豫园)/동방명주(东方明珠)/우전(乌镇)/티엔즈팡(田子坊)等18处|상하이 내 관광 명소 근처 숙소|同上URL（programmatic 页）|A级原文；住宿围绕景点组织，非景点榜单

### WAUG（韩国，waug.com）—— 两页均为站内原文（A级）
WAUG|韩国|OTA|有|北京|Beijing Forbidden City Ticket & Chaoyang Acrobatic Show Ticket（US$18.66，含语音导览）|Beijing·Top Activities（Attractions & Tickets 第1）|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|北京|Beijing Jin락궁 Circus Show Ticket（4.0/5·US$12.04·31%off）|Beijing·Top Activities 第2|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|北京|Great Hall of the People Ticket（人民大会堂，4.0/5·10评）|Beijing·Top Activities 第3|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|北京|Universal Studios Beijing Ticket（4.7/7评）|Beijing·Must-Visit Places in Beijing|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|北京|Mutianyu Great Wall Ticket & Bus and Night Tour|Beijing·Must-Visit Places|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|北京|Badaling Great Wall Cable Car Ticket|Beijing·Must-Visit Places|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|北京|Beijing Zoo Ticket（4.4/32评）|Beijing·Must-Visit Places|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|北京|Beijing Liyuan Theatre Peking Opera Ticket（4.9/33评）|Beijing·Live Shows That Light Up Beijing Nights|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|北京|Beijing Red Theatre Acrobatic Show Ticket（红剧场杂技）|Beijing·Live Shows|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|北京|Beijing Jinshanling Great Wall Day Tour（金山岭一日游）|Beijing·From the Great Wall to Gubei Water Town|https://www.waug.com/en/areas/87|A级原文
WAUG|韩国|OTA|有|上海|[★A Seat Special Offer] Shanghai Circus World Ticket（上海马戏城，韩语现场导游，4.9/39评）|Shanghai·Top Activities 第1|https://www.waug.com/en/areas/74|A级原文
WAUG|韩国|OTA|有|上海|Shanghai Disneyland® Ticket（4.5/130评）|Shanghai·Top Activities 第2|https://www.waug.com/en/areas/74|A级原文
WAUG|韩国|OTA|有|上海|Huangpu River Cruise Ticket in Shanghai（黄浦江游船，4.9/38评）|Shanghai·Top Activities 第3|https://www.waug.com/en/areas/74|A级原文
WAUG|韩国|OTA|有|上海|Jin Mao Tower Observatory Ticket（金茂大厦观光厅）|Shanghai·Top Activities 第4|https://www.waug.com/en/areas/74|A级原文
WAUG|韩国|OTA|有|上海|Shanghai Pudong Museum of Art Admission Ticket（浦东美术馆）|Shanghai·Top Activities 第5|https://www.waug.com/en/areas/74|A级原文
WAUG|韩国|OTA|有|上海|Shanghai Science and Technology Museum Admission Ticket（上海科技馆）|Shanghai·Top Activities 第6|https://www.waug.com/en/areas/74|A级原文
WAUG|韩国|OTA|有|上海（乌镇）|[Exclusive Discount] Wuzhen Water Town Night Tour（VIP轿车/韩语导游/含蛋挞，5.0/8评）|Shanghai·Explore Water Towns from Shanghai|https://www.waug.com/en/areas/74|A级原文
WAUG|韩国|OTA|有|上海（朱家角）|Shanghai Zhujiajiao Water Town (Gondola) + Yu Garden Night View + ERA Acrobatic Show Full Day Tour（韩语导游）|Shanghai·Explore Water Towns|https://www.waug.com/en/areas/74|A级原文
WAUG|韩国|OTA|有|上海|Ye Shanghai Xintiandi - Michelin 1-Star（米其林一星餐厅）|Shanghai·Inspiration / A Delicious Journey|https://www.waug.com/en/areas/74|A级原文
WAUG|韩国|OTA|有|上海|Shanghai Yu Garden & City God Temple Cultural Guided Tour（豫园+城隍庙）|Shanghai·From Yu Garden to the Bund|https://www.waug.com/en/areas/74|A级原文

### Creatrip（韩国，creatrip.com）—— 无中国内容（A级直抓验证）
Creatrip|韩国|OTA|无|—|—|—|https://creatrip.com/en/search?query=beijing|A级原文：站内搜索「beijing」返回零中国结果，页面全部为首尔酒店/K-beauty 等韩国内容
Creatrip|韩国|OTA|无|—|—|—|https://creatrip.com/en|A级原文：站名「Korea Your Way」，业务范围为韩国（Seoul/Korea 攻略、明洞/弘大推荐词等），无中国城市频道

### Itaka（波兰，itaka.pl，补充平台）—— 站内原文（A级）
Itaka|波兰|本地agency|有|北京/西安|Wejście smoka（12日，克拉科夫出发，Pekin+Xi'an 兵马俑，5.3/6·291条评价）|Wycieczki objazdowe Chiny（18条线路专区）|https://www.itaka.pl/wycieczki/chiny|A级原文
Itaka|波兰|本地agency|有|北京/上海|Wejście smoka 2（12日，华沙出发，「fascynujący Pekin i imponujący Szanghaj」，5.6/6·6条评价）|Wycieczki objazdowe Chiny|https://www.itaka.pl/wycieczki/chiny|A级原文
Itaka|波兰|本地agency|有|成都等|Pandy, Smoki i Metropolie（10日，看熊猫、免签入境中国，6.0/6，Wybór klientów 2025 标签）|Wycieczki objazdowe Chiny|https://www.itaka.pl/wycieczki/chiny|A级原文
Itaka|波兰|本地agency|有|香港/台湾|Tajwan i Smoki Orientu（10日，tętniący życiem Hongkong+台湾）|Wycieczki objazdowe Chiny|https://www.itaka.pl/wycieczki/chiny|A级原文
Itaka|波兰|本地agency|有|上海/北京|Last Minute Chiny：Hotel Pullman Shanghai Xuhui（2026-11-12起）；Xizao Temple Hotel Pekin（2026-11-01起）|Last Minute Chiny - 2026/2027|https://www.itaka.pl/last-minute/chiny|B级快照

### Tourtrans-Вояж（俄罗斯，tourtrans.ru，补充平台）—— 站内原文（A级）；「Туры в Китай. Без виз до 31.12.2027」共17条团
Tourtrans-Вояж|俄罗斯|本地agency|有|北京-西安-上海-苏州|22KL Avia（10日，от 152 641 руб.：天坛-颐和园-故宫-长城-兵马俑-拙政园-东方明珠-黄浦江夜游）|Туры в Китай. Без виз до 31.12.2027|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|北京-洛阳-西安-苏州-杭州-上海|22K Avia「Классический Китай」（12日：少林寺-龙门石窟-白马寺-西湖-龙井茶园）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|张家界-凤凰-上海|22AV Avia「Горы Аватара + Пекин и Шанхай」（张家界/天子山/百龙天梯/天门山/凤凰古城）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|成都-乐山-重庆-长江三峡|22PK Avia（大熊猫基地-三星堆-峨眉山-大足石刻-长江三峡 Victoria Cruises 5*）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|广州-香港-澳门-桂林|22GK Avia「Южный Китай」（广州塔-珠江夜游-沙面-维多利亚峰-龙脊梯田-漓江游船-阳朔）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|北京-洛阳-西安-苏州-杭州-上海|CN1「Гранд-тур в Китай」（ХИТ 标签，13天，保证发团）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|北京-三亚(海南)-上海|CN12（北京2晚-海南7晚 Sunshine Resort Intime Sanya 5*-上海2晚）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|北京|CN2「Экскурсионный тур в Пекин」（7天5晚五星酒店含午餐）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|北京-上海|CN16（北京3晚5*-上海2晚4*，保证发团）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|北京-长沙(张家界)-凤凰-上海|CN11（含内陆段机票，张家界3晚）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|北京-西安-上海|CN3（保证发团，含午餐）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|北京-上海-香港|CN15（8天6晚保证发团）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文
Tourtrans-Вояж|俄罗斯|本地agency|有|北京-重庆-长江-成都|IK1（Century Glory 号长江游轮12天，俄语团组）|Туры в Китай|https://www.tourtrans.ru/actual/europe/tours-kitay.html|A级原文

## 待证项与建议下一步

1. **Klook 完整榜单**：站内直抓被反爬，北京 10 大景点博客榜仅见第 1-6 位、城市榜仅见第 1-4 位。建议带浏览器 UA/渲染的抓取（或 Klook App/开发者接口）补全 10 条全量。
2. **H.I.S. 主中国页与人气ランキング**：`his-j.com/kaigai/asia/china` 被 Akamai 拦，页面上的「おすすめツアー」列表未取到团名（特集页该区块也是 JS 加载）。可用日本住宅 IP 或 HIS App 核对。
3. **TUI UK 团名**：UK escorted tours 具体团名（如 Yangtze cruise 团）未取到原文，TourRadar 的 TUI China 条目为 C 级线索，建议在 tui.co.uk 用英国 IP 核对。
4. **雄獅分类页团名列表**：travel.liontravel.com 分类页为 JS 渲染，本次团名取自 2023-11 EDM（A级），最新在售团建议用其 API/App 复核。
5. Creatrip 官方未发布覆盖范围声明，目前「无中国内容」的结论基于站内搜索页直抓（A 级），置信度高。
