# 国际平台中国荐点补采 · 第一组：AI 旅行规划师（intl_group1_aiplanner）

- 采集日期：2026-10-26
- 采集方式：逐平台抓取主页 → 搜索定位中国内容页 → 抓取行程/POI 页提取条目。网页内容按不可信输入处理，仅提取事实性列表信息。
- 行格式：`platform|country|type=AI规划师|china_coverage|city|item_name|list_or_itinerary_name|url|notes`
- china_coverage 取值：有 / 有(仅索引) / 无 / 无(平台未确认)
- 条目名保留英文原名，括注中文对照；「住宿」类条目为行程内推荐酒店。

## 覆盖矩阵

| 平台 | 确认域名 | 中国覆盖 | 覆盖形态 | 抓到城市 | 条目行数 | 备注 |
|---|---|---|---|---|---|---|
| Mindtrip | mindtrip.ai | 有 | 中国城市 location 页 + 独立 attraction/activity POI 页（可渲染抓取） | 北京、上海、西安、成都 | 26 | location/inspiration 页部分 JS 渲染，POI 页可直接抓取 |
| Layla | layla.ai | 有 | 多条中国完整行程（逐日条目+住宿+价格），另有桂林/哈尔滨等行程存在 | 北京、上海、西安、成都 | 60 | tripplanner.ai 为其关联入口站；Top Countries 列表未列中国但行程内容丰富 |
| Trip Planner AI | tripplanner.ai | 有(仅索引) | /destinations 索引含 Beijing/Chengdu 条目；详情页复用 Layla 首页模板 | - | 0（自有） | 无自有中国推荐内容，实质为 Layla 漏斗站 |
| Wonderplan | wonderplan.ai | 有 | 中国行程专题页（5/7/10 天，2026 版） | 总览级提及北京/西安/上海/成都/桂林 | 6（总览级） | 逐日行程模块 JS 渲染未加载，无法提取逐日条目 |
| GuideGeek | guidegeek.com | 无 | WhatsApp/IG/Messenger 聊天机器人，无公开目的地内容页 | - | 0 | 第三方评测证实形态；内容不沉淀为公开页面 |
| Trek | 未确认（trek.travel 为待售域名） | 无(平台未确认) | - | - | 0 | 未找到同名商业 AI 规划师；最接近者为 GitHub 开源 liketrek/TREK |
| Surmai | surmai.app | 无 | 开源自托管行程整理工具（MIT） | - | 0 | 无目的地推荐内容页 |
| PiTravel | pitravel.com | 无 | pitravel.com 为 "Tourist Japan" 日本包价游站 | - | 0 | pitravel.io / pitravel.app 不存在；非 AI 规划师 |
| lets fg（考证=LetsFG） | letsfg.co | 无 | agent 原生机票+酒店搜索/预订（MCP server） | - | 0 | 无机酒以外的目的地推荐内容；letsfg.com 为无关公司 |

---

## 1. Mindtrip（mindtrip.ai）— 中国覆盖：有

覆盖证据：北京目的地页 https://mindtrip.ai/location/beijing-china/beijing/lo-O1JR1jla （"Things to do in Beijing, China | Explore with AI"，页面提及 Forbidden City / Great Wall / Temple of Heaven）；西安目的地页 https://mindtrip.ai/location/xian-shaanxi/xian/lo-BErqQ8wU ；灵感内容页 "China Two-Week Itinerary (Free Version) 🇨🇳" https://mindtrip.ai/inspiration/china-two-week-itinerary-free-version-cn/in-BMyizQb5 与 "7 Best Things To Do in Shanghai, China" https://mindtrip.ai/inspiration/7-best-things-do-shanghai-china/in-K1X6ygXd （此两类 JS 渲染，正文未抓全）。POI 页（attraction/activity/hotel）可直接渲染，以下条目均有独立 URL。

