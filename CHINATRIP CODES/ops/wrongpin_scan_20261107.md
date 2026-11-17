# 错针扫描清单（2026-11-07，只读）
> 扫描口径：active 非 food/hotel/transport；同城、名称互含/核心相等、B 优先级严格高于 A、haversine > 1km。每 A 留最优 B（优先级差最大→距离最远）。优先级基础序 = Iron rule（app/services/source_tier.py），名录外源按 2026-11-03 拍板序插入；`ct_` 前缀 source_poi_id 行按 chinatravel 档计（事故形态）。扫描时刻 2026-11-07T11:26:06，全流程只读未写库。

## 统计
- 扫入池行数：5706（active 非 food/hotel/transport，坐标非空）
- 行级假阳性剔除：{'subfacility': 88, 'branch': 118, 'hotelish': 48, 'retail': 4}（branch/subfacility/retail/hotelish）
- 城市（有池行）数：402
- 原始可疑对（A×B 全对，>1km）：537
- 去重后（每 A 留一 B）：453；主清单（tier1）131（其中 ct 形态 63），弱配对（tier2 仅别名命中）127，地理核警示 195
- ct 标记行数（source_poi_id 带 ct_ 前缀）：2576
- ct 标记行按标称 source：{'amap': 1239, 'chinatravel': 1337}
- 池行 Top 城市：杭州:364, 重庆:361, 北京:347, 上海:324, 苏州:307, 成都:288, 广州:277, 南京:273

## A. 重点：chinatravel / ct_ 形态可疑对（63 对）

| 城市 | A 名（疑错针） | A source | A source_poi_id | A 坐标 | A cat | B 名（疑真实） | B source | B 坐标 | B cat | 距离km | 优先级差 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 上海 | 闵行博物馆 | chinatravel | `ct_上海_259` | 121.37029,31.16472 | museum | 上海市闵行区博物馆 | museum3 | 121.35937,31.16064 | museum | 1.13 | 10 | - |
| 上海 | 龙美术馆(西岸馆) | chinatravel | `ct_上海_304` | 121.47589,31.18835 | museum | 龙美术馆 | artmuseum | 121.57394,31.21597 | museum | 9.82 | 9 | - |
| 上海 | 中华艺术宫 | amap→chinatravel | `ct_上海_73` | 121.52883,31.12308 | attraction | 中华艺术宫（上海美术馆） | artmuseum | 121.49441,31.18413 | museum | 7.54 | 9 | 类别差attraction/museum |
| 上海 | 石库门老街 | chinatravel | `ct_上海_206` | 121.51702,31.22276 | attraction | 上海市黄浦区新天地石库门街区 | street | 121.48058,31.22377 | historic | 3.47 | 8 | B区块、类别差attraction/historic |
| 上海 | 安福路 | chinatravel | `ct_上海_108` | 121.45445,31.21841 | attraction | 武康路-安福路街区 | street | 121.44047,31.20876 | historic | 1.71 | 8 | B区块、类别差attraction/historic |
| 上海 | 武康路 | chinatravel | `ct_上海_41` | 121.45096,31.21174 | attraction | 武康路-安福路街区 | street | 121.44047,31.20876 | historic | 1.05 | 8 | B区块、类别差attraction/historic |
| 上海 | 新场古镇 | amap→chinatravel | `ct_上海_169` | 121.64438,31.02610 | attraction | 新场镇 | histown | 121.47400,31.23000 | ancient_town | 27.88 | 7 | B区块、类别差attraction/ancient_town |
| 上海 | 川沙古镇 | amap→chinatravel | `ct_上海_178` | 121.47400,31.23000 | attraction | 川沙新镇 | histown | 121.69567,31.19320 | ancient_town | 21.47 | 7 | B区块、类别差attraction/ancient_town |
| 上海 | 朱家角大清邮局 | chinatravel | `ct_上海_356` | 121.06471,31.11125 | other | 朱家角镇 | histown | 121.04651,31.10365 | ancient_town | 1.93 | 7 | B区块、类别差other/ancient_town |
| 上海 | 上海朱家角珠溪里舍 | chinatravel | `ct_上海_7841` | 121.05052,31.11416 | nature | 朱家角镇 | histown | 121.04651,31.10365 | ancient_town | 1.23 | 7 | B区块、类别差nature/ancient_town |
| 北京 | 铛铛车游北京中轴线 | chinatravel | `ct_北京_260` | 116.41024,39.90619 | entertainment | 北京中轴线 | unesco | 116.39785,39.90104 | historic | 1.20 | 15 | 类别差entertainment/historic |
| 北京 | 明十三陵 | chinatravel | `ct_北京_16` | 116.23793,40.26480 | attraction | 昌平区明十三陵景区 | 5a | 116.24053,40.27913 | attraction | 1.61 | 14 | B区块 |
| 北京 | 清华大学 | chinatravel | `ct_北京_277` | 116.34837,40.00645 | attraction | 清华大学艺术博物馆 | museum1 | 116.32848,40.00354 | museum | 1.72 | 12 | 类别差attraction/museum |
| 北京 | 五塔寺塔 | chinatravel | `ct_北京_249` | 116.34312,39.95196 | attraction | 北京石刻艺术博物馆 | museum3 | 116.33046,39.94477 | museum | 1.34 | 10 | 类别差attraction/museum |
| 北京 | 王府井 | chinatravel | `ct_北京_38` | 116.42428,39.92119 | citywalk | 北京市东城区王府井商业街区 | street | 116.41228,39.91596 | historic | 1.18 | 8 | B区块、类别差citywalk/historic |
| 南京 | 夫子庙雨花石博物馆 | chinatravel | `ct_南京_299` | 118.80192,32.02507 | museum | 夫子庙秦淮河风光带 | 5a | 118.78889,32.02093 | attraction | 1.31 | 14 | 类别差museum/attraction |
| 南京 | 南京夫子庙-秦淮风光带-长干里 | amap→chinatravel | `ct_南京_156` | 118.77925,32.01580 | attraction | 夫子庙秦淮河风光带 | 5a | 118.78889,32.02093 | attraction | 1.07 | 14 | - |
| 南京 | 南京博物院-民国馆 | amap→chinatravel | `ct_南京_163` | 118.84322,32.03583 | museum | 南京博物院 | museum1 | 118.82490,32.04045 | museum | 1.80 | 12 | - |
| 广州 | 广州美术馆(新馆) | chinatravel | `ct_广州_269` | 113.33805,23.10395 | museum | 广州艺术博物院 | museum1 | 113.32272,23.10173 | museum | 1.59 | 12 | - |
| 广州 | 南越王博物院(王墓展区) | amap→chinatravel | `ct_广州_15` | 113.26156,23.13771 | museum | 南越王博物院 | museum1 | 113.26987,23.12685 | museum | 1.48 | 12 | - |
| 广州 | 陈家祠 | chinatravel | `ct_广州_8` | 113.25732,23.12993 | attraction | 广东民间工艺博物馆 | museum1 | 113.24540,23.12668 | museum | 1.27 | 12 | 类别差attraction/museum |
| 广州 | 广州体育馆 | chinatravel | `ct_广州_283` | 113.28941,23.18524 | theme_park | 广州体育文化博物馆（广州亚运会亚残运会博物馆） | museum3 | 113.32207,23.13843 | museum | 6.18 | 10 | 类别差theme_park/museum |
| 广州 | 洪秀全故居 | chinatravel | `ct_广州_272` | 113.18483,23.42086 | attraction | 广州市花都区洪秀全纪念馆（广州市花都区博物馆） | museum3 | 113.22012,23.40433 | museum | 4.04 | 10 | 类别差attraction/museum |
| 广州 | 广州体育文化博物馆 | chinatravel | `ct_广州_302` | 113.33421,23.14179 | museum | 广州体育文化博物馆（广州亚运会亚残运会博物馆） | museum3 | 113.32207,23.13843 | museum | 1.30 | 10 | - |
| 广州 | 荔湾博物馆 | amap→chinatravel | `ct_广州_135` | 113.23588,23.11962 | museum | 广州市荔湾区博物馆 | museum3 | 113.24400,23.12590 | museum | 1.08 | 10 | - |
| 成都 | 黄龙溪廊桥 | chinatravel | `ct_成都_315` | 103.98346,30.32445 | historic | 黄龙溪镇 | histown | 103.96993,30.31772 | ancient_town | 1.50 | 7 | B区块、类别差historic/ancient_town |
| 成都 | 元通古镇 | amap→chinatravel | `ct_成都_99` | 103.62309,30.72870 | attraction | 元通镇 | histown | 103.62395,30.73801 | ancient_town | 1.04 | 7 | B区块、类别差attraction/ancient_town |
| 成都 | 东郊记忆艺术区 | chinatravel | `ct_成都_269` | 104.14334,30.69092 | citywalk | 东郊记忆 | amap | 104.13213,30.67231 | attraction | 2.33 | 1 | 类别差citywalk/attraction |
| 杭州 | 杭州万科良渚文化艺术中心 | chinatravel | `ct_杭州_274` | 120.04390,30.36880 | art | 良渚古城遗址 | unesco | 119.98993,30.39418 | attraction | 5.90 | 15 | 类别差art/attraction |
| 杭州 | 中国茶叶博物馆龙井馆区 | chinatravel | `ct_杭州_364` | 120.12367,30.22304 | museum | 中国茶叶博物馆 | museum1 | 120.12097,30.23224 | museum | 1.06 | 12 | - |
| 武汉 | 黄陂木兰文化生态旅游区 | amap→chinatravel | `ct_武汉_16` | 114.30500,30.59280 | nature | 黄陂区木兰文化生态旅游区 | 5a | 114.37489,31.07725 | attraction | 54.28 | 14 | 类别差nature/attraction |
| 武汉 | 夜上黄鹤楼 | amap→chinatravel | `ct_武汉_10` | 114.16301,30.34744 | attraction | 黄鹤楼公园 | 5a | 114.30237,30.54450 | attraction | 25.66 | 14 | - |
| 武汉 | 武汉大学 | chinatravel | `ct_武汉_8` | 114.37767,30.54191 | attraction | 武汉大学万林艺术博物馆 | museum2 | 114.36303,30.53662 | museum | 1.52 | 11 | 类别差attraction/museum |
| 武汉 | 万林艺术博物馆 | amap→chinatravel | `ct_武汉_145` | 114.35760,30.52605 | museum | 武汉大学万林艺术博物馆 | museum2 | 114.36303,30.53662 | museum | 1.29 | 11 | - |
| 武汉 | 武汉大禹文化博物馆 | chinatravel | `ct_武汉_280` | 114.29642,30.55858 | museum | 武汉市晴川阁管理处（武汉大禹文化博物馆） | museum2 | 114.28445,30.55526 | museum | 1.20 | 11 | - |
| 武汉 | 武汉大学-风雨操场 | chinatravel | `ct_武汉_325` | 114.37162,30.54226 | attraction | 武汉大学万林艺术博物馆 | museum2 | 114.36303,30.53662 | museum | 1.03 | 11 | 类别差attraction/museum |
| 武汉 | 钱学森纪念馆 | chinatravel | `ct_武汉_299` | 114.53987,30.71752 | museum | 钱学森与武汉生物工程学院博物馆 | museum3 | 114.52662,30.71284 | museum | 1.37 | 10 | - |
| 武汉 | 武汉美术馆(汉口馆) | amap→chinatravel | `ct_武汉_53` | 114.29292,30.58396 | museum | 武汉美术馆 | artmuseum | 114.25395,30.56138 | museum | 4.50 | 9 | - |
| 武汉 | 黎黄陂路 | chinatravel | `ct_武汉_35` | 114.31360,30.58980 | attraction | 湖北省武汉市江岸区黎黄陂路历史文化街区 | street | 114.29943,30.58768 | historic | 1.38 | 8 | B区块、类别差attraction/historic |
| 武汉 | 大余湾 | amap→chinatravel | `ct_武汉_92` | 114.36111,31.02041 | ancient_town | 大余湾村 | histvillage | 114.37182,31.02952 | attraction | 1.44 | 2 | 类别差ancient_town/attraction |
| 深圳 | 东部华侨城直升机体验 | chinatravel | `ct_深圳_292` | 114.29976,22.62946 | theme_park | 南山区华侨城旅游度假区 | 5a | 113.98410,22.53510 | attraction | 34.06 | 14 | 类别差theme_park/attraction |
| 深圳 | 东部华侨城大侠谷 | amap→chinatravel | `ct_深圳_25` | 114.28797,22.62680 | nature | 南山区华侨城旅游度假区 | 5a | 113.98410,22.53510 | attraction | 32.82 | 14 | 类别差nature/attraction |
| 深圳 | 深圳华侨城旅游度假区 | amap→chinatravel | `ct_深圳_18` | 114.05800,22.54280 | theme_park | 南山区华侨城旅游度假区 | 5a | 113.98410,22.53510 | attraction | 7.64 | 14 | 类别差theme_park/attraction |
| 深圳 | 华侨城创意文化园 | amap→chinatravel | `ct_深圳_56` | 113.99381,22.53773 | park | 南山区华侨城旅游度假区 | 5a | 113.98410,22.53510 | attraction | 1.04 | 14 | 类别差park/attraction |
| 深圳 | 深圳博物馆-古代艺术馆 | amap→chinatravel | `ct_深圳_107` | 114.10043,22.54208 | museum | 深圳博物馆 | museum1 | 114.06152,22.54054 | museum | 4.00 | 12 | - |
| 深圳 | 深圳博物馆历史民俗馆 | chinatravel | `ct_深圳_220` | 114.07330,22.54694 | museum | 深圳博物馆 | museum1 | 114.06152,22.54054 | museum | 1.40 | 12 | - |
| 深圳 | 鹤湖新居 | chinatravel | `ct_深圳_268` | 114.27746,22.73108 | nature | 深圳市龙岗区客家民俗博物馆 | museum3 | 114.26453,22.72771 | museum | 1.38 | 10 | 类别差nature/museum |
| 深圳 | 深圳美术馆(新馆) | amap→chinatravel | `ct_深圳_137` | 114.01383,22.63628 | museum | 深圳美术馆 | artmuseum | 114.14724,22.57095 | museum | 15.50 | 9 | - |
| 苏州 | 夜游拙政园《拙政问雅》 | chinatravel | `ct_苏州_9913` | 120.61538,31.31360 | other | 拙政园 | unesco | 120.62863,31.32367 | park | 1.68 | 15 | 类别差other/park |
| 苏州 | 苏州博物馆西馆 | amap→chinatravel | `ct_苏州_27` | 120.74935,31.66993 | museum | 苏州博物馆（苏州民俗博物馆） | museum1 | 120.62946,31.32147 | museum | 40.38 | 12 | - |
| 苏州 | 苏州博物馆-特展厅 | chinatravel | `ct_苏州_338` | 120.63787,31.32698 | museum | 苏州博物馆（苏州民俗博物馆） | museum1 | 120.62946,31.32147 | museum | 1.01 | 12 | - |
| 苏州 | 黎里古镇 | amap→chinatravel | `ct_苏州_54` | 120.70900,30.98904 | attraction | 黎里镇 | histown | 120.84921,31.03820 | ancient_town | 14.44 | 7 | B区块、类别差attraction/ancient_town |
| 苏州 | 光福景区 | amap→chinatravel | `ct_苏州_179` | 120.37053,31.28535 | nature | 光福镇 | histown | 120.39252,31.28228 | ancient_town | 2.12 | 7 | B区块、类别差nature/ancient_town |
| 苏州 | 沙溪古镇 | amap→chinatravel | `ct_苏州_46` | 121.06584,31.56482 | attraction | 沙溪镇 | histown | 121.07649,31.55569 | ancient_town | 1.43 | 7 | B区块、类别差attraction/ancient_town |
| 苏州 | 明月湾古村 | amap→chinatravel | `ct_苏州_94` | 120.58600,31.29730 | attraction | 明月湾村 | histvillage | 120.28924,31.09325 | attraction | 36.22 | 2 | - |
| 苏州 | 东村古村 | chinatravel | `ct_苏州_239` | 120.29368,31.15902 | attraction | 东村 | histvillage | 120.61538,31.31360 | attraction | 35.08 | 2 | - |
| 重庆 | 武隆喀斯特旅游区 | amap→chinatravel | `ct_重庆_2` | 107.76802,29.41734 | nature | 武隆县喀斯特旅游区 | 5a | 107.78446,29.37088 | attraction | 5.41 | 14 | 类别差nature/attraction |
| 重庆 | 白帝城 | amap→chinatravel | `ct_重庆_105` | 109.59460,31.05547 | historic | 白帝城·瞿塘峡景区 | 5a | 109.57287,31.04610 | attraction | 2.32 | 14 | B区块、类别差historic/attraction |
| 重庆 | 巴蜀古代建筑博物馆 | chinatravel | `ct_重庆_248` | 106.34283,29.60742 | museum | 重庆市沙坪坝博物馆（重庆市沙坪坝巴蜀古代建筑博物馆） | museum2 | 106.33270,29.60389 | museum | 1.06 | 11 | - |
| 重庆 | 南川东街 | chinatravel | `ct_重庆_337` | 107.11658,29.15781 | attraction | 重庆市南川区南川东街 | street | 107.09900,29.15780 | historic | 1.71 | 8 | 类别差attraction/historic |
| 重庆 | 观音桥步行街 | amap→chinatravel | `ct_重庆_56` | 106.55516,29.57768 | attraction | 重庆市江北区观音桥商圈旅游休闲街区 | street | 106.53999,29.58329 | historic | 1.59 | 8 | B区块、类别差attraction/historic |
| 重庆 | 松溉古镇 | chinatravel | `ct_重庆_223` | 105.90523,29.05605 | attraction | 松溉镇 | histown | 105.89374,29.05625 | ancient_town | 1.12 | 7 | B区块、类别差attraction/ancient_town |
| 重庆 | 朝天门广场 | amap→chinatravel | `ct_重庆_37` | 106.58787,29.56680 | attraction | 朝天门大桥 | amap | 106.58190,29.58828 | attraction | 2.46 | 1 | - |

## B. 其他源可疑对（68 对，按城市/优先级差/距离排）

| 城市 | A 名（疑错针） | A source | A source_poi_id | A 坐标 | A cat | B 名（疑真实） | B source | B 坐标 | B cat | 距离km | 优先级差 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 上饶 | 万年县神农源景区 | baidu | `bacf53d3f8ed2a419e82ea1d` | 117.25808,28.70661 | nature | 神农源风景名胜区 | scenic | 117.05928,28.68552 | nature | 19.53 | 6 | B区块 |
| 东莞 | 石龙镇 | histown | `ht_eddd19f75e2a` | 113.87441,23.10584 | ancient_town | 东莞市石龙镇博物馆 | museum3 | 113.85757,23.10675 | museum | 1.73 | 3 | 类别差ancient_town/museum |
| 中卫 | 宁夏回族自治区中卫市沙坡头区向阳街旅游休闲街区 | street | `st_9f026a6640b2` | 105.18503,37.51427 | historic | 沙坡头区沙坡头旅游景区 | 5a | 105.02289,37.45991 | attraction | 15.53 | 6 | B区块、类别差historic/attraction |
| 丽江 | 丽江玉龙雪山风景名胜区 | scenic | `scenic_0217` | 100.22228,26.90224 | nature | 玉龙纳西族自治县玉龙雪山景区 | 5a | 100.19833,27.10500 | attraction | 22.67 | 9 | B区块、类别差nature/attraction |
| 五大连池 | 五大连池世界地质公园博物馆 | museum2 | `m2_2d605e6e1357` | 126.13432,48.64656 | museum | 五大连池景区 | 5a | 126.26501,48.69650 | attraction | 11.09 | 3 | B区块、类别差museum/attraction |
| 北京 | 北京奥林匹克公园 | baidu | `5644cf50f6cf052382a12ec3` | 116.39292,40.00443 | attraction | 北京奥运博物馆 | museum3 | 116.39660,39.99050 | museum | 1.58 | 11 | 类别差attraction/museum |
| 北京 | 八达岭-十三陵风景名胜区 | scenic | `scenic_0001` | 115.77531,40.46621 | nature | 昌平区明十三陵景区 | 5a | 116.24053,40.27913 | attraction | 44.56 | 9 | B区块、类别差nature/attraction |
| 北京 | 中国美术馆 | artmuseum | `a1_907b17111648` | 116.40893,39.92455 | museum | 中国国家博物馆 | museum1 | 116.39776,39.90318 | museum | 2.56 | 3 | - |
| 北京 | 妙应寺白塔 | reservation | `resv_北京_妙应寺白塔` | 116.36331,39.92566 | attraction | 白塔寺 | chinatravel | 116.37613,39.93214 | attraction | 1.31 | 3 | - |
| 北京 | 中央电视塔景区 | baidu | `2949a58c58499370a1d230e5` | 116.30701,39.91885 | nature | 中央广播电视塔 | chinatravel | 116.31970,39.92678 | attraction | 1.40 | 1 | 类别差nature/attraction |
| 厦门 | 鼓浪屿-万石山风景名胜区 | scenic | `scenic_0080` | 118.09414,24.44569 | nature | 鼓浪屿 | unesco | 118.06690,24.44483 | attraction | 2.76 | 10 | 类别差nature/attraction |
| 周口 | 太昊陵 | baidu | `fd246495eb760b4e04026f8f` | 114.88750,33.75077 | attraction | 太昊伏羲陵文化旅游区 | 5a | 114.89830,33.73914 | attraction | 1.63 | 15 | - |
| 呼伦贝尔 | 内蒙古自治区呼伦贝尔市海拉尔区呼伦贝尔古城旅游休闲街区 | street | `st_55f09cb7f117` | 119.74591,49.20965 | historic | 呼伦贝尔大草原·莫尔格勒河景区 | 5a | 119.90324,49.57381 | attraction | 42.06 | 6 | B区块、类别差historic/attraction |
| 呼和浩特 | 内蒙古自治区呼和浩特市新城区恼包旅游休闲街区 | street | `st_09cd3b0d0702` | 111.66500,40.85820 | historic | 内蒙古博物院 | museum1 | 111.73863,40.83991 | museum | 6.52 | 4 | 类别差historic/museum |
| 和田 | 新疆维吾尔自治区和田地区和田市团城旅游休闲街区 | street | `st_ed7434790547` | 79.93590,37.11190 | historic | 和田地区博物馆 | museum2 | 79.92718,37.09188 | museum | 2.36 | 3 | 类别差historic/museum |
| 大理 | 云南省大理白族自治州大理市双廊镇民族文化街 | street | `st_edfc3fde75d5` | 100.19297,25.91318 | historic | 大理白族自治州博物馆 | museum2 | 100.23162,25.59722 | museum | 35.35 | 3 | 类别差historic/museum |
| 大理 | 云南省大理白族自治州巍山彝族回族自治县南诏古街 | street | `st_c6f713aee626` | 100.15555,25.70267 | historic | 大理白族自治州博物馆 | museum2 | 100.23162,25.59722 | museum | 13.99 | 3 | 类别差historic/museum |
| 宁德 | 鸳鸯溪风景名胜区 | scenic | `scenic_0084` | 119.11595,27.05307 | nature | 白水洋·鸳鸯溪旅游景区 | 5a | 118.98600,26.90860 | attraction | 20.59 | 9 | B区块、类别差nature/attraction |
| 宁波 | 宁波市天一阁博物院（宁波市保国寺古建筑博物馆） | museum1 | `m1_0a8cd3e2a6e5` | 121.52106,29.97988 | museum | 天一阁·月湖景区 | 5a | 121.54303,29.86776 | attraction | 12.65 | 2 | B区块、类别差museum/attraction |
| 安顺 | 龙宫风景名胜区 | scenic | `scenic_0198` | 105.88579,26.10695 | nature | 西秀区龙宫景区 | 5a | 105.89028,26.09750 | attraction | 1.14 | 9 | B区块、类别差nature/attraction |
| 宜昌 | 长阳土家族自治县博物馆 | museum3 | `m3_d79cb2ae3923` | 111.20893,30.47409 | museum | 长阳土家族自治县清江画廊景区 | 5a | 111.14705,30.44467 | attraction | 6.77 | 4 | B区块、类别差museum/attraction |
| 岳阳 | 岳阳楼洞庭湖风景名胜区 | scenic | `scenic_0141` | 113.09726,29.34876 | nature | 岳阳楼君山岛景区 | 5a | 113.09521,29.38162 | attraction | 3.66 | 9 | B区块、类别差nature/attraction |
| 岳阳 | 湖南省岳阳市岳阳楼区洞庭南路历史文化街区 | street | `st_d04541cbc0cb` | 113.09198,29.36683 | historic | 岳阳楼君山岛景区 | 5a | 113.09521,29.38162 | attraction | 1.67 | 6 | B区块、类别差historic/attraction |
| 常熟 | 沙家浜镇 | histown | `ht_c3b163f3ad1f` | 120.84736,31.54577 | ancient_town | 沙家浜虞山尚湖旅游区 | 5a | 120.69149,31.64620 | attraction | 18.51 | 7 | 类别差ancient_town/attraction |
| 广元 | 剑门蜀道风景名胜区 | scenic | `scenic_0182` | 105.78645,32.42148 | nature | 剑门蜀道剑门关旅游景区 | 5a | 105.57510,32.22177 | attraction | 29.79 | 9 | B区块、类别差nature/attraction |
| 广州 | 广州市北京路文化旅游区 | baidu | `61af64fa29975758f942b281` | 113.26904,23.12395 | nature | 北京路步行街 | amap | 113.26010,22.98663 | attraction | 15.30 | 1 | 类别差nature/attraction |
| 广州 | 广州市中国共产党第三次全国代表大会会址纪念馆旅游区 | baidu | `63faac026ab59d00b5f42fc9` | 113.29590,23.11823 | museum | 中国共产党第三次全国代表大会会址纪念馆 | chinatravel | 113.30796,23.12242 | museum | 1.32 | 1 | - |
| 张家口 | 河北省张家口市崇礼区富龙风铃乐谷休闲街区 | street | `st_baa040eb8b56` | 115.28300,40.97460 | historic | 张家口市博物馆 | museum2 | 114.89173,40.76826 | museum | 40.11 | 3 | 类别差historic/museum |
| 张家界 | 《张家界千古情》 | show | `show:张家界:《张家界千古情》` | 110.48927,29.12343 | entertainment | 武陵源 | unesco | 110.47166,29.34289 | attraction | 24.46 | 11 | 类别差entertainment/attraction |
| 张家界 | 张家界市博物馆 | museum2 | `m2_a5f590015e6d` | 110.45473,29.13230 | museum | 武陵源 | unesco | 110.47166,29.34289 | attraction | 23.47 | 4 | 类别差museum/attraction |
| 张家界 | 武陵源天门山旅游区 | 5a | `5a_199` | 110.55100,29.34570 | attraction | 武陵源 | unesco | 110.47166,29.34289 | attraction | 7.70 | 1 | - |
| 恩施 | 湖北省恩施土家族苗族自治州宣恩县仙山贡水兴隆老街 | street | `st_d31c1cd7e1ad` | 109.48528,29.98628 | historic | 恩施土家族苗族自治州博物馆 | museum1 | 109.48000,30.29520 | museum | 34.35 | 4 | 类别差historic/museum |
| 恩施 | 恩施土家族苗族自治州博物馆 | museum1 | `m1_adb133ac3445` | 109.48000,30.29520 | museum | 恩施州腾龙洞景区 | 5a | 109.50838,30.31022 | attraction | 3.20 | 2 | B区块、类别差museum/attraction |
| 成都 | 安仁镇 | histown | `ht_5fba029dd099` | 103.61615,30.51404 | ancient_town | 安仁古镇景区 | 5a | 103.62548,30.50452 | attraction | 1.39 | 7 | B区块、类别差ancient_town/attraction |
| 拉萨 | 西藏自治区拉萨市城关区八廓街 | street | `st_0e23c9386a16` | 91.12994,29.65016 | historic | 西藏博物馆 | museum1 | 91.09885,29.64845 | museum | 3.01 | 4 | 类别差historic/museum |
| 晋中 | 《又见平遥》 | show | `show:晋中（平遥）:《又见平遥》` | 112.13139,37.17060 | entertainment | 山西省晋中市平遥县又见平遥文化产业园区印象新街 | street | 111.99686,37.23603 | historic | 13.96 | 4 | 类别差entertainment/historic |
| 晋中 | 平遥县平遥古城景区 | 5a | `5a_029` | 112.18354,37.20416 | attraction | 平遥古城 | unesco | 112.16097,37.20205 | attraction | 2.01 | 1 | - |
| 景德镇 | 景德镇陶瓷民俗博物馆 | museum2 | `m2_b85366313acb` | 117.18377,29.28364 | museum | 景德镇中国陶瓷博物馆 | museum1 | 117.17552,29.29323 | museum | 1.33 | 1 | - |
| 杭州 | 良渚文化村 | amap | `BV10184624` | 120.02592,30.36482 | attraction | 良渚古城遗址 | unesco | 119.98993,30.39418 | attraction | 4.75 | 14 | - |
| 杭州 | 西溪国家湿地公园 | baidu | `44fb383656ad5d986c3e1ba9` | 120.06492,30.26723 | attraction | 杭州西溪湿地博物馆 | museum2 | 120.06082,30.25619 | museum | 1.29 | 12 | 类别差attraction/museum |
| 杭州 | 中国湿地博物馆 | museum2 | `m2_86cdc8d85172` | 120.09886,30.26792 | museum | 西湖区西溪湿地旅游区 | 5a | 120.06492,30.26723 | attraction | 3.26 | 3 | 类别差museum/attraction |
| 杭州 | 拱宸桥·桥西历史文化街区 | curated | `curated:杭州:拱宸桥·桥西历史文化街区` | 120.13794,30.31731 | attraction | 拱宸桥 | amap | 120.15014,30.32220 | attraction | 1.29 | 3 | - |
| 杭州 | 杭州西溪湿地博物馆 | museum2 | `m2_d5c6b159f55e` | 120.06082,30.25619 | museum | 西湖区西溪湿地旅游区 | 5a | 120.06492,30.26723 | attraction | 1.29 | 3 | 类别差museum/attraction |
| 楚雄 | 云南省楚雄彝族自治州楚雄市彝人古镇主题街区 | street | `st_087d5a52b09f` | 101.51967,25.05778 | historic | 楚雄彝族自治州博物馆 | museum2 | 101.54766,25.02386 | museum | 4.71 | 3 | 类别差historic/museum |
| 武汉 | 东湖生态旅游风景区 | curated | `curated:武汉:东湖生态旅游风景区` | 114.41326,30.54868 | nature | 武汉东湖风景名胜区 | scenic | 114.34563,30.59199 | nature | 8.07 | 7 | B区块 |
| 江山 | 廿八都镇 | histown | `ht_207d2f0e82c8` | 118.62700,28.73720 | ancient_town | 江郎山·廿八都旅游区 | 5a | 118.48355,28.29051 | attraction | 51.61 | 7 | 类别差ancient_town/attraction |
| 江门 | 开平碉楼文化旅游区 | 5a | `5a_225` | 112.56487,22.34975 | attraction | 开平碉楼与村落 | unesco | 112.52582,22.25891 | attraction | 10.87 | 1 | - |
| 洛阳 | 洛阳龙门风景名胜区 | scenic | `scenic_0122` | 112.47569,34.57946 | nature | 龙门石窟 | unesco | 112.47592,34.55444 | nature | 2.78 | 10 | - |
| 深圳 | 深圳湾公园 | baidu | `df2fbad8ddee98cfe9f85366` | 113.95312,22.50382 | attraction | 深圳湾体育中心 | amap | 113.95018,22.52030 | - | 1.86 | 1 | - |
| 湘西 | 老司城村 | histvillage | `histvillage_0358` | 109.97701,28.99438 | attraction | 永顺县老司城博物馆 | museum3 | 109.93941,29.01287 | museum | 4.19 | 8 | 类别差attraction/museum |
| 湘西 | 湘西土家族苗族自治州博物馆 | museum2 | `m2_d5fde479d51e` | 109.67140,28.21774 | museum | 湘西土家族苗族自治州凤凰古城旅游区 | 5a | 109.60559,27.94866 | attraction | 30.61 | 3 | 类别差museum/attraction |
| 湘西 | 湖南省湘西土家族苗族自治州吉首市乾州古城旅游休闲街区 | street | `st_2da1fa71acee` | 109.69849,28.25427 | historic | 湘西土家族苗族自治州博物馆 | museum2 | 109.67140,28.21774 | museum | 4.85 | 3 | 类别差historic/museum |
| 湘西 | 湘西土家族苗族自治州地质公园博物馆 | museum3 | `m3_795e01d0ef43` | 109.73900,28.31170 | museum | 湘西土家族苗族自治州博物馆 | museum2 | 109.67140,28.21774 | museum | 12.37 | 1 | - |
| 漳州 | 福建省漳州市芗城区漳州古城旅游休闲街区 | street | `st_fc50ac7abc0d` | 117.65381,24.50525 | historic | 福建省漳州市博物馆 | museum2 | 117.64700,24.51320 | museum | 1.12 | 3 | 类别差historic/museum |
| 石家庄 | 西柏坡-天桂山风景名胜区 | scenic | `scenic_0009` | 113.74377,38.25730 | nature | 石家庄平山县西柏坡景区 | 5a | 113.94221,38.34108 | attraction | 19.66 | 9 | B区块、类别差nature/attraction |
| 石家庄 | 河北省石家庄市新华区湾里庙步行街 | street | `st_59451cd7c468` | 114.48737,38.04413 | historic | 石家庄市博物馆 | museum2 | 114.51280,38.04593 | museum | 2.24 | 3 | 类别差historic/museum |
| 西安 | 华清宫 | curated | `curated:西安:华清宫` | 109.21505,34.35886 | attraction | 临潼区华清池景区 | baidu | 109.25545,34.41455 | nature | 7.22 | 1 | B区块、类别差attraction/nature |
| 连云港 | 连云港市赣榆区博物馆 | museum3 | `m3_e151f55fa267` | 119.17212,34.83798 | museum | 连云港市博物馆 | museum1 | 119.22399,34.59394 | museum | 27.55 | 2 | - |
| 通化 | 高句丽文物古迹旅游景区 | 5a | `5a_054` | 126.20295,41.13953 | attraction | 高句丽王城、王陵及贵族墓葬 | unesco | 126.19293,41.15906 | attraction | 2.33 | 1 | - |
| 遵义 | 赤水丹霞旅游区 | 5a | `5a_279` | 105.74680,28.37613 | attraction | 中国丹霞 | unesco | 106.04679,28.41860 | nature | 29.72 | 1 | 类别差attraction/nature |
| 邯郸 | 广府镇 | histown | `ht_7045e496a166` | 114.71408,36.72037 | ancient_town | 永年县广府古城景区 | 5a | 114.72930,36.70198 | attraction | 2.45 | 7 | B区块、类别差ancient_town/attraction |
| 银川 | 西夏王陵风景名胜区 | scenic | `scenic_0238` | 106.01967,38.44313 | nature | 西夏陵 | unesco | 105.99145,38.43544 | attraction | 2.60 | 10 | 类别差nature/attraction |
| 银川 | 宁夏回族自治区银川市西夏区贺兰山·漫葡小镇旅游休闲街区 | street | `st_5a4ddd1ece39` | 106.07028,38.62160 | historic | 宁夏回族自治区博物馆 | museum1 | 106.23512,38.48468 | museum | 20.91 | 4 | 类别差historic/museum |
| 银川 | 宁夏回族自治区地质博物馆 | museum2 | `m2_26fb49df77c5` | 106.27818,38.46637 | museum | 宁夏回族自治区博物馆 | museum1 | 106.23512,38.48468 | museum | 4.27 | 1 | - |
| 长春 | "八大部"-净月潭风景名胜区 | scenic | `scenic_0032` | 125.45324,43.80127 | nature | 南关区净月潭景区 | 5a | 125.42907,43.78365 | attraction | 2.76 | 9 | B区块、类别差nature/attraction |
| 阿克苏 | 阿克苏地区文博院（博物馆） | museum2 | `m2_76ef650fac4a` | 80.24039,41.17232 | museum | 阿克苏地区天山托木尔景区 | 5a | 80.26350,41.16770 | nature | 2.00 | 3 | B区块、类别差museum/nature |
| 阿坝 | 阿坝藏族羌族自治州九寨沟县九寨沟景区 | 5a | `5a_257` | 103.86640,33.29528 | attraction | 九寨沟风景名胜区 | unesco | 103.90218,33.19790 | nature | 11.33 | 1 | B区块、类别差attraction/nature |
| 马鞍山 | 采石风景名胜区 | scenic | `scenic_0071` | 118.50700,31.67060 | nature | 长江采石矶文化生态旅游区 | 5a | 118.47844,31.49173 | attraction | 20.07 | 9 | 类别差nature/attraction |