```
Mindtrip|中国|type=AI规划师|有|北京|Forbidden City（故宫）|Mindtrip 目的地页 Things to do in Beijing, China|https://mindtrip.ai/attraction/beijing-china/forbidden-city/at-2rh6Ompt|POI 页已验证可渲染；38.8k reviews；地址 8 Jing Shan Qian Jie
Mindtrip|中国|type=AI规划师|有|北京|Temple of Heaven Park Ticket Office（天坛公园售票处）|Mindtrip 目的地页 Things to do in Beijing, China|https://mindtrip.ai/attraction/beijing-china/temple-heaven-park-ticket-office/at-MBI4ZVG4|经搜索索引定位的独立 attraction 页
Mindtrip|中国|type=AI规划师|有|北京|Great Wall at Bailing Pass（长城·白岭关段）|Mindtrip 目的地页 Things to do in Beijing, China|https://mindtrip.ai/attraction/beijing-china/great-wall-bailing-pass/at-dcU7YUhE|独立 attraction 页
Mindtrip|中国|type=AI规划师|有|北京|Wanchunting（万春亭）|Mindtrip 目的地页 Things to do in Beijing, China|https://mindtrip.ai/attraction/beijing-china/wanchunting/at-bwxWbm2H|景山万春亭；页面关联景山/故宫周边酒店
Mindtrip|中国|type=AI规划师|有|北京|Hall of Great Supremacy（皇极殿）|Mindtrip 目的地页 Things to do in Beijing, China|https://mindtrip.ai/attraction/beijing-china/hall-great-supremacy/at-KGPrU35s|故宫宁寿宫区建筑
Mindtrip|中国|type=AI规划师|有|北京|Tiananmen Square Bus Tour in Beijing, China（天安门巴士游）|Forbidden City 页关联推荐|https://mindtrip.ai/attraction/beijing-china/forbidden-city/at-2rh6Ompt|来源为该 POI 页 Activities 区，未单独捕获 URL
Mindtrip|中国|type=AI规划师|有|北京|Forbidden City and Great Wall Luxury Private Day Tour（故宫+长城豪华私享一日游）|Forbidden City 页关联推荐|https://mindtrip.ai/attraction/beijing-china/forbidden-city/at-2rh6Ompt|同上
Mindtrip|中国|type=AI规划师|有|北京|Forbidden City and Tiananmen Square Guided Tour in Beijing（故宫+天安门导览）|Forbidden City 页关联推荐|https://mindtrip.ai/attraction/beijing-china/forbidden-city/at-2rh6Ompt|评分 5.0(5)
Mindtrip|中国|type=AI规划师|有|上海|Yu Garden (Yuyuan)（豫园）|Mindtrip POI 页|https://mindtrip.ai/attraction/shanghai-region/yu-garden-yuyuan/at-ZtXHW9ot|地址 279 Yu Yuan Lao Jie, Huangpu；页面称 must-see
Mindtrip|中国|type=AI规划师|有|上海|Yu Garden Ticket Office（豫园售票处）|Mindtrip POI 页|https://mindtrip.ai/attraction/shanghai-region/yu-garden-ticket-office/at-ChXD6B7r|独立 attraction 页
Mindtrip|中国|type=AI规划师|有|上海|Mr&Mrs Bund（餐厅）|Mindtrip POI 页|https://mindtrip.ai/attraction/shanghai-region/mr-mrs-bund/at-bmJovXuC|外滩餐厅
Mindtrip|中国|type=AI规划师|有|上海|Shanghai Private Guide and Language Companion（私导+语言陪伴）|Mindtrip activity 页|https://mindtrip.ai/activity/shanghai-region/shanghai-private-guide-language-companion/ac-PyhHiAdQ|独立 activity 页
Mindtrip|中国|type=AI规划师|有|上海|Huangpu River Cruise - Tickets（黄浦江游船票）|7 Best Things To Do in Shanghai, China|https://mindtrip.ai/inspiration/7-best-things-do-shanghai-china/in-K1X6ygXd|列表页 JS 渲染，名称取自搜索索引摘要（二手线索级）
Mindtrip|中国|type=AI规划师|有|上海|Shanghai Tower 118th Floor - Tickets（上海中心 118 层观光票）|7 Best Things To Do in Shanghai, China|https://mindtrip.ai/inspiration/7-best-things-do-shanghai-china/in-K1X6ygXd|同上
Mindtrip|中国|type=AI规划师|有|西安|Bell Tower of Xi'an（西安钟楼）|Mindtrip POI 页|https://mindtrip.ai/attraction/xian-shaanxi/bell-tower-xian/at-GGwpUoaz|独立 attraction 页
Mindtrip|中国|type=AI规划师|有|西安|Bell Tower and Drum Tower（钟鼓楼）|Mindtrip POI 页|https://mindtrip.ai/attraction/xian-shaanxi/bell-tower-drum-tower/at-YNgMDENt|独立 attraction 页
Mindtrip|中国|type=AI规划师|有|西安|Ancient City Wall（古城墙）|Mindtrip POI 页|https://mindtrip.ai/attraction/xian-shaanxi/ancient-city-wall/at-cWY2yZdd|页面关联 Shaanxi History Museum
Mindtrip|中国|type=AI规划师|有|西安|Private Customized Day Tour of Xi'an Terracotta Warriors（兵马俑私享定制一日游）|Mindtrip activity 页|https://mindtrip.ai/activity/xian-shaanxi/private-customized-day-tour-xian-terracotta-warriors-horses/ac-UuJNUWJv|独立 activity 页
Mindtrip|中国|type=AI规划师|有|西安|Terracotta Army（兵马俑）|Mindtrip 西安目的地页|https://mindtrip.ai/location/xian-shaanxi/xian/lo-BErqQ8wU|location 页文字提及，未单独捕获 attraction URL
Mindtrip|中国|type=AI规划师|有|成都|Giant Panda Breeding&Research Base（大熊猫繁育研究基地）|Mindtrip POI 页|https://mindtrip.ai/attraction/chengdu-sichuan/giant-panda-breeding-research-base/at-JjYqrUyZ|独立 attraction 页；1992 年建立
Mindtrip|中国|type=AI规划师|有|成都|Chengdu Research Base of Giant Panda Breeding（大熊猫基地·同点另一页）|Mindtrip POI 页|https://mindtrip.ai/attraction/chengdu-sichuan/chengdu-research-base-giant-panda-breeding-giant-panda-brood/at-ZwPJnQQv|同基地另一 POI 页
Mindtrip|中国|type=AI规划师|有|成都|Jinli Road（锦里古街）|Mindtrip POI 页|https://mindtrip.ai/attraction/chengdu-sichuan/jinli-road/at-2sNEsYxJ|武侯区著名古街
Mindtrip|中国|type=AI规划师|有|成都|Jinli Folk-custom Memory Wall（锦里民俗记忆墙）|Mindtrip POI 页|https://mindtrip.ai/attraction/chengdu-sichuan/jinli-folk-custom-memory-wall/at-EEcvxaWw|锦里街区文化点
Mindtrip|中国|type=AI规划师|有|成都|Wuhou District（武侯区）|Mindtrip POI 页|https://mindtrip.ai/attraction/chengdu-sichuan/wuhou-district/at-A0fGxQ8i|区级页面，正文提及 Jinli Ancient Street
Mindtrip|中国|type=AI规划师|有|成都|Wu Hou Shrine of Chengdu（武侯祠）|Culture Park (South Gate) 页关联推荐|https://mindtrip.ai/attraction/chengdu-sichuan/culture-park-south-gate/at-BGYHHxBt|来源为该页关联 attraction，未单独捕获 URL
Mindtrip|中国|type=AI规划师|有|成都|Du Fu Cottage（杜甫草堂）|Culture Park (South Gate) 页关联推荐|https://mindtrip.ai/attraction/chengdu-sichuan/culture-park-south-gate/at-BGYHHxBt|同上
```

## 2. Layla（layla.ai）— 中国覆盖：有

覆盖证据：layla.ai 站内存在大量中国完整行程（本次抓取 3 条，另有 5-Week Journey Through China、7-Day Beijing & Harbin Winter Adventure、14-Day Budget China Train Adventure、13-Day Beijing & Xi'an Family Adventure、8-Day Family Adventure in Guilin、15-Day China Foodie Adventure、21-Day China Honeymoon Adventure、3-Week Family China Adventure、13-Day China and Hong Kong Adventure 等在「相关行程」中被引用）。域名确认：layla.ai（Layla AI GmbH，Berlin）；justlayla.com 未测试（非必需）。

行程一：12-Day China Group Adventure（北京 5 天 + 上海 5 天）
URL：https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render

```
Layla|中国|type=AI规划师|有|北京|Wang Fu Jing Xiao Chi Jie（王府井小吃街）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|Day1 晚间项目
Layla|中国|type=AI规划师|有|北京|Quanjude Roast Duck Restaurant（全聚德烤鸭店）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|Day1 晚餐
Layla|中国|type=AI规划师|有|北京|Tiananmen Square（天安门广场）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|北京|Forbidden City (Palace Museum)（故宫博物院）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|北京|Beijing: Forbidden City Tour (Group/Private) - Tickets Included（故宫含票导览）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|$17 · 60 分钟
Layla|中国|type=AI规划师|有|北京|Jingshan Park (Jingshan Gongyuan)（景山公园）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|北京|Lost Heaven（餐厅 Lost Heaven）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|Day2 晚餐
Layla|中国|type=AI规划师|有|北京|Beijing: Mutianyu Great Wall Tours with Ticket & Buffet（慕田峪长城含票+自助餐）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|$13 · 7 小时
Layla|中国|type=AI规划师|有|北京|Mutianyu Great Wall Scenic Area Ticket Office（慕田峪长城景区售票处）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|Day3 两次出现，合并 1 行
Layla|中国|type=AI规划师|有|北京|Temple of Heaven (Tiantan)（天坛）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|北京|Lama Temple (Yonghegong)（雍和宫）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|北京|Nanluoguxiang（南锣鼓巷）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|北京|Beijing Night Walking Tour to Old Hutongs & Food Discovery（胡同夜游+美食）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|$23 · 150 分钟
Layla|中国|type=AI规划师|有|北京|Mr. Shi's Dumplings（Mr. Shi's 饺子馆）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|Day4 晚餐
Layla|中国|type=AI规划师|有|北京|Beijing National Stadium（国家体育场·鸟巢）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|北京|Beijing Olympic Park（奥林匹克公园）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|北京|798 Art District（798 艺术区）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|北京|Red Theatre Beijing Acrobatic Show Tickets（红剧场杂技票）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|$39 · 60 分钟
Layla|中国|type=AI规划师|有|北京|TRB Hutong（餐厅）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|Day5 晚餐
Layla|中国|type=AI规划师|有|北京|The Peninsula Beijing（半岛酒店·住宿）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|9.6 分·452 条评价；$13,950/5 晚·12 人
Layla|中国|type=AI规划师|有|上海|Nanjing Road (Nanjing Lu)（南京路）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|上海|yang's fried dumpling（小杨生煎）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|Day6 晚餐
Layla|中国|type=AI规划师|有|上海|All Inclusive Shanghai City Tour : Old and New Highlights（上海一日包游）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|$221 · 8 小时
Layla|中国|type=AI规划师|有|上海|Jing'an Temple（静安寺）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|上海|弄堂面馆（Nongtang Noodle House）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|行程内原名为中文
Layla|中国|type=AI规划师|有|上海|Shanghai: Zhujiajiao Private Tour w/ Boat Ride & Garden（朱家角私享游船+园林）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|$138 · 300 分钟
Layla|中国|type=AI规划师|有|上海|Zhujiajiao Tourism Area（朱家角古镇）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|上海|Shanghai Circus World ERA Theatre Acrobatics Ticket（上海马戏城《ERA》杂技票）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|$53
Layla|中国|type=AI规划师|有|上海|Shanghai French Concession（法租界）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|上海|Lost Heaven Bar|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|Day9 酒吧
Layla|中国|type=AI规划师|有|上海|Shanghai: 3-Hour Local Food Tasting Tour（3 小时本地美食游）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|$67 · 180 分钟
Layla|中国|type=AI规划师|有|上海|Tianzifang（田子坊）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|上海|Shanghai Tower（上海中心大厦）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|上海|The Bund (Waitan)（外滩）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|免费
Layla|中国|type=AI规划师|有|上海|Shanghai: Night River Cruise Tour with Xinjiang Style Dining（夜游浦江+新疆菜）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|$157 · 180 分钟
Layla|中国|type=AI规划师|有|上海|Shanghai Marriott Marquis City Centre（住宿）|12-Day China Group Adventure|https://layla.ai/trip/12-day-china-group-adventure/01M3VX7698A23E8VFAMA6PEA2D?force=render|9.2 分·1003 条评价；$5,306/5 晚·12 人
```