## C. 地理核警示（山/湖/岛/河等通用地理名匹配或大范围实体，两入口可合法 >1km，195 对）

| 城市 | A 名（疑错针） | A source | A source_poi_id | A 坐标 | A cat | B 名（疑真实） | B source | B 坐标 | B cat | 距离km | 优先级差 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 上海 | 上海博物馆(东馆) | amap→chinatravel | `ct_上海_59` | 121.54136,31.21815 | museum | 上海博物馆 | museum1 | 121.47558,31.22829 | museum | 6.36 | 12 | - |
| 上海 | 上海世博展览馆 | amap→chinatravel | `ct_上海_175` | 121.48994,31.18272 | museum | 上海世博会博物馆 | museum2 | 121.48208,31.19453 | museum | 1.51 | 11 | - |
| 上海 | 上海世博园 | amap→chinatravel | `ct_上海_145` | 121.49227,31.18482 | nature | 上海世博会博物馆 | museum2 | 121.48208,31.19453 | museum | 1.45 | 11 | 类别差nature/museum |
| 上海 | 上海当代艺术馆 | chinatravel | `ct_上海_273` | 121.48392,31.23540 | nature | 上海当代艺术博物馆 | artmuseum | 121.49849,31.20111 | museum | 4.06 | 9 | 类别差nature/museum |
| 上海 | 上海外滩花间堂·愉园 | chinatravel | `ct_上海_7852` | 121.49193,31.22988 | nature | 上海外滩美术馆 | artmuseum | 121.48765,31.24123 | museum | 1.33 | 9 | 类别差nature/museum |
| 上海 | 上海外滩12号大楼 | chinatravel | `ct_上海_293` | 121.50093,31.23968 | nature | 上海外滩美术馆 | artmuseum | 121.48765,31.24123 | museum | 1.27 | 9 | 类别差nature/museum |
| 北京 | 大运河博物馆 | amap→chinatravel | `ct_北京_108` | 116.80321,40.11611 | museum | 北京大运河文化旅游景区 | 5a | 116.66615,39.91536 | attraction | 25.19 | 14 | B区块、类别差museum/attraction |
| 北京 | 京杭大运河 | amap→chinatravel | `ct_北京_238` | 116.72824,39.88900 | historic | 北京大运河文化旅游景区 | 5a | 116.66615,39.91536 | attraction | 6.05 | 14 | B区块、类别差historic/attraction |
| 北京 | 八达岭古长城(残长城) | amap→chinatravel | `ct_北京_93` | 115.98835,40.34827 | nature | 八达岭-十三陵风景名胜区 | scenic | 115.77531,40.46621 | nature | 22.30 | 5 | B区块 |
| 北京 | 八达岭野生动物世界 | amap→chinatravel | `ct_北京_43` | 115.99234,40.35933 | theme_park | 八达岭-十三陵风景名胜区 | scenic | 115.77531,40.46621 | nature | 21.88 | 5 | B区块、类别差theme_park/nature |
| 南京 | 中山陵园史迹陈列 | chinatravel | `ct_南京_243` | 118.84609,32.05055 | nature | 钟山风景名胜区－中山陵园风景区 | 5a | 118.78170,31.99785 | attraction | 8.44 | 14 | B区块、类别差nature/attraction |
| 南京 | 中山陵景区 | amap→chinatravel | `ct_南京_9` | 118.84030,32.04590 | nature | 钟山风景名胜区－中山陵园风景区 | 5a | 118.78170,31.99785 | attraction | 7.68 | 14 | B区块、类别差nature/attraction |
| 南京 | 钟山风景名胜区 | amap→chinatravel | `ct_南京_5` | 118.84030,32.04590 | nature | 钟山风景名胜区－中山陵园风景区 | 5a | 118.78170,31.99785 | attraction | 7.68 | 14 | B区块、类别差nature/attraction |
| 南京 | 钟山风景名胜区-燕雀湖 | amap→chinatravel | `ct_南京_155` | 118.83042,32.04817 | nature | 钟山风景名胜区－中山陵园风景区 | 5a | 118.78170,31.99785 | attraction | 7.24 | 14 | B区块、类别差nature/attraction |
| 南京 | 牛首山圣象广场 | chinatravel | `ct_南京_307` | 118.76231,31.93238 | nature | 牛首山文化旅游区 | amap | 118.76012,31.90715 | nature | 2.81 | 1 | - |
| 南京 | 汤山紫清湖旅游区 | amap→chinatravel | `ct_南京_54` | 119.03294,32.06407 | nature | 紫清湖野生动物世界 | amap | 119.05125,32.06774 | theme_park | 1.77 | 1 | 类别差nature/theme_park |
| 南京 | 牛首山弘觉寺塔 | amap→chinatravel | `ct_南京_150` | 118.74368,31.90553 | nature | 牛首山文化旅游区 | amap | 118.76012,31.90715 | nature | 1.56 | 1 | - |
| 南京 | 南京紫清湖生态旅游温泉度假区 | chinatravel | `ct_南京_6597` | 119.03652,32.06328 | attraction | 紫清湖野生动物世界 | amap | 119.05125,32.06774 | theme_park | 1.47 | 1 | 类别差attraction/theme_park |
| 广州 | 白云山国家级风景名胜区-玻璃桥 | amap→chinatravel | `ct_广州_160` | 113.28877,23.15468 | nature | 白云山景区 | 5a | 113.29727,23.18054 | attraction | 3.00 | 14 | B区块、类别差nature/attraction |
| 成都 | 都江堰景区鱼嘴分水堤 | amap→chinatravel | `ct_成都_77` | 104.06628,30.57294 | nature | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 60.06 | 15 | - |
| 成都 | 都江堰·玫瑰花溪谷 | chinatravel | `ct_成都_263` | 103.77658,30.98884 | theme_park | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 21.84 | 15 | 类别差theme_park/nature |
| 成都 | 都江堰文庙 | chinatravel | `ct_成都_256` | 103.62612,31.00460 | attraction | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 12.39 | 15 | 类别差attraction/nature |
| 成都 | 都江堰西街 | chinatravel | `ct_成都_180` | 103.62317,31.00121 | attraction | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 11.93 | 15 | 类别差attraction/nature |
| 成都 | 都江堰青城道温泉 | chinatravel | `ct_成都_1288` | 103.64700,30.98830 | attraction | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 11.90 | 15 | 类别差attraction/nature |
| 成都 | 都江堰景区 | amap→chinatravel | `ct_成都_1` | 103.60911,31.00256 | nature | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 11.56 | 15 | - |
| 成都 | 青城山skydive跳伞基地 | chinatravel | `ct_成都_243` | 103.62152,30.84789 | theme_park | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 7.96 | 15 | 类别差theme_park/nature |
| 成都 | 青城山 | amap→chinatravel | `ct_成都_4` | 103.59485,30.89953 | nature | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 2.43 | 15 | - |
| 成都 | 都江堰中华大熊猫苑(原熊猫乐园) | amap→chinatravel | `ct_成都_8` | 103.59485,30.89953 | theme_park | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 2.43 | 15 | 类别差theme_park/nature |
| 成都 | 青城山尊铂森林温泉 | chinatravel | `ct_成都_1469` | 103.56768,30.88944 | attraction | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 1.65 | 15 | 类别差attraction/nature |
| 杭州 | 梅家坞村 | amap→chinatravel | `ct_杭州_182` | 120.08929,30.20309 | attraction | 杭州西湖文化景观 | unesco | 120.14556,30.23519 | nature | 6.48 | 15 | 类别差attraction/nature |
| 杭州 | 西湖文化广场 | amap→chinatravel | `ct_杭州_41` | 120.16132,30.27172 | nature | 杭州西湖文化景观 | unesco | 120.14556,30.23519 | nature | 4.34 | 15 | - |
| 杭州 | 杭州西湖风景名胜区-三天竺法镜寺 | chinatravel | `ct_杭州_211` | 120.11636,30.24076 | nature | 杭州西湖文化景观 | unesco | 120.14556,30.23519 | nature | 2.87 | 15 | - |
| 杭州 | 白堤 | amap→chinatravel | `ct_杭州_100` | 120.12142,30.22255 | attraction | 杭州西湖文化景观 | unesco | 120.14556,30.23519 | nature | 2.71 | 15 | 类别差attraction/nature |
| 杭州 | 岳王庙景区 | amap→chinatravel | `ct_杭州_13` | 120.13495,30.25195 | attraction | 杭州西湖文化景观 | unesco | 120.14556,30.23519 | nature | 2.12 | 15 | 类别差attraction/nature |
| 杭州 | 西泠印社 | amap→chinatravel | `ct_杭州_113` | 120.14226,30.25171 | museum | 杭州西湖文化景观 | unesco | 120.14556,30.23519 | nature | 1.86 | 15 | 类别差museum/nature |
| 杭州 | 千岛湖龙晨水搏乐园 | chinatravel | `ct_杭州_315` | 119.11301,29.73772 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 52.29 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖鱼跃龙门漂流 | chinatravel | `ct_杭州_240` | 119.10976,29.73806 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 52.05 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖啤酒博物院 | amap→chinatravel | `ct_杭州_139` | 119.14796,29.60890 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 49.13 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖啤酒小镇 | amap→chinatravel | `ct_杭州_108` | 119.14679,29.60953 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 49.04 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖天迹热气球 | amap→chinatravel | `ct_杭州_121` | 119.14679,29.60953 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 49.04 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖燃擎·卡丁车俱乐部 | amap→chinatravel | `ct_杭州_120` | 119.14696,29.60732 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 48.98 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖欢乐水世界 | amap→chinatravel | `ct_杭州_159` | 119.11490,29.59899 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 45.75 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖巨网捕鱼 | chinatravel | `ct_杭州_341` | 119.10738,29.60793 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 45.37 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖钓鱼岛水上乐园 | chinatravel | `ct_杭州_331` | 119.10737,29.60797 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 45.37 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖希尔顿水上乐园 | chinatravel | `ct_杭州_83` | 119.08935,29.60658 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 43.67 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖沪马飞行营地 | chinatravel | `ct_杭州_5264` | 119.07821,29.60694 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 42.67 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖希尔顿休闲游艇俱乐部 | amap→chinatravel | `ct_杭州_148` | 119.07821,29.60694 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 42.67 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖仙人谷漂流 | chinatravel | `ct_杭州_221` | 119.09102,29.42804 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 41.73 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖进贤湾豪华游艇 | chinatravel | `ct_杭州_346` | 119.04785,29.64631 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 41.71 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖石林景区 | amap→chinatravel | `ct_杭州_89` | 119.09023,29.46978 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 41.31 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖农夫山泉生产基地 | chinatravel | `ct_杭州_336` | 119.06480,29.59456 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 40.99 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖天屿景区 | amap→chinatravel | `ct_杭州_27` | 119.04603,29.63118 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 40.82 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖“月光之恋”光影艺术夜游 | chinatravel | `ct_杭州_126` | 119.04478,29.60834 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 39.70 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖梦想5号游船 | chinatravel | `ct_杭州_246` | 119.04334,29.60744 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 39.53 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 杭州千岛湖开元森泊焕境乐园 | amap→chinatravel | `ct_杭州_64` | 119.03810,29.61499 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 39.38 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖伯爵号豪华游轮 | amap→chinatravel | `ct_杭州_66` | 119.03402,29.60473 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 38.59 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖明豪湖边有个乐园 | amap→chinatravel | `ct_杭州_127` | 119.02966,29.60147 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 38.06 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖梦之岛乐园 | chinatravel | `ct_杭州_342` | 119.02452,29.59667 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 37.40 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖中心湖区 | amap→chinatravel | `ct_杭州_12` | 119.01456,29.59370 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 36.39 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖乐游环湖骑行 | chinatravel | `ct_杭州_288` | 119.01493,29.58530 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 36.10 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖红叶湾水上乐园 | chinatravel | `ct_杭州_243` | 118.98402,29.63781 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 35.83 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖帆船中心 | chinatravel | `ct_杭州_327` | 119.00794,29.48707 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 33.35 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖城中湖休闲游 | amap→chinatravel | `ct_杭州_152` | 118.92388,29.56698 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 27.14 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖景区 | amap→chinatravel | `ct_杭州_4` | 118.92388,29.56698 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 27.14 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖豪华休闲游 | amap→chinatravel | `ct_杭州_116` | 118.92388,29.56698 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 27.14 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖东南湖区 | amap→chinatravel | `ct_杭州_23` | 118.92388,29.56698 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 27.14 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖冰火岛ATV山地越野车俱乐部 | chinatravel | `ct_杭州_216` | 118.87997,29.56979 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 23.39 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖红山谷景区 | amap→chinatravel | `ct_杭州_65` | 118.86392,29.38607 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 21.83 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖华美胜地度假区 | chinatravel | `ct_杭州_219` | 118.85256,29.55052 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 20.07 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 杭州西湖丝绸文化博物馆 | chinatravel | `ct_杭州_273` | 120.10797,30.18107 | museum | 杭州西湖风景区 | 5a | 120.12142,30.22255 | attraction | 4.79 | 14 | B区块、类别差museum/attraction |
| 杭州 | 杭州西湖相宜妆园 | chinatravel | `ct_杭州_5404` | 120.13000,30.25960 | other | 杭州西湖风景区 | 5a | 120.12142,30.22255 | attraction | 4.20 | 14 | B区块、类别差other/attraction |
| 杭州 | 杭州西湖云上茶宿 | chinatravel | `ct_杭州_5490` | 120.11143,30.24556 | nature | 杭州西湖风景区 | 5a | 120.12142,30.22255 | attraction | 2.73 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖水下千年 | chinatravel | `ct_杭州_339` | 118.68377,29.47660 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 1.95 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖西南湖区 | chinatravel | `ct_杭州_293` | 118.68373,29.47669 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 1.95 | 14 | B区块、类别差nature/attraction |
| 杭州 | 浙江大学(之江校区) | chinatravel | `ct_杭州_224` | 120.13595,30.19655 | attraction | 浙江大学艺术与考古博物馆 | museum1 | 120.07157,30.29777 | museum | 12.84 | 12 | 类别差attraction/museum |
| 杭州 | 浙江省博物馆(之江馆区) | amap→chinatravel | `ct_杭州_30` | 120.10229,30.16023 | museum | 浙江省博物馆 | museum1 | 120.14359,30.25114 | museum | 10.86 | 12 | - |
| 杭州 | 浙江大学(玉泉校区) | chinatravel | `ct_杭州_101` | 120.13407,30.26795 | attraction | 浙江大学艺术与考古博物馆 | museum1 | 120.07157,30.29777 | museum | 6.86 | 12 | 类别差attraction/museum |
| 杭州 | 浙江自然博物院(杭州馆) | amap→chinatravel | `ct_杭州_40` | 120.13000,30.25960 | museum | 浙江自然博物院 | museum1 | 120.16460,30.27702 | museum | 3.85 | 12 | - |
| 杭州 | 富春江夜游 | amap→chinatravel | `ct_杭州_177` | 119.68321,29.80834 | attraction | 富春江-新安江风景名胜区 | scenic | 119.28508,29.47789 | nature | 53.20 | 5 | B区块、类别差attraction/nature |
| 杭州 | 新安江 | chinatravel | `ct_杭州_258` | 119.13213,29.55071 | nature | 富春江-新安江风景名胜区 | scenic | 119.28508,29.47789 | nature | 16.87 | 5 | B区块 |
| 杭州 | 天目山景区 | amap→chinatravel | `ct_杭州_77` | 119.47129,30.34997 | nature | 东天目山景区 | amap | 119.51487,30.34421 | nature | 4.23 | 1 | B区块 |
| 武汉 | 江汉路步行街 | chinatravel | `ct_武汉_19` | 114.30039,30.58662 | attraction | 湖北省武汉市江汉区江汉路步行街区 | street | 114.28800,30.58361 | historic | 1.23 | 8 | B区块、类别差attraction/historic |
| 武汉 | 武汉东湖海洋世界 | amap→chinatravel | `ct_武汉_30` | 114.37185,30.56849 | nature | 武汉东湖风景名胜区 | scenic | 114.34563,30.59199 | nature | 3.62 | 5 | B区块 |
| 武汉 | 武汉东湖飞鸟世界 | amap→chinatravel | `ct_武汉_59` | 114.37577,30.57456 | nature | 武汉东湖风景名胜区 | scenic | 114.34563,30.59199 | nature | 3.48 | 5 | B区块 |
| 深圳 | 观澜湖生态运动公社 | amap→chinatravel | `ct_深圳_49` | 114.03026,22.72519 | nature | 龙华区观澜湖休闲旅游区 | 5a | 114.07381,22.72964 | attraction | 4.49 | 14 | 类别差nature/attraction |
| 深圳 | 梧桐山艺术小镇 | chinatravel | `ct_深圳_236` | 114.20533,22.59342 | nature | 梧桐山风景名胜区 | scenic | 114.20255,22.57691 | nature | 1.86 | 5 | B区块 |
| 苏州 | 苏州市吴中太湖旅游区 | amap→chinatravel | `ct_苏州_62` | 120.42521,31.09328 | nature | 吴中区太湖旅游区 | 5a | 120.44333,31.21990 | attraction | 14.19 | 14 | 类别差nature/attraction |
| 苏州 | 金鸡湖游船 | amap→chinatravel | `ct_苏州_35` | 120.70635,31.28265 | nature | 金鸡湖旅游区 | 5a | 120.70647,31.31103 | attraction | 3.16 | 14 | 类别差nature/attraction |
| 苏州 | 苏州金鸡湖美术馆 | amap→chinatravel | `ct_苏州_143` | 120.70261,31.32120 | museum | 金鸡湖旅游区 | 5a | 120.70647,31.31103 | attraction | 1.19 | 14 | 类别差museum/attraction |
| 苏州 | 香雪海 | amap→chinatravel | `ct_苏州_98` | 120.57525,31.29056 | nature | 光福镇 | histown | 120.39252,31.28228 | ancient_town | 17.39 | 7 | B区块、类别差nature/ancient_town |
| 重庆 | 金佛山飞拉达 | chinatravel | `ct_重庆_318` | 107.19433,28.93313 | theme_park | 金佛山-神龙峡风景区 | 5a | 107.10421,29.15250 | attraction | 25.92 | 14 | B区块、类别差theme_park/attraction |
| 重庆 | 阿依河漂流 | amap→chinatravel | `ct_重庆_203` | 108.19760,29.35365 | nature | 彭水县阿依河景区 | 5a | 108.15814,29.17143 | attraction | 20.62 | 14 | B区块、类别差nature/attraction |
| 重庆 | 金佛山北坡滑雪场 | chinatravel | `ct_重庆_211` | 107.20187,29.02575 | theme_park | 金佛山-神龙峡风景区 | 5a | 107.10421,29.15250 | attraction | 16.99 | 14 | B区块、类别差theme_park/attraction |
| 重庆 | 巫山小三峡 | amap→chinatravel | `ct_重庆_13` | 109.89490,31.09057 | nature | 小三峡小小三峡旅游区 | 5a | 109.90115,31.23392 | attraction | 15.95 | 14 | 类别差nature/attraction |
| 重庆 | 小小三峡 | amap→chinatravel | `ct_重庆_76` | 109.78574,31.26445 | nature | 小三峡小小三峡旅游区 | 5a | 109.90115,31.23392 | attraction | 11.48 | 14 | 类别差nature/attraction |
| 重庆 | 金佛山天星国际温泉城 | chinatravel | `ct_重庆_2642` | 107.11231,29.05161 | attraction | 金佛山-神龙峡风景区 | 5a | 107.10421,29.15250 | attraction | 11.25 | 14 | B区块 |
| 重庆 | 黑山谷风景区 | amap→chinatravel | `ct_重庆_28` | 107.00079,28.91664 | nature | 万盛黑山谷-龙鳞石海风景区 | 5a | 106.92666,28.96513 | attraction | 9.01 | 14 | B区块、类别差nature/attraction |
| 重庆 | 瞿塘峡 | amap→chinatravel | `ct_重庆_82` | 109.59460,31.05547 | nature | 白帝城·瞿塘峡景区 | 5a | 109.57287,31.04610 | attraction | 2.32 | 14 | B区块、类别差nature/attraction |
| 重庆 | 夜游两江 | chinatravel | `ct_重庆_61` | 106.59964,29.56674 | theme_park | 重庆两江游 | amap | 106.58669,29.56570 | theme_park | 1.26 | 1 | - |
| 上海 | 上海自然博物馆 | amap→chinatravel | `ct_上海_22` | 121.46266,31.23502 | museum | 上海科技馆 | museum1 | 121.54136,31.21815 | museum | 7.71 | 12 | - |
| 北京 | 水关长城 | amap→chinatravel | `ct_北京_119` | 115.97786,40.36229 | nature | 八达岭-十三陵风景名胜区 | scenic | 115.77531,40.46621 | nature | 20.68 | 5 | B区块 |
| 南京 | 江苏省五台山体育中心 | chinatravel | `ct_南京_249` | 118.78479,32.05274 | theme_park | 江苏省美术馆 | artmuseum | 118.79742,32.04421 | museum | 1.52 | 9 | 类别差theme_park/museum |
| 成都 | 成都融创文旅城 | amap→chinatravel | `ct_成都_33` | 104.06502,30.55056 | theme_park | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 61.53 | 15 | 类别差theme_park/nature |
| 成都 | 成都热雪奇迹 | amap→chinatravel | `ct_成都_42` | 103.61899,30.95175 | nature | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 7.06 | 15 | - |
| 杭州 | 桂花岛（猴岛） | chinatravel | `ct_杭州_250` | 119.15899,29.49452 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 48.00 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖钓鱼岛 | chinatravel | `ct_杭州_228` | 119.10738,29.60794 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 45.37 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖夜游 | chinatravel | `ct_杭州_97` | 119.04332,29.60749 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 39.53 | 14 | B区块、类别差nature/attraction |
| 杭州 | 月光岛（五龙岛） | chinatravel | `ct_杭州_209` | 119.02076,29.61882 | theme_park | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 38.02 | 14 | B区块、类别差theme_park/attraction |
| 杭州 | 千岛湖秀水街 | chinatravel | `ct_杭州_359` | 119.02725,29.59681 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 37.66 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖植物园 | amap→chinatravel | `ct_杭州_128` | 119.00636,29.57776 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 35.04 | 14 | B区块、类别差nature/attraction |
| 杭州 | 千岛湖龙川湾 | chinatravel | `ct_杭州_207` | 118.69219,29.46419 | nature | 淳安县千岛湖风景区 | 5a | 118.66359,29.47608 | attraction | 3.07 | 14 | B区块、类别差nature/attraction |
| 杭州 | 浙江省地质博物馆 | chinatravel | `ct_杭州_333` | 120.25964,30.18406 | museum | 浙江省博物馆 | museum1 | 120.14359,30.25114 | museum | 13.41 | 12 | - |
| 杭州 | 浙江省非物质文化遗产馆 | chinatravel | `ct_杭州_256` | 120.11541,30.16344 | museum | 浙江省博物馆 | museum1 | 120.14359,30.25114 | museum | 10.12 | 12 | - |
| 杭州 | 黄龙体育中心 | amap→chinatravel | `ct_杭州_167` | 120.12983,30.26776 | - | 浙江省博物馆 | museum1 | 120.14359,30.25114 | museum | 2.27 | 12 | - |
| 杭州 | 浙江省科技馆 | amap→chinatravel | `ct_杭州_78` | 120.13000,30.25960 | museum | 浙江省博物馆 | museum1 | 120.14359,30.25114 | museum | 1.61 | 12 | - |
| 杭州 | 芦茨湾 | chinatravel | `ct_杭州_302` | 119.68434,29.69180 | nature | 富春江-新安江风景名胜区 | scenic | 119.28508,29.47789 | nature | 45.35 | 5 | B区块 |
| 杭州 | 七里扬帆 | amap→chinatravel | `ct_杭州_104` | 119.54262,29.55254 | other | 富春江-新安江风景名胜区 | scenic | 119.28508,29.47789 | nature | 26.27 | 5 | B区块、类别差other/nature |
| 杭州 | 西天目风景区 | chinatravel | `ct_杭州_335` | 119.46030,30.33850 | nature | 东天目山景区 | amap | 119.51487,30.34421 | nature | 5.28 | 1 | B区块 |
| 武汉 | 湖北省科学技术馆 | amap→chinatravel | `ct_武汉_77` | 114.50319,30.49076 | nature | 湖北省博物馆 | museum1 | 114.36526,30.56163 | museum | 15.38 | 12 | 类别差nature/museum |
| 上饶 | 三清山神仙谷景区 | baidu | `91779a29689d4e954afc8dc9` | 118.01492,28.87904 | nature | 三清山 | unesco | 118.05724,28.94912 | nature | 8.81 | 16 | - |
| 上饶 | 三清山田园牧歌景区 | baidu | `8ee6d21abee69d5616c9056b` | 118.06558,28.94608 | nature | 玉山县三清山旅游景区 | 5a | 118.06585,28.89537 | attraction | 5.64 | 15 | B区块、类别差nature/attraction |
| 上饶 | 玉山县三清山旅游景区 | 5a | `5a_140` | 118.06585,28.89537 | attraction | 三清山 | unesco | 118.05724,28.94912 | nature | 6.04 | 1 | 类别差attraction/nature |
| 丽江 | 古城区丽江古城景区 | 5a | `5a_283` | 100.23321,26.87613 | attraction | 丽江古城 | unesco | 100.23443,26.86315 | attraction | 1.45 | 1 | - |
| 乐山 | 峨眉山风景名胜区 | scenic | `scenic_0179` | 103.48500,29.60120 | nature | 市中区乐山大佛景区 | 5a | 103.77443,29.53841 | attraction | 28.85 | 9 | B区块、类别差nature/attraction |
| 乐山 | 市中区乐山大佛景区 | 5a | `5a_258` | 103.77443,29.53841 | attraction | 峨眉山—乐山大佛 | unesco | 103.48500,29.60120 | attraction | 28.85 | 1 | - |
| 九江 | 庐山风景名胜区 | scenic | `scenic_0097` | 115.97213,29.52191 | nature | 庐山国家公园 | unesco | 115.97165,29.56399 | nature | 4.68 | 10 | B区块 |
| 佛山 | 西樵山风景名胜区 | scenic | `scenic_0162` | 112.97680,22.92454 | nature | 南海区西樵山景区 | 5a | 112.97987,22.94009 | attraction | 1.76 | 9 | B区块、类别差nature/attraction |
| 北京 | 八达岭水关长城景区 | baidu | `beabdbf4e155d19b7069d327` | 116.03212,40.34314 | nature | 八达岭-十三陵风景名胜区 | scenic | 115.77531,40.46621 | nature | 25.69 | 6 | B区块 |
| 北京 | 金海湖风景区 | baidu | `ff4933daf92894fa631c67ba` | 117.31237,40.17389 | nature | 北京金海湖碧波岛度假区 | amap | 117.26661,40.17988 | nature | 3.94 | 1 | - |
| 十堰 | 武当山风景名胜区 | scenic | `scenic_0132` | 111.08716,32.51096 | nature | 武当山古建筑群 | unesco | 111.06404,32.44275 | nature | 7.89 | 10 | - |
| 哈尔滨 | 黑龙江省哈尔滨市道外区中华巴洛克历史文化街区 | street | `st_978f98234ee1` | 126.64079,45.78183 | historic | 黑龙江省博物馆 | museum1 | 126.64094,45.75757 | museum | 2.70 | 4 | 类别差historic/museum |
| 哈尔滨 | 黑龙江省渤海上京遗址博物馆 | museum3 | `m3_560df43963da` | 126.95812,45.54642 | museum | 黑龙江省博物馆 | museum1 | 126.64094,45.75757 | museum | 34.04 | 2 | - |
| 安庆 | 天柱山风景名胜区 | scenic | `scenic_0068` | 116.46854,30.71677 | nature | 潜山县天柱山风景区 | 5a | 116.45869,30.73517 | attraction | 2.25 | 9 | B区块、类别差nature/attraction |
| 巴中 | 光雾山-诺水河风景名胜区 | scenic | `scenic_0190` | 107.18695,32.38294 | nature | 光雾山旅游景区 | 5a | 106.77507,32.67881 | attraction | 50.73 | 9 | B区块、类别差nature/attraction |
| 巴音郭楞 | 博斯腾湖风景名胜区 | scenic | `scenic_0242` | 86.35798,41.79984 | nature | 巴音郭楞蒙古自治州博湖县博斯腾湖景区 | 5a | 86.73043,41.90805 | attraction | 33.11 | 9 | B区块、类别差nature/attraction |
| 忻州 | 五台县五台山风景名胜区 | 5a | `5a_025` | 113.59119,38.96903 | attraction | 五台山 | unesco | 113.57352,39.08211 | nature | 12.67 | 1 | 类别差attraction/nature |
| 惠州 | 罗浮山风景名胜区 | scenic | `scenic_0166` | 114.06758,23.26119 | nature | 博罗县罗浮山景区 | 5a | 114.05133,23.22586 | attraction | 4.26 | 9 | B区块、类别差nature/attraction |
| 惠州 | 惠州西湖风景名胜区 | scenic | `scenic_0165` | 114.39813,23.08988 | nature | 惠州西湖旅游景区 | 5a | 114.40740,23.08485 | attraction | 1.10 | 9 | B区块、类别差nature/attraction |
| 成都 | 都江堰水利工程（都江堰景区） | ctrip | `ctrip:成都:都江堰水利工程（都江堰景区）` | 103.60911,31.00256 | nature | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 11.56 | 19 | - |
| 成都 | 青城山都江堰旅游景区 | 5a | `5a_255` | 103.60701,30.99941 | attraction | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 11.17 | 1 | 类别差attraction/nature |
| 成都 | 成都市西岭雪山景区 | baidu | `cc0849a01d3a0553950319a2` | 103.18869,30.69168 | nature | 西岭雪山大飞水风景区 | amap | 103.24139,30.70164 | nature | 5.16 | 1 | B区块 |
| 本溪 | 本溪水洞风景名胜区 | scenic | `scenic_0028` | 124.48053,41.10059 | nature | 本溪满族自治县本溪水洞景区 | 5a | 124.08089,41.30020 | attraction | 40.13 | 9 | B区块、类别差nature/attraction |
| 杭州 | 杭州西湖博物馆总馆 | museum1 | `m1_db71938f3321` | 120.13040,30.25924 | museum | 杭州西湖文化景观 | unesco | 120.14556,30.23519 | nature | 3.05 | 3 | 类别差museum/nature |
| 杭州 | 清河坊历史文化街区 | street | `st_06cdaa478e02` | 120.16855,30.25085 | historic | 杭州胡庆余堂中药博物馆 | museum2 | 120.16896,30.23983 | museum | 1.23 | 3 | 类别差historic/museum |
| 杭州 | 杭州西湖风景区 | 5a | `5a_093` | 120.12142,30.22255 | attraction | 杭州西湖文化景观 | unesco | 120.14556,30.23519 | nature | 2.71 | 1 | 类别差attraction/nature |
| 桂林 | 桂林漓江风景名胜区 | scenic | `scenic_0169` | 110.46430,25.02442 | nature | 漓江风景区 | 5a | 110.29819,25.22422 | attraction | 27.81 | 9 | B区块、类别差nature/attraction |
| 洛阳 | 洛阳隋唐大运河博物馆 | museum3 | `m3_c9ec00932d4b` | 112.45199,34.64338 | museum | 洛阳隋唐大运河文化博物馆 | museum2 | 112.49420,34.67369 | museum | 5.12 | 1 | - |
| 深圳 | 大梅沙海滨公园 | curated | `curated:深圳:大梅沙海滨公园` | 113.84557,22.58754 | attraction | 大梅沙海滩 | amap | 114.30666,22.59511 | nature | 47.34 | 2 | 类别差attraction/nature |
| 焦作 | 王屋山-云台山风景名胜区 | scenic | `scenic_0124` | 113.42766,35.42127 | nature | 云台山神农山青天河风景区 | 5a | 113.01751,35.34178 | attraction | 38.22 | 9 | B区块、类别差nature/attraction |
| 焦作 | 神农山风景名胜区 | scenic | `scenic_0128` | 112.79900,35.22025 | nature | 云台山神农山青天河风景区 | 5a | 113.01751,35.34178 | attraction | 24.00 | 9 | B区块、类别差nature/attraction |
| 玉溪 | 澄江化石地世界自然遗产博物馆（云南省自然博物馆） | museum1 | `m1_31ff0d7eb3c1` | 102.97030,24.63025 | museum | 澄江化石地 | unesco | 102.97877,24.66584 | nature | 4.05 | 3 | 类别差museum/nature |
| 舟山 | 普陀山风景名胜区 | scenic | `scenic_0047` | 122.38985,29.98620 | nature | 普陀区普陀山风景区 | 5a | 122.39468,29.97432 | attraction | 1.40 | 9 | B区块、类别差nature/attraction |
| 苏州 | 苏州市七里山塘景区 | baidu | `9ee392b8d8fbe058babd6392` | 120.60125,31.31849 | nature | 山塘街 | chinatravel | 120.61374,31.32098 | nature | 1.22 | 1 | - |
| 莆田 | 湄洲岛风景名胜区 | scenic | `scenic_0095` | 119.12900,25.06340 | nature | 湄洲岛妈祖文化旅游区 | 5a | 119.14801,25.09022 | attraction | 3.54 | 9 | 类别差nature/attraction |
| 重庆 | 两江夜游 | curated | `curated:重庆:两江夜游` | 106.57663,29.56238 | attraction | 重庆两江游 | amap | 106.58669,29.56570 | theme_park | 1.04 | 3 | 类别差attraction/theme_park |
| 长沙 | 岳麓山风景名胜区 | scenic | `scenic_0143` | 112.93627,28.18369 | nature | 岳麓山-橘子洲旅游区 | 5a | 112.96200,28.18694 | attraction | 2.55 | 9 | 类别差nature/attraction |
| 青岛 | 山东省青岛市黄岛区金沙滩啤酒城旅游休闲街区 | street | `st_e94b8c3836bc` | 120.23915,35.95233 | historic | 青岛市黄岛区博物馆 | museum3 | 120.04888,35.87162 | museum | 19.34 | 2 | 类别差historic/museum |
| 韶关 | 丹霞山风景名胜区 | scenic | `scenic_0163` | 113.72157,25.02151 | nature | 仁化县丹霞山景区 | 5a | 113.75857,25.04402 | attraction | 4.49 | 9 | B区块、类别差nature/attraction |
| 马鞍山 | 安徽省马鞍山市雨山区长江不夜城旅游休闲街区 | street | `st_0e9e082f1398` | 118.46386,31.65596 | historic | 马鞍山市博物馆 | museum2 | 118.09043,31.72131 | museum | 36.07 | 3 | 类别差historic/museum |
| 黔南 | 荔波樟江风景名胜区 | scenic | `scenic_0199` | 107.82971,25.35695 | nature | 黔南布依族苗族自治州荔波县樟江景区 | 5a | 107.79857,25.32484 | attraction | 4.75 | 9 | B区块、类别差nature/attraction |
| 中山 | 中山市博物馆 | museum2 | `m2_033618011c76` | 113.39300,22.51600 | museum | 中山市孙中山故里旅游区 | 5a | 113.52718,22.44793 | nature | 15.73 | 3 | 类别差museum/nature |
| 中山 | 广东省中山市孙文西路旅游休闲街区 | street | `st_68515f23afb9` | 113.36680,22.52185 | historic | 中山市博物馆 | museum2 | 113.39300,22.51600 | museum | 2.77 | 3 | 类别差historic/museum |
| 九江 | 九江市民俗博物馆 | museum3 | `m3_a1433799617f` | 116.03856,29.74633 | museum | 九江市博物馆 | museum1 | 115.95321,29.69099 | museum | 10.29 | 2 | - |
| 九江 | 九江市周敦颐纪念馆 | museum2 | `m2_ae39ad7e22e8` | 116.01906,29.66626 | museum | 九江市博物馆 | museum1 | 115.95321,29.69099 | museum | 6.93 | 1 | - |
| 南京 | 江苏省美术馆 | artmuseum | `a1_265af1e410df` | 118.79742,32.04421 | museum | 江苏省江海博物馆 | museum2 | 118.79662,32.05934 | museum | 1.68 | 2 | - |
| 南昌 | 江西省南昌市西湖区万寿宫旅游休闲街区 | street | `st_285831f8993e` | 115.88738,28.67421 | historic | 江西省博物馆 | museum1 | 115.88184,28.70591 | museum | 3.57 | 4 | 类别差historic/museum |
| 威海 | 威海市裕红祥丝绸文化博物馆 | museum3 | `m3_5d0bd654b481` | 122.13336,37.51512 | museum | 威海市博物馆 | museum2 | 122.49006,37.16001 | museum | 50.53 | 1 | - |
| 山南 | 西藏自治区山南市乃东区昌珠镇扎西曲登 | street | `st_ca6de5a8a8bb` | 91.77272,29.18708 | historic | 山南市博物馆 | museum3 | 91.77220,29.23700 | museum | 5.55 | 2 | 类别差historic/museum |
| 成都 | 熊猫谷 | amap | `B0K2XU9RQ0` | 103.59896,30.96554 | nature | 青城山—都江堰 | unesco | 103.56992,30.90417 | nature | 7.36 | 14 | - |
| 杭州 | 浙江省杭州市临平区运河·塘栖古镇历史风情街区 | street | `st_4f290ae24f02` | 120.18183,30.47593 | historic | 浙江省博物馆 | museum1 | 120.14359,30.25114 | museum | 25.26 | 4 | 类别差historic/museum |
| 杭州 | 浙江省杭州市拱墅区桥西历史文化街区 | street | `st_9a9267b4a989` | 120.13794,30.31731 | historic | 浙江省博物馆 | museum1 | 120.14359,30.25114 | museum | 7.38 | 4 | 类别差historic/museum |
| 杭州 | 浙江省博物馆 | museum1 | `m1_31b0c50a2c8f` | 120.14359,30.25114 | museum | 杭州西湖风景区 | 5a | 120.12142,30.22255 | attraction | 3.83 | 2 | B区块、类别差museum/attraction |
| 杭州 | 浙江省现代陶瓷艺术博物馆 | museum2 | `m2_621fda09ed54` | 120.21618,30.12636 | museum | 浙江省博物馆 | museum1 | 120.14359,30.25114 | museum | 15.53 | 1 | - |
| 武汉 | 湖北省武汉市江汉区江汉路步行街区 | street | `st_f299237ed5f6` | 114.28800,30.58361 | historic | 湖北省博物馆 | museum1 | 114.36526,30.56163 | museum | 7.79 | 4 | 类别差historic/museum |
| 武汉 | 湖北省武汉市江岸区吉庆民俗街区 | street | `st_f6166089f9ce` | 114.29276,30.58603 | historic | 湖北省博物馆 | museum1 | 114.36526,30.56163 | museum | 7.45 | 4 | 类别差historic/museum |
| 武汉 | 湖北省武汉市江岸区黎黄陂路历史文化街区 | street | `st_25e718d112d3` | 114.29943,30.58768 | historic | 湖北省博物馆 | museum1 | 114.36526,30.56163 | museum | 6.94 | 4 | 类别差historic/museum |
| 武汉 | 湖北地质博物馆 | museum3 | `m3_22f14d755179` | 114.26753,30.57923 | museum | 湖北省博物馆 | museum1 | 114.36526,30.56163 | museum | 9.56 | 2 | - |
| 江门 | 广东省江门市蓬江区启明里 | street | `st_951ee9f3f726` | 113.09489,22.58125 | historic | 江门市博物馆 | museum1 | 113.03790,22.52768 | museum | 8.35 | 4 | 类别差historic/museum |
| 济南 | 山东省泰崃天宝泰山玉石文化博物馆 | museum3 | `m3_bc4a21514503` | 117.53289,36.71012 | museum | 山东博物馆 | museum1 | 117.09573,36.65816 | museum | 39.41 | 2 | - |
| 济南 | 山东省天宇自然博物馆 | museum2 | `m2_1a9aa2c43679` | 117.12013,36.65207 | museum | 山东博物馆 | museum1 | 117.09573,36.65816 | museum | 2.28 | 1 | - |
| 湖州 | 浙江省湖州市吴兴区湖州小西街-衣裳街-状元街旅游休闲街区 | street | `st_657943a08258` | 120.09401,30.86452 | historic | 湖州市博物馆（湖州市美术馆） | museum2 | 120.06186,30.88772 | museum | 4.01 | 3 | 类别差historic/museum |
| 芜湖 | 安徽省芜湖市镜湖区芜湖古城旅游休闲街区 | street | `st_c6e30ddf3d49` | 118.38426,31.32041 | historic | 芜湖市博物馆 | museum2 | 118.43086,31.34911 | museum | 5.46 | 3 | 类别差historic/museum |
| 芜湖 | 芜湖市繁昌区博物馆 | museum3 | `m3_e99aa0ebe56f` | 118.19900,31.10160 | museum | 芜湖市博物馆 | museum2 | 118.43086,31.34911 | museum | 35.26 | 1 | - |
| 西宁 | 青海省马佳肴民族文化博物馆 | museum3 | `m3_401500b05e14` | 101.65326,36.66102 | museum | 青海省博物馆 | museum1 | 101.75612,36.63023 | museum | 9.79 | 2 | - |
| 西宁 | 青海省自然资源博物馆 | museum2 | `m2_c7d496f77918` | 101.72557,36.64818 | museum | 青海省博物馆 | museum1 | 101.75612,36.63023 | museum | 3.38 | 1 | - |
| 长沙 | 湖南省宋旦汉字艺术博物馆 | museum3 | `m3_720ac6ece824` | 112.90646,28.35341 | museum | 湖南博物院 | museum1 | 112.98862,28.19430 | museum | 19.44 | 2 | - |
| 长沙 | 湖南省茶叶博物馆 | museum2 | `m2_3c6d80f33c38` | 113.06989,28.20444 | museum | 湖南博物院 | museum1 | 112.98862,28.19430 | museum | 8.04 | 1 | - |
| 青岛 | 山东省青岛市市北区台东旅游休闲街区 | street | `st_e9de5b1afdc0` | 120.35241,36.08788 | historic | 青岛市博物馆 | museum1 | 120.47312,36.10153 | museum | 10.95 | 4 | 类别差historic/museum |
| 青岛 | 山东省青岛市大鲍岛文化旅游休闲街区 | street | `st_a2e8f91ad6f0` | 120.38300,36.06610 | historic | 青岛市博物馆 | museum1 | 120.47312,36.10153 | museum | 9.01 | 4 | 类别差historic/museum |
| 青岛 | 青岛市黄岛区博物馆 | museum3 | `m3_bbd4e60a7bc8` | 120.04888,35.87162 | museum | 青岛市博物馆 | museum1 | 120.47312,36.10153 | museum | 45.94 | 2 | - |
| 青岛 | 青岛市即墨区博物馆 | museum3 | `m3_26d5a72db658` | 120.53766,36.40269 | museum | 青岛市博物馆 | museum1 | 120.47312,36.10153 | museum | 33.98 | 2 | - |
| 青岛 | 青岛市即墨区即墨老酒博物馆 | museum3 | `m3_85212a878660` | 120.53021,36.36311 | museum | 青岛市博物馆 | museum1 | 120.47312,36.10153 | museum | 29.53 | 2 | - |
| 青岛 | 青岛市民俗博物馆 | museum2 | `m2_11e016ef2d17` | 120.32721,36.06140 | museum | 青岛市博物馆 | museum1 | 120.47312,36.10153 | museum | 13.85 | 1 | - |
| 黄山 | 黄山区博物馆 | museum3 | `m3_22982b855e73` | 118.14154,30.29640 | museum | 黄山区黄山风景区 | 5a | 118.16006,30.13953 | attraction | 17.53 | 4 | B区块、类别差museum/attraction |
| 黄山 | 黄山区黄山风景区 | 5a | `5a_114` | 118.16006,30.13953 | attraction | 黄山 | unesco | 118.17197,30.12261 | nature | 2.20 | 1 | 类别差attraction/nature |