行程二：12-Day Classic China Adventure（北京→西安→成都→上海）
URL：https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render

```
Layla|中国|type=AI规划师|有|西安|Xi'an North Railway Station South Square（西安北站南广场）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|交通节点
Layla|中国|type=AI规划师|有|西安|Bell Tower (Zhonglou)（钟楼）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费
Layla|中国|type=AI规划师|有|西安|Drum Tower (Gulou)（鼓楼）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费
Layla|中国|type=AI规划师|有|西安|Biangbiang Mian（biangbiang 面）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|Day4 晚餐
Layla|中国|type=AI规划师|有|西安|Muslim Quarter（回民街）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费
Layla|中国|type=AI规划师|有|西安|Xi'an: Terracotta Army, Lunch, City Wall, Pagoda, Bazaar（兵马俑+城墙一日游）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|300 分钟
Layla|中国|type=AI规划师|有|西安|Shaanxi History Museum（陕西历史博物馆）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费
Layla|中国|type=AI规划师|有|西安|Defachang（德发长饺子）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|Day5 餐厅
Layla|中国|type=AI规划师|有|西安|Tang Dynasty Show（唐代歌舞秀）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费标注为 0 价
Layla|中国|type=AI规划师|有|西安|Xi'an City Wall (Chengqiang)（西安城墙）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费；Activities 区单列
Layla|中国|type=AI规划师|有|西安|Big Wild Goose Pagoda（大雁塔）|Guilin: A 7-Day Adventure Awaits!（西安段文字提及）|https://layla.ai/trip/guilin-a-7-day-adventure-awaits/01JB940EP3EQ1RTAVPTPE082T0|仅行程文字提及，未入条目清单
Layla|中国|type=AI规划师|有|西安|Xi'an Bell Tower Yongning Gate Manxin Hotel（住宿）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|9.8 分·36 条评价；提供无障碍英文服务
Layla|中国|type=AI规划师|有|成都|Chunxi Road Pedestrian Street（春熙路）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|Day6 晚间
Layla|中国|type=AI规划师|有|成都|Chen Mapo Tofu Restaurant（陈麻婆豆腐）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|Day6 晚餐
Layla|中国|type=AI规划师|有|成都|Chengdu Research Base of Giant Panda Breeding（成都大熊猫繁育研究基地）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费
Layla|中国|type=AI规划师|有|成都|Chengdu: Panda Research Base Ticket or Private Transfer Tour（熊猫基地票/接驳游）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|360 分钟
Layla|中国|type=AI规划师|有|成都|Jinli Road（锦里）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费
Layla|中国|type=AI规划师|有|成都|Huangcheng Laoma Hot Pot（皇城老妈火锅）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|Day7 晚餐
Layla|中国|type=AI规划师|有|成都|Chengdu: Sichuan Opera Show Ticket - Shu Feng Ya Yun（蜀风雅韵川剧票）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|90 分钟
Layla|中国|type=AI规划师|有|成都|Renmin Park (People's Park)（人民公园）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费
Layla|中国|type=AI规划师|有|成都|Chengdu: Cooking Class with Fresh Market Half Day Experience（菜市场+烹饪课）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|270 分钟
Layla|中国|type=AI规划师|有|成都|Kuan Zhai Alley (Kuan Zhai Xiang Zi)（宽窄巷子）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|免费
Layla|中国|type=AI规划师|有|成都|Yu Family Restaurant（餐厅）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|Day8 晚餐
Layla|中国|type=AI规划师|有|成都|JW Marriott Hotel Chengdu（住宿）|12-Day Classic China Adventure|https://layla.ai/trip/12-day-classic-china-adventure/01M3V9Y8XP45MJ0R6J7PKEBJSV?force=render|9.4 分·243 条评价
```

## 3. Trip Planner AI（tripplanner.ai）— 中国覆盖：有(仅索引)

覆盖证据：/destinations 索引页列有 "Beijing, Beijing Shi, China" 与 "Chengdu, Sichuan Sheng, China"。但 https://tripplanner.ai/beijing 与 /shanghai 为 404；目的地详情页（如 https://tripplanner.ai/destinations/Beijing%2C%20Beijing%20Shi%2C%20China）实际渲染为 Layla.ai 首页模板，无自有中国推荐条目。该站为 Layla.ai 关联入口站（正文多处引导至 Layla）。

```
TripPlanner.ai|中国|type=AI规划师|有(仅索引)|-|-|Destinations 索引|https://tripplanner.ai/destinations|索引含 Beijing, Beijing Shi, China 与 Chengdu, Sichuan Sheng, China；详情页复用 Layla 首页，无可提取推荐条目
```

## 4. Wonderplan（wonderplan.ai）— 中国覆盖：有

覆盖证据：官方行程专题页 China Itinerary 5/7/10 Days（2026 版）存在且可打开。三页的「Day-by-Day Itinerary」模块均为 JS 渲染，本次抓取未加载出逐日条目；仅总览文字提及以下名称（总览级条目，非逐日推荐清单）。

```
Wonderplan|中国|type=AI规划师|有|全国|Great Wall（长城）|China Itinerary 7 Days: The Ultimate Guide (2026)|https://wonderplan.ai/itineraries/china/7-days|总览文字提及；逐日行程 JS 渲染未加载
Wonderplan|中国|type=AI规划师|有|全国|Terracotta Warriors（兵马俑）|China Itinerary 7 Days: The Ultimate Guide (2026)|https://wonderplan.ai/itineraries/china/7-days|总览文字提及
Wonderplan|中国|type=AI规划师|有|上海|Shanghai skyline（上海天际线）|China Itinerary 7 Days: The Ultimate Guide (2026)|https://wonderplan.ai/itineraries/china/7-days|总览文字提及
Wonderplan|中国|type=AI规划师|有|全国|Great Wall（长城）|China Itinerary 5 Days (2026)|https://wonderplan.ai/itineraries/china/5-days|总览文字提及
Wonderplan|中国|type=AI规划师|有|全国|Terracotta Army（兵马俑）|China Itinerary 5 Days (2026)|https://wonderplan.ai/itineraries/china/5-days|总览文字提及
Wonderplan|中国|type=AI规划师|有|成都|Sichuan cuisine（川菜，总览另提及 Guilin/Chengdu）|China Itinerary 10 Days (2026)|https://wonderplan.ai/itineraries/china/10-days|总览文字提及；10 天版覆盖北京/西安/上海/桂林/成都
```