## D. 弱配对（tier2：名称命中仅靠别名达成，须人工复核，127 对）

| 城市 | A 名（疑错针） | A source | A source_poi_id | A 坐标 | A cat | B 名（疑真实） | B source | B 坐标 | B cat | 距离km | 优先级差 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 上海 | 中国共产党第一次全国代表大会会址 | amap→chinatravel | `ct_上海_89` | 121.47528,31.22015 | memorial | 中国共产党一大·二大·四大纪念馆景区 | 5a | 121.48493,31.25499 | attraction | 3.98 | 14 | B区块、类别差memorial/attraction |
| 上海 | 宝龙美术馆 | amap→chinatravel | `ct_上海_156` | 121.35790,31.15797 | museum | 龙美术馆 | artmuseum | 121.57394,31.21597 | museum | 21.54 | 9 | - |
| 上海 | 上海话剧艺术中心 | chinatravel | `ct_上海_313` | 121.45215,31.21819 | nature | 武康路-安福路街区 | street | 121.44047,31.20876 | historic | 1.53 | 8 | B区块、类别差nature/historic |
| 上海 | 罗密欧阳台 | chinatravel | `ct_上海_354` | 121.45158,31.21386 | viewpoint | 武康路-安福路街区 | street | 121.44047,31.20876 | historic | 1.20 | 8 | B区块、类别差viewpoint/historic |
| 北京 | 长陵 | chinatravel | `ct_北京_112` | 116.26171,40.30754 | attraction | 昌平区明十三陵景区 | 5a | 116.24053,40.27913 | attraction | 3.63 | 14 | B区块 |
| 北京 | 昭陵 | chinatravel | `ct_北京_298` | 116.23063,40.29810 | attraction | 昌平区明十三陵景区 | 5a | 116.24053,40.27913 | attraction | 2.27 | 14 | B区块 |
| 北京 | 故宫钟表馆 | amap→chinatravel | `ct_北京_106` | 116.39705,39.91775 | attraction | 故宫博物院 | museum1 | 116.40966,39.92550 | museum | 1.38 | 12 | 类别差attraction/museum |
| 北京 | 角楼 | amap→chinatravel | `ct_北京_148` | 116.39705,39.91775 | historic | 故宫博物院 | museum1 | 116.40966,39.92550 | museum | 1.38 | 12 | 类别差historic/museum |
| 北京 | 神路景区 | amap→chinatravel | `ct_北京_173` | 116.24053,40.27913 | attraction | 八达岭-十三陵风景名胜区 | scenic | 115.77531,40.46621 | nature | 44.56 | 5 | B区块、类别差attraction/nature |
| 广州 | 广州市文化馆(新馆) | amap→chinatravel | `ct_广州_85` | 113.32935,23.07575 | attraction | 白云山景区 | 5a | 113.29727,23.18054 | attraction | 12.10 | 14 | B区块 |
| 广州 | 长隆飞鸟乐园 | amap→chinatravel | `ct_广州_9` | 113.28176,23.02441 | theme_park | 番禺区长隆旅游度假区 | 5a | 113.32969,23.00117 | attraction | 5.54 | 14 | 类别差theme_park/attraction |
| 广州 | 广东省凉茶博物馆 | amap→chinatravel | `ct_广州_140` | 113.44988,23.17923 | museum | 广东省博物馆 | museum1 | 113.32644,23.11475 | museum | 14.52 | 12 | - |
| 广州 | 广东省古村落小洲村 | amap→chinatravel | `ct_广州_164` | 113.35826,23.06244 | attraction | 广东省博物馆 | museum1 | 113.32644,23.11475 | museum | 6.67 | 12 | 类别差attraction/museum |
| 广州 | 白鹅潭大湾区艺术中心 | amap→chinatravel | `ct_广州_186` | 113.24183,23.10002 | gallery | 广东美术馆 | artmuseum | 113.30705,23.10868 | museum | 6.74 | 9 | 类别差gallery/museum |
| 成都 | 四川美术馆 | amap→chinatravel | `ct_成都_84` | 104.06535,30.65979 | museum | 四川省建川博物馆 | museum1 | 103.61977,30.50029 | museum | 46.20 | 12 | - |
| 成都 | 罨画池 | amap→chinatravel | `ct_成都_111` | 103.52305,30.58602 | garden | 崇州市博物馆 | museum3 | 103.67840,30.62832 | museum | 15.59 | 10 | 类别差garden/museum |
| 成都 | 成都市天府美术馆 | amap→chinatravel | `ct_成都_131` | 104.02469,30.71297 | museum | 成都市美术馆 | artmuseum | 104.05219,30.66518 | museum | 5.93 | 9 | - |
| 成都 | 国色天乡陆地乐园 | amap→chinatravel | `ct_成都_59` | 103.81884,30.71323 | theme_park | 国色天乡童话世界 | amap | 103.83128,30.72562 | theme_park | 1.82 | 1 | - |
| 武汉 | 汉阳铁厂 | chinatravel | `ct_武汉_168` | 114.25297,30.56540 | historic | 武汉博物馆 | museum1 | 114.25733,30.61185 | museum | 5.18 | 12 | 类别差historic/museum |
| 武汉 | 晴川阁夜游(大禹晴川情） | chinatravel | `ct_武汉_215` | 114.29687,30.55921 | attraction | 武汉市晴川阁管理处（武汉大禹文化博物馆） | museum2 | 114.28445,30.55526 | museum | 1.27 | 11 | 类别差attraction/museum |
| 深圳 | 大侠谷瀑布 | chinatravel | `ct_深圳_280` | 114.29905,22.62956 | nature | 南山区华侨城旅游度假区 | 5a | 113.98410,22.53510 | attraction | 34.00 | 14 | 类别差nature/attraction |
| 深圳 | 东部华侨城 | amap→chinatravel | `ct_深圳_5` | 114.29915,22.59962 | theme_park | 南山区华侨城旅游度假区 | 5a | 113.98410,22.53510 | attraction | 33.14 | 14 | 类别差theme_park/attraction |
| 深圳 | OCAT(深圳馆) | chinatravel | `ct_深圳_241` | 114.00525,22.54041 | museum | 南山区华侨城旅游度假区 | 5a | 113.98410,22.53510 | attraction | 2.25 | 14 | 类别差museum/attraction |
| 深圳 | 龙岗区科技馆 | amap→chinatravel | `ct_深圳_144` | 114.24745,22.71863 | museum | 深圳市龙岗区客家民俗博物馆 | museum3 | 114.26453,22.72771 | museum | 2.02 | 10 | - |
| 三明 | 泰宁县博物馆 | museum3 | `m3_b2e3e1417968` | 117.17763,26.89868 | museum | 泰宁县泰宁风景旅游区 | 5a | 117.12498,26.90749 | attraction | 5.31 | 4 | 类别差museum/attraction |
| 上海 | 东方明珠广播电视塔 | baidu | `b643224025414952f4e73b2f` | 121.49917,31.23967 | attraction | 351米太空舱 | chinatravel | 121.51098,31.24318 | theme_park | 1.19 | 1 | 类别差attraction/theme_park |
| 上饶 | 江西省上饶市广信区望仙谷岩铺老街旅游休闲街区 | street | `st_4b15f64c17d6` | 117.81594,28.67934 | historic | 上饶市博物馆 | museum1 | 117.94746,28.44993 | museum | 28.56 | 4 | 类别差historic/museum |
| 上饶 | 江西省上饶市信州区金龙岗青年艺术街区 | street | `st_772eb85fd656` | 117.97454,28.44527 | historic | 上饶市博物馆 | museum1 | 117.94746,28.44993 | museum | 2.70 | 4 | 类别差historic/museum |
| 东莞 | 东莞市石龙镇博物馆 | museum3 | `m3_28489d0ac778` | 113.85757,23.10675 | museum | 东莞市博物馆 | museum2 | 113.75611,23.04042 | museum | 12.73 | 1 | - |
| 东莞 | 东莞市袁崇焕纪念园 | museum3 | `m3_fbfc8e113c96` | 113.83624,23.10377 | museum | 东莞市博物馆 | museum2 | 113.75611,23.04042 | museum | 10.81 | 1 | - |
| 东莞 | 东莞市钱币博物馆 | museum3 | `m3_995a99dc3ff5` | 113.76163,23.00969 | museum | 东莞市博物馆 | museum2 | 113.75611,23.04042 | museum | 3.46 | 1 | - |
| 临沂 | 山东省临沂市兰山区灯火兰山·新琅琊旅游休闲街区 | street | `st_97fa77379bdd` | 118.34868,35.07665 | historic | 临沂市博物馆 | museum1 | 118.35645,35.08968 | museum | 1.61 | 4 | 类别差historic/museum |
| 保定 | 河北省保定市莲池区西大街 | street | `st_59fa23fd352f` | 115.49106,38.95693 | historic | 保定市博物馆 | museum2 | 115.16598,38.86904 | museum | 29.78 | 3 | 类别差historic/museum |
| 兰州 | 甘肃省兰州市西固区河口古镇旅游休闲街区 | street | `st_3a10e62e4da1` | 103.43976,36.17130 | historic | 兰州市博物馆 | museum1 | 103.83415,36.05525 | museum | 37.70 | 4 | 类别差historic/museum |
| 兰州 | 兰州市地震博物馆 | museum3 | `m3_41fcb1a4dea1` | 103.90166,36.04769 | museum | 兰州市博物馆 | museum1 | 103.83415,36.05525 | museum | 6.13 | 2 | - |
| 包头 | 内蒙古自治区包头市东河区乔家金街旅游休闲街区 | street | `st_9484527c7cf7` | 110.02435,40.59760 | historic | 包头市博物馆（包头市文物保护中心） | museum1 | 109.84108,40.67259 | museum | 17.57 | 4 | 类别差historic/museum |
| 北京 | 北京十渡风景区 | baidu | `64ff3be1653dd1bb90114cc4` | 115.59704,39.63909 | nature | 十渡风景名胜区 | chinatravel | 115.61250,39.64514 | nature | 1.48 | 1 | B区块 |
| 南京 | 侵华日军南京大屠杀遇难同胞纪念馆 | tripadvisor | `tripadvisor:南京:侵华日军南京大屠杀遇难同胞纪念馆` | 118.74181,32.03555 | attraction | 南京利济巷慰安所旧址陈列馆 | amap | 118.79759,32.03915 | museum | 5.27 | 5 | 类别差attraction/museum |
| 台州 | 浙江省台州市临海市紫阳街 | street | `st_fc1e6b5e70ae` | 121.11661,28.84266 | historic | 台州市博物馆 | museum2 | 121.41638,28.66023 | museum | 35.57 | 3 | 类别差historic/museum |
| 合肥 | 安徽省体育博物馆 | museum3 | `m3_b5afedcc6b06` | 117.29728,31.85592 | museum | 安徽博物院 | museum1 | 117.22026,31.80211 | museum | 9.42 | 2 | - |
| 吉林 | 吉林市明清造船厂遗址博物馆 | museum3 | `m3_c001c032a20e` | 126.67075,43.76832 | museum | 吉林市博物馆（吉林市陨石博物馆） | museum1 | 126.56142,43.82894 | museum | 11.06 | 2 | - |
| 吉林 | 吉林市文庙博物馆 | museum3 | `m3_9d01122a4178` | 126.57034,43.84089 | museum | 吉林市博物馆（吉林市陨石博物馆） | museum1 | 126.56142,43.82894 | museum | 1.51 | 2 | - |
| 吉林 | 吉林市满族博物馆 | museum2 | `m2_1868b2dc87e6` | 126.53764,43.84108 | museum | 吉林市博物馆（吉林市陨石博物馆） | museum1 | 126.56142,43.82894 | museum | 2.34 | 1 | - |
| 吐鲁番 | 吐鲁番市文博院 | museum1 | `m1_3dc7f9523b32` | 89.25026,42.97274 | museum | 高昌区葡萄沟风景区 | 5a | 89.24480,43.00863 | attraction | 4.02 | 2 | B区块、类别差museum/attraction |
| 吴忠 | 宁夏回族自治区吴忠市利通区光耀旅游休闲街区 | street | `st_4592817f51be` | 106.21300,37.98450 | historic | 吴忠市博物馆 | museum3 | 106.19900,37.99740 | museum | 1.89 | 2 | 类别差historic/museum |
| 太原 | 晋祠 | reservation | `resv_太原_晋祠` | 112.44278,37.69879 | attraction | 太原市晋祠博物馆 | museum1 | 112.44148,37.70861 | museum | 1.10 | 15 | 类别差attraction/museum |
| 太原 | 山西省太原市晋源区太原古县城十字街 | street | `st_05cc91df7018` | 112.48591,37.72763 | historic | 太原市博物馆 | museum1 | 112.55000,37.87070 | museum | 16.88 | 4 | 类别差historic/museum |
| 太原 | 山西省太原市迎泽区钟楼步行街 | street | `st_4e611f9e2977` | 112.56300,37.86320 | historic | 太原市博物馆 | museum1 | 112.55000,37.87070 | museum | 1.41 | 4 | 类别差historic/museum |
| 宜宾 | 四川省宜宾市翠屏区僰道历史文化旅游休闲街区 | street | `st_c753f522f956` | 104.62654,28.77009 | historic | 宜宾市博物院 | museum1 | 104.68118,28.79589 | museum | 6.05 | 4 | 类别差historic/museum |
| 宜春 | 高安市吴有训科教馆 | museum3 | `m3_4af7fbc3386a` | 115.35585,28.41650 | museum | 高安市博物馆（高安元青花博物馆） | museum2 | 115.38957,28.44100 | museum | 4.28 | 1 | - |
| 宝鸡 | 扶风县博物馆 | museum3 | `m3_824580406e4c` | 107.88031,34.35750 | museum | 法门文化景区 | 5a | 107.90226,34.43353 | attraction | 8.69 | 4 | B区块、类别差museum/attraction |
| 宣城 | 绩溪县博物馆（绩溪县三雕博物馆） | museum3 | `m3_2c68e35b41ec` | 118.59359,30.07001 | museum | 绩溪县龙川景区 | 5a | 118.66972,30.07563 | attraction | 7.35 | 4 | B区块、类别差museum/attraction |
| 广州 | 广东美术馆 | artmuseum | `a1_11100db9de99` | 113.30705,23.10868 | museum | 广东省博物馆 | museum1 | 113.32644,23.11475 | museum | 2.09 | 3 | - |
| 广州 | 广州市九龙湖度假区 | baidu | `f52a91b23ca74c858505bfca` | 113.41673,23.47885 | nature | 广州市文化馆(新馆) | amap | 113.32935,23.07575 | attraction | 45.70 | 1 | 类别差nature/attraction |
| 广州 | 广州市中山纪念堂 | baidu | `323b7bfa27cd1ad816a19044` | 113.26475,23.13286 | nature | 广州市文化馆(新馆) | amap | 113.32935,23.07575 | attraction | 9.16 | 1 | 类别差nature/attraction |
| 庆阳 | 庆阳市西峰区博物馆 | museum3 | `m3_bcd580108269` | 107.67340,35.66727 | museum | 庆阳市博物馆 | museum2 | 107.64417,35.70589 | museum | 5.04 | 1 | - |
| 开封 | 河南省开封市龙亭区七盛角旅游休闲街区 | street | `st_36320d63e2a9` | 114.34418,34.80635 | historic | 开封市博物馆 | museum1 | 114.34110,34.78929 | museum | 1.92 | 4 | 类别差historic/museum |
| 开封 | 河南省开封市鼓楼区鼓楼特色文化旅游休闲街区 | street | `st_2d79ac86751d` | 114.35598,34.79387 | historic | 开封市博物馆 | museum1 | 114.34110,34.78929 | museum | 1.45 | 4 | 类别差historic/museum |
| 德州 | 德州市苏禄王墓博物馆 | museum2 | `m2_10df6b71c358` | 116.29562,37.47160 | museum | 德州市博物馆 | museum1 | 116.35661,37.44217 | museum | 6.30 | 1 | - |
| 怀化 | 湖南省怀化市洪江市黔阳古城旅游休闲街区 | street | `st_9eba756b54b9` | 109.81734,27.19090 | historic | 怀化市博物馆 | museum2 | 109.96682,27.52721 | museum | 40.20 | 3 | 类别差historic/museum |
| 惠州 | 博罗县博物馆 | museum3 | `m3_3546fc305320` | 114.28742,23.18487 | museum | 博罗县罗浮山景区 | 5a | 114.05133,23.22586 | attraction | 24.56 | 4 | B区块、类别差museum/attraction |
| 惠州 | 广东省惠州市惠城区水东街 | street | `st_b6d65196f44d` | 114.41272,23.09040 | historic | 惠州市博物馆 | museum2 | 114.41559,23.11237 | museum | 2.46 | 3 | 类别差historic/museum |
| 惠州 | 广东省惠州市惠城区祝屋巷 | street | `st_7a798c549f10` | 114.39828,23.10074 | historic | 惠州市博物馆 | museum2 | 114.41559,23.11237 | museum | 2.19 | 3 | 类别差historic/museum |
| 成都 | 成都市宝光桂湖文化旅游区 | baidu | `792cb3f460f485f2b220a8b6` | 104.16132,30.82635 | nature | 成都市美术馆 | artmuseum | 104.05219,30.66518 | museum | 20.74 | 10 | 类别差nature/museum |
| 成都 | 人民公园 | baidu | `007629aa30f7456cbd48424b` | 104.05768,30.65710 | attraction | 成都市美术馆 | artmuseum | 104.05219,30.66518 | museum | 1.04 | 10 | 类别差attraction/museum |
| 成都 | 四川省成都市成华区望平坊旅游休闲街区 | street | `st_b83ef3c45f43` | 104.08995,30.65366 | historic | 成都市美术馆 | artmuseum | 104.05219,30.66518 | museum | 3.83 | 1 | 类别差historic/museum |
| 扬州 | 高邮市文游台景区 | baidu | `ab03b739d6735aeb97ec849c` | 119.44754,32.79467 | nature | 高邮市博物馆 | museum3 | 119.45892,32.78161 | museum | 1.80 | 11 | 类别差nature/museum |
| 扬州 | 江苏省扬州市高邮市运河·盂城驿街区 | street | `st_e0cef88fda45` | 119.43915,32.77098 | historic | 高邮市博物馆 | museum3 | 119.45892,32.78161 | museum | 2.19 | 2 | 类别差historic/museum |
| 无锡 | 无锡市鸿山遗址博物馆 | museum2 | `m2_aae08e0b04c3` | 120.50841,31.49249 | museum | 无锡博物院 | museum1 | 120.30612,31.54992 | museum | 20.21 | 1 | - |
| 昆明 | 云南省中医药民族医药博物馆 | museum3 | `m3_00b2143c084e` | 102.82418,24.83792 | museum | 云南省博物馆 | museum1 | 102.75367,24.94958 | museum | 14.31 | 2 | - |
| 昆明 | 昆明市官渡区博物馆 | museum3 | `m3_dcf0f5783e82` | 102.75054,25.00894 | museum | 昆明市博物馆 | museum1 | 102.72842,25.03240 | museum | 3.43 | 2 | - |
| 晋中 | 平遥县博物馆 | museum3 | `m3_6d1ab15a80c0` | 112.17583,37.18961 | museum | 平遥县平遥古城景区 | 5a | 112.18354,37.20416 | attraction | 1.76 | 4 | B区块、类别差museum/attraction |
| 晋中 | 山西省晋中市平遥县又见平遥文化产业园区印象新街 | street | `st_9b6cabb2b6ea` | 111.99686,37.23603 | historic | 平遥县博物馆 | museum3 | 112.17583,37.18961 | museum | 16.67 | 2 | 类别差historic/museum |
| 杭州 | 良渚博物院 | museum1 | `m1_3563d776723d` | 120.02840,30.37804 | museum | 良渚古城遗址 | unesco | 119.98993,30.39418 | attraction | 4.10 | 3 | 类别差museum/attraction |
| 柳州 | 柳州市立鱼峰风景区 | baidu | `58f0f0834317fbbd97ec84d4` | 109.41298,24.30077 | nature | 柳州市博物馆 | museum2 | 109.41267,24.31897 | museum | 2.02 | 12 | 类别差nature/museum |
| 柳州 | 柳州博物馆 | baidu | `5b642b6028a36498095cb3cf` | 109.41267,24.31897 | museum | 广西壮族自治区柳州市鱼峰区窑埠古镇街区 | street | 109.42765,24.31568 | historic | 1.56 | 9 | B区块、类别差museum/historic |
| 柳州 | 广西壮族自治区柳州市鱼峰区窑埠古镇街区 | street | `st_67a7979f100d` | 109.42765,24.31568 | historic | 柳州市博物馆 | museum2 | 109.41267,24.31897 | museum | 1.56 | 3 | 类别差historic/museum |
| 武威 | 武威市西夏博物馆 | museum3 | `m3_45fde8e3769c` | 102.64429,37.92339 | museum | 武威市博物馆 | museum1 | 102.62290,37.94206 | museum | 2.80 | 2 | - |
| 武威 | 武威市五凉文化博物馆 | museum3 | `m3_66298eebcf2a` | 102.63628,37.92332 | museum | 武威市博物馆 | museum1 | 102.62290,37.94206 | museum | 2.39 | 2 | - |
| 武威 | 武威市雷台汉文化博物馆 | museum3 | `m3_62f867deb354` | 102.63820,37.94188 | museum | 武威市博物馆 | museum1 | 102.62290,37.94206 | museum | 1.34 | 2 | - |
| 武汉 | 湖北省武汉市武昌区昙华林历史文化街区 | street | `st_4366822dd6f7` | 114.31128,30.55171 | historic | 武汉博物馆 | museum1 | 114.25733,30.61185 | museum | 8.45 | 4 | 类别差historic/museum |
| 武汉 | 武汉市晴川阁管理处（武汉大禹文化博物馆） | museum2 | `m2_e864319af306` | 114.28445,30.55526 | museum | 武汉博物馆 | museum1 | 114.25733,30.61185 | museum | 6.81 | 1 | - |
| 永州 | 湖南省永州市零陵区柳子街 | street | `st_270f77bf4777` | 111.60300,26.21834 | historic | 永州市博物馆 | museum3 | 111.63237,26.21784 | museum | 2.93 | 2 | 类别差historic/museum |
| 汕头 | 汕头市革命历史博物馆 | museum3 | `m3_d400c37182ed` | 116.69042,23.35577 | museum | 汕头市博物馆 | museum2 | 116.77513,23.45923 | museum | 14.39 | 1 | - |
| 沈阳 | 辽宁省沈阳市铁西区红梅文创园旅游休闲街区 | street | `st_b7bf9caae329` | 123.35041,41.81117 | historic | 辽宁省博物馆 | museum1 | 123.46050,41.67805 | museum | 17.39 | 4 | 类别差historic/museum |
| 沈阳 | 辽宁省沈阳市和平区沈阳老北市旅游休闲街区 | street | `st_996e3d1bcda4` | 123.42675,41.80737 | historic | 辽宁省博物馆 | museum1 | 123.46050,41.67805 | museum | 14.65 | 4 | 类别差historic/museum |
| 泉州 | 福建省泉州市鲤城区泉州中山路旅游休闲街区 | street | `st_0c888c239edd` | 118.59208,24.91490 | historic | 泉州市博物馆 | museum2 | 118.89720,24.91621 | museum | 30.77 | 3 | 类别差historic/museum |
| 泰州 | 泰州市口岸雕花楼景区 | baidu | `597f9c15e3f5ebe0611c676b` | 119.87779,32.30311 | nature | 泰州市博物馆 | museum2 | 119.92373,32.44704 | museum | 16.58 | 12 | 类别差nature/museum |
| 泰州 | 泰州市姜堰区博物馆 | museum3 | `m3_432f2daf3720` | 120.14838,32.52584 | museum | 泰州市博物馆 | museum2 | 119.92373,32.44704 | museum | 22.82 | 1 | - |
| 济南 | 山东省济南市槐荫区印象济南·泉世界文化旅游休闲街区 | street | `st_2cda7301cb7d` | 116.90881,36.67756 | historic | 济南市博物馆 | museum1 | 117.12014,36.65205 | museum | 19.06 | 4 | 类别差historic/museum |
| 济南 | 济南市长清区博物馆 | museum3 | `m3_1a22b0d354df` | 116.76039,36.55336 | museum | 济南市博物馆 | museum1 | 117.12014,36.65205 | museum | 33.94 | 2 | - |
| 济南 | 济南市章丘区城子崖遗址博物馆 | museum3 | `m3_06c98dd0cdcc` | 117.36259,36.73538 | museum | 济南市博物馆 | museum1 | 117.12014,36.65205 | museum | 23.52 | 2 | - |
| 淄博 | 淄博市淄川区寅瑄乡愁博物馆 | museum3 | `m3_d6365dc5b962` | 117.99449,36.65736 | museum | 淄博市博物馆 | museum1 | 118.03895,36.80372 | museum | 16.75 | 2 | - |
| 淄博 | 淄博市在堂鱼盘艺术博物馆 | museum3 | `m3_112dc4e01825` | 118.05500,36.81300 | museum | 淄博市博物馆 | museum1 | 118.03895,36.80372 | museum | 1.76 | 2 | - |
| 淄博 | 淄博市起凤田氏骨科博物馆 | museum2 | `m2_9cf3578fea82` | 118.10700,37.06436 | museum | 淄博市博物馆 | museum1 | 118.03895,36.80372 | museum | 29.61 | 1 | - |
| 淄博 | 淄博市源一刻瓷艺术博物馆 | museum2 | `m2_d7ee6128770f` | 117.99169,36.64457 | museum | 淄博市博物馆 | museum1 | 118.03895,36.80372 | museum | 18.19 | 1 | - |
| 淮北 | 安徽省淮北市相山区隋唐运河古镇旅游休闲街区 | street | `st_bb8a0205c9f6` | 116.80952,33.93785 | historic | 淮北市博物馆 | museum1 | 116.79800,33.95580 | museum | 2.26 | 4 | 类别差historic/museum |
| 淮北 | 淮北市刘开渠纪念馆 | museum3 | `m3_13dd641c6682` | 116.79625,33.98162 | museum | 淮北市博物馆 | museum1 | 116.79800,33.95580 | museum | 2.88 | 2 | - |
| 淮安 | 淮安市博物馆 | museum1 | `m1_8b36c429a142` | 119.11320,33.55095 | museum | 淮安市周恩来故里景区 | 5a | 119.15269,33.51261 | nature | 5.62 | 2 | B区块、类别差museum/nature |
| 淮安 | 淮安市楚州博物馆 | museum3 | `m3_ccae9726ae99` | 119.14183,33.50713 | museum | 淮安市博物馆 | museum1 | 119.11320,33.55095 | museum | 5.55 | 2 | - |
| 溧阳 | 溧阳市博物馆 | museum2 | `m2_1cb9885e76f3` | 119.48500,31.41620 | museum | 天目湖景区 | 5a | 119.42696,31.29985 | attraction | 14.06 | 3 | B区块、类别差museum/attraction |
| 潍坊 | 潍坊市潍城区神农茶文化博物馆 | museum3 | `m3_f979089bd081` | 119.09934,36.67265 | museum | 潍坊市博物馆 | museum1 | 119.15906,36.71191 | museum | 6.89 | 2 | - |
| 潍坊 | 潍坊市潍城区五道庙博物馆 | museum3 | `m3_49a9a0cb8c20` | 119.09665,36.70456 | museum | 潍坊市博物馆 | museum1 | 119.15906,36.71191 | museum | 5.62 | 2 | - |
| 烟台 | 山东省烟台市芝罘区朝阳街 | street | `st_57c64008be86` | 121.40179,37.54306 | historic | 烟台市博物馆 | museum1 | 121.44800,37.46370 | museum | 9.72 | 4 | 类别差historic/museum |
| 焦作 | 河南省焦作市修武县岸上旅游休闲街区 | street | `st_bf9a1ebd7e32` | 113.38028,35.41915 | historic | 焦作市博物馆 | museum2 | 113.25035,35.23718 | museum | 23.42 | 3 | 类别差historic/museum |
| 盐城 | 盐城市丹顶鹤湿地生态旅游区 | baidu | `a8df35abffc25f30c07da269` | 120.51658,33.60630 | nature | 盐城中国海盐博物馆（盐城市博物馆） | museum1 | 120.16100,33.34930 | museum | 43.64 | 13 | 类别差nature/museum |
| 盐城 | 盐城市盐都区博物馆 | museum3 | `m3_17916b5a3fc2` | 120.16334,33.33787 | museum | 盐城中国海盐博物馆（盐城市博物馆） | museum1 | 120.16100,33.34930 | museum | 1.29 | 2 | - |
| 福州 | 福州市鼓楼区博物馆 | museum3 | `m3_705399d9d6ec` | 119.30400,26.08200 | museum | 福州市博物馆 | museum2 | 119.56370,26.48687 | museum | 51.93 | 1 | - |
| 绵阳 | 绵阳市安州区博物馆 | museum3 | `m3_b2d8955fe216` | 104.56545,31.53101 | museum | 绵阳市博物馆 | museum2 | 104.77759,31.47556 | museum | 21.04 | 1 | - |
| 茂名 | 茂名市电白区博物馆 | museum3 | `m3_48519a8074a6` | 111.01122,21.50588 | museum | 茂名市博物馆 | museum2 | 110.92500,21.66330 | museum | 19.64 | 1 | - |
| 荆门 | 钟祥市博物馆 | museum3 | `m3_8b3f1b64fd43` | 112.61881,31.18290 | museum | 明显陵文化旅游景区 | 5a | 112.63689,31.20631 | attraction | 3.12 | 4 | B区块、类别差museum/attraction |
| 莆田 | 福建省莆田市荔城区兴化府历史文化街区 | street | `st_679e6d74787a` | 119.01630,25.43335 | historic | 莆田市博物馆 | museum2 | 119.01724,25.45807 | museum | 2.75 | 3 | 类别差historic/museum |
| 衢州 | 浙江省衢州市柯城区水亭门历史文化街区 | street | `st_3a0b80629834` | 118.86701,28.96211 | historic | 衢州市博物馆 | museum2 | 118.85931,28.97023 | museum | 1.17 | 3 | 类别差historic/museum |
| 西宁 | 西宁市湟中区博物馆 | museum2 | `m2_52eda137b374` | 101.57200,36.50090 | museum | 湟中县塔尔寺景区 | 5a | 101.56777,36.48760 | attraction | 1.53 | 3 | B区块、类别差museum/attraction |
| 西安 | 陕西省西安市曲江新区大唐不夜城步行街 | street | `st_91c943877936` | 108.96405,34.20883 | historic | 陕西历史博物馆 | museum1 | 108.95508,34.22420 | museum | 1.90 | 4 | 类别差historic/museum |
| 西安 | 陕西省美术博物馆 | artmuseum | `a1_28cc8b61a237` | 108.94421,34.23099 | museum | 陕西历史博物馆 | museum1 | 108.95508,34.22420 | museum | 1.25 | 3 | - |
| 贵阳 | 贵州省贵阳市花溪区青岩古镇南北明清街旅游休闲街区 | street | `st_803a4d6e3eb6` | 106.68670,26.33116 | historic | 贵州省博物馆 | museum1 | 106.64247,26.64761 | museum | 35.46 | 4 | 类别差historic/museum |
| 贵阳 | 贵州省贵阳市南明区青云路步行街 | street | `st_c7bf2bd31e50` | 106.70845,26.56576 | historic | 贵州省博物馆 | museum1 | 106.64247,26.64761 | museum | 11.22 | 4 | 类别差historic/museum |
| 郑州 | 河南省郑州市金水区郑州记忆1952油化厂旅游休闲街区 | street | `st_d9c920cab325` | 113.64020,34.77232 | historic | 郑州博物馆 | museum1 | 113.54683,34.73961 | museum | 9.27 | 4 | 类别差historic/museum |
| 郑州 | 郑州市天中艺术博物馆 | museum3 | `m3_f52104f7b39a` | 113.69837,34.81601 | museum | 郑州博物馆 | museum1 | 113.54683,34.73961 | museum | 16.24 | 2 | - |
| 郑州 | 郑州市大河村遗址博物馆 | museum2 | `m2_4dc1d3b824cf` | 113.69455,34.83750 | museum | 郑州博物馆 | museum1 | 113.54683,34.73961 | museum | 17.33 | 1 | - |
| 郴州 | 湖南省郴州市苏仙区裕后街 | street | `st_bae5e72f7ae9` | 113.03988,25.78631 | historic | 郴州市博物馆 | museum2 | 113.01500,25.77060 | museum | 3.04 | 3 | 类别差historic/museum |
| 长沙 | 湖南省长沙市开福区潮宗街 | street | `st_afa7832371b3` | 112.97333,28.20315 | historic | 长沙市博物馆 | museum1 | 112.98070,28.24192 | museum | 4.37 | 4 | 类别差historic/museum |
| 阿坝 | 汶川县博物馆 | museum3 | `m3_abe64bdeeea1` | 103.58123,31.47195 | museum | 阿坝藏族羌族自治州汶川县汶川特别旅游区 | 5a | 103.46176,30.97678 | attraction | 56.22 | 4 | 类别差museum/attraction |
| 阿拉善盟 | 额济纳博物馆（额济纳旗文物保护中心） | museum3 | `m3_e04e05bcdfd2` | 101.05858,41.95114 | museum | 阿拉善盟胡杨林旅游区 | 5a | 101.20501,41.98011 | attraction | 12.53 | 4 | 类别差museum/attraction |
| 韶关 | 韶关市曲江区博物馆 | museum3 | `m3_8e20630dd4e1` | 113.60500,24.68250 | museum | 韶关市博物馆 | museum2 | 113.55202,24.79997 | museum | 14.12 | 1 | - |
| 黄冈 | 黄冈市黄州区博物馆 | museum3 | `m3_25d1d93a4fb0` | 114.88000,30.43440 | museum | 黄冈市博物馆 | museum2 | 114.91039,30.46860 | museum | 4.79 | 1 | - |

## 假阳性剔除与自查记录（任务第5条，一轮自查后口径收紧）

- 分店/门店（`店)` 括注、分店/旗舰店/一店…）：连锁多门店合法分布，跳过。
- 子设施词（入口/停车场/码头/索道/售票/游客中心/观景台/东西南北门/公交地铁站等）：同实体附属点位天然离主点 >1km，跳过。
- 零售词（便利店/超市/咖啡/影城/书店/银行等）与酒店词行（含公馆/山庄/度假村误标行）：不属观光点池，跳过。
- 一/二轮自查发现并已收口的误配形态（单测复核 debug 见 ops/debug 脚本，已删）：
  1. 别名整含他馆本名——宝龙美术馆 别名「上海宝龙美术馆」整含 龙美术馆 本名、故宫钟表馆 别名「故宫博物院钟表馆」整含 故宫博物院 本名、上海自然博物馆 别名「上海科技馆分馆/自然分馆」整含 上海科技馆；修法：长核仅出自别名且（余差≤2字或短核=短核侧本名全串）→ 降弱档 §D（事故形态长核 成都武侯祠 出自 B 本名剥尾，不受影响）。
  2. 纯馆类通名裸核——上海科技馆 别名「科技馆」配到 上海隧道科技馆；修法：裸通名核（科技馆/博物馆/美术馆…无正名前缀）不参与匹配。
  3. 双别名缩写命中——中共一大纪念馆 别名剥出「中共一大」× 中共一大会址纪念馆别名「中共一大会址纪念馆」；修法：双侧参与核均仅出自别名 → 降弱档 §D。
  4. 过剥尾残核——上海大观园 剥出「上海大」配 上海大学博物馆；修法：参与互含的短核剥尾深度须 ≤1。
  5. 通用地理别名——「大运河」配 5A 景区等，命中核含山/湖/岛/河等地理词归 §C。
  6. 1 字差嵌入（龙美术馆 ⊂ 宝龙美术馆 本名层）由互含长短差 ≥2 字闸拦下；2 字残核（人民公园/人民广场 剥出「人民」）一律不认；命中核按排序取保证确定性。
- B 为区块/面实体（名含景区/古镇/街区/镇/遗址公园或类别 ancient_town/citywalk）：子点位离中心 1-5km 属合法几何，备注列打「B区块」提示缓判。
- 跨城同名：已在同城过滤内天然排除。
- 局限：同为低优源的同名重复行（如两条 chinatravel 同名）不在本次口径内；未识别 source 行只作 B 不作 A；城市内街区型点位（武康路 vs 武康路-安福路街区）与面实体子点（明十三陵陵寝 vs 景区中心）属于「坐标都对但相距 >1km」的合法形态，靠备注列人工缓判。

## 修复与回滚思路（本次未执行）

1. 逐对人工确认（看 address 字段：事故形态 A 地址会落在错误街道，如锦悦西路）。
2. 确认错针后两条路（任选，逐行执行前先 dump A/B 全字段）：
   - 针拷贝：`UPDATE pois SET location=B.location, wgs84_location=B.wgs84_location, address=B.address, updated_at=NOW() WHERE id=A.id` —— 保留 A 行其余字段；
   - 软删让位：`UPDATE pois SET status='inactive', updated_at=NOW() WHERE id=A.id` —— 引擎读池自动改用 B（既有口径：退役先查同城 active 同实体）。
3. 回滚：修复前 `CREATE TABLE pois_wrongpin_bak_20261107 AS SELECT * FROM pois WHERE id IN (…A ids…)`，回滚即 `UPDATE pois SET (location, wgs84_location, address, status) = (SELECT … FROM bak) WHERE id=…` 或 `status='active'`。
4. 若批量处置，建议像 parks 清洗一样单开 exec 脚本 + md 记录处置行与回滚语句。