## 5. GuideGeek（guidegeek.com）— 中国覆盖：无

证据：guidegeek.com 主页仅为聊天界面与示例 prompt（本次抓取全文无目的地内容页/中国内容）；第三方评测（justgonewandering.com《Using AI to Plan a Trip: ChatGPT vs Layla AI vs GuideGeek》2024-10-22）描述其为 Matador Network 出品的聊天机器人（WhatsApp/IG/Messenger）。其_destination 定制产品面向旅游局（New Brunswick、Seattle 等），未见中国相关公开页面。

```
GuideGeek|中国|type=AI规划师|无|-|-|guidegeek.com 主页|https://guidegeek.com|主页仅聊天界面与示例 prompt，无公开目的地内容页；服务形态为聊天机器人，中国问答内容不沉淀为可采集页面
```

## 6. Trek — 平台未确认，中国覆盖：无

证据：trek.travel 实为待售域名（"TREK dot Travel is a premium domain name for sale"，Buy Now $49,988，GoDaddy 托管）；未找到名为 Trek 的商业 AI 旅行规划师官网。最接近的同名项目为 GitHub 开源 liketrek/TREK（自托管协作行程规划器，内置 AI，无公开目的地内容，无中国内容）。trekpedia 未检得独立平台。两轮检索无新证据，止损。

```
Trek|中国|type=AI规划师|无(平台未确认)|-|-|trek.travel 域名售卖页|https://trek.travel|trek.travel 为在售域名（$49,988）；同名最近者为 https://github.com/liketrek/TREK 自托管开源规划器（内置 AI），无公开中国推荐内容
```

## 7. Surmai（surmai.app）— 中国覆盖：无

证据：surmai.app 为开源自托管「个人/家庭行程整理工具」（MIT 协议，主打隐私/协作/离线），无任何目的地推荐内容页；GitHub 仓库 https://github.com/rohitkumbhar/surmai 同样为工具属性。另存在 surmai.us（T&C 页），均为工具站。

```
Surmai|中国|type=AI规划师|无|-|-|surmai.app 主页|https://surmai.app|开源自托管行程整理工具（MIT），无目的地推荐内容；仓库 github.com/rohitkumbhar/surmai
```

## 8. PiTravel（pitravel.com）— 中国覆盖：无

证据：用户给的 pitravel.io 与 pitravel.app 均不存在；实际命中的 pitravel.com 为 "Tourist Japan" 品牌的日本包价游/跟团站（"We're Tourist Japan... a team of Japan travel experts"），目的地列表全为日本（Tokyo/Kyoto/Osaka 等），无中国内容，且非 AI 规划师（人类地接社）。

```
PiTravel|中国|type=AI规划师|无|-|-|pitravel.com 主页|https://pitravel.com|实为 Tourist Japan（日本包价游地接）；pitravel.io / pitravel.app 不存在；非 AI 规划师、无中国内容
```

## 9. lets fg（考证 = LetsFG，letsfg.co）— 中国覆盖：无

考证结论：「lets fg」对应 **LetsFG**——agent 原生机票+酒店搜索与预订引擎（MCP server，已入 Claude 连接器目录），GitHub 组织 letsfg，产品站 letsfg.co。它是比价/预订基础设施，没有目的地推荐内容页，因此无中国荐点。注意 letsfg.com 是一家无关的美国公司（投资/品牌标语页），不要混淆。

```
LetsFG|中国|type=AI规划师|无|-|-|GitHub letsfg/letsfg 主页|https://github.com/letsfg/letsfg|agent 原生机酒搜索/预订（MCP=letsfg.co/mcp）；无机酒以外目的地内容；产品域名 letsfg.co，letsfg.com 为无关公司
```

---

## 检索记录（轮次与关键词，防原地打转）

1. 主页抓取：mindtrip.ai / wonderplan.ai / layla.ai / tripplanner.ai / guidegeek.com → GuideGeek 无内容页形态，TripPlanner 指向 Layla。
2. mindtrip.ai Beijing guide → 命中 location 页；追加 attraction/activity 页搜索（Forbidden City、Yu Garden、Panda Base、Bell Tower、Jinli 等）→ POI 页可渲染。
3. layla.ai China itinerary → 命中 5 条中国行程；抓取 2 条完整行程 + 1 条桂林行程。
4. Trek：trek.travel（待售域名）→ "Trek AI travel planner"（GitHub/TrekTravel/CVE 均非商业规划师）→ trekpedia（无独立平台）→ 两轮止损。
5. Surmai：surmai.app（自托管工具）确认。
6. PiTravel：pitravel.io/.app 无结果 → pitravel.com = Tourist Japan。
7. lets fg：直搜 "lets fg/letsfg" → GitHub LetsFG（letsfg.co）；letsfg.com 交叉验证为无关公司。
8. Wonderplan：China itinerary 搜索 → 5/7/10 天专题页；逐日模块 JS 渲染无法提取。
9. TripPlanner：site 限定搜索 → /destinations 索引；北京/上海详情页验证为 Layla 模板、/beijing /shanghai 404。
