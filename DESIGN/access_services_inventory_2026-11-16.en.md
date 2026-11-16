# Remote scenic-area transport — poi_access_services inventory (2026-11-16)

Provenance is split by fact:

* `official_status` — `verified` (official page checked) / `pending` (not yet
  checked) / `no_official_page` (attraction has no official site);
* `window_source` — where the first/last departure times come from
  (`official` / `baidu` / `amap`); note that Chinese scenic-area official sites
  normally publish **routes and ticket prices only**, not timetables;
* `fare_source` — where the fare comes from.

Nothing is invented: rows whose timetable is map-vendor measured are marked
`window_source=baidu`, never claimed as official.

| City | Attraction | English name | Mode | Boarding | First | Last | Ride (min) | official_status | window | fare | URL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 上海 | 上海影视乐园 | Shanghai Film and TV Park | train | 人民广场站(3口) | 05:20 | 21:57 | 58 | pending | baidu |  |  |
| 上海 | 上海梵高星空艺术馆 | Shanghai Van Gogh Starry Sky Art Museum | shuttle | 人民广场站(3口) | 06:00 | 22:30 | 57 | pending | baidu |  |  |
| 上海 | 东林寺 | Donglin Temple | bus | 人民广场站 | 08:30 | 08:30 | 58 | pending | baidu |  |  |
| 上海 | 州桥老街 | Zhouqiao Old Street | shuttle | 成都北路南京西路站 | 08:40 | 08:40 | 61 | pending | baidu |  |  |
| 上海 | 张堰镇 | Zhangyan Town | shuttle | 人民广场站(3口) | 06:00 | 23:45 | 195 | pending | baidu |  |  |
| 上海 | 村口大树 | The Big Tree at the Village Entrance | bus | 人民广场站(3口) | 09:05 | 09:05 | 100 | pending | baidu |  |  |
| 上海 | 金山城市沙滩 | Jinshan City Beach | train | 人民广场站(3口) | 05:20 | 21:57 | 107 | pending | baidu |  |  |
| 上海 | 飞越上海(第一百货店) | Flying Over Shanghai (First Department Store) | shuttle | 人民广场站(3口) | 06:00 | 22:30 | 57 | pending | baidu |  |  |
| 北京 | 九谷口自然风景区 | Jiugukou Natural Scenic Area | shuttle | 王府井站(C4西南口) | 09:10 | 09:10 | 165 | no_official_page | baidu |  |  |
| 北京 | 八奇洞景区 | Baqi Cave Scenic Area | shuttle | 东城三里河站 | 09:00 | 09:00 | 61 | verified | baidu | official | https://s.visitbeijing.com.cn/attraction/118181 |
| 北京 | 八达岭长城 | Badaling Great Wall | shuttle | 前门站 | 06:30 | 11:00 | 91 | pending | baidu |  |  |
| 北京 | 八达岭长城 | Badaling Great Wall | shuttle | Deshengmen (877) / Huangtudian (S2) / Qi |  |  |  | verified | official |  | https://www.beijing.gov.cn/renwen/sy/whkb/201906/t201906 |
| 北京 | 北京二锅头酒博物馆 | Beijing Erguotou Wine Museum | shuttle | 王府井站(C4西南口) | 09:10 | 09:10 | 73 | verified | baidu | official | https://www.redstarwine.cn/fwzx/cgfw/cindex1.html |
| 北京 | 北京黄花城水长城漫心府 | Beijing Huanghuacheng Waterside Great Wall Manxin Mansion | bus | 王府井站(C4西南口) | 07:00 | 16:00 | 146 | verified | baidu | official | https://huanghuacheng.com/index.php/Ticket/publicity.htm |
| 北京 | 古北口镇 | Gubeikou Town | shuttle | 前门站 | 09:00 | 09:00 | 141 | no_official_page | baidu |  |  |
| 北京 | 居庸关长城 | Juyongguan Great Wall | shuttle | 王府井站(C4西南口) | 09:00 | 09:00 | 60 | no_official_page | baidu |  |  |
| 北京 | 慕田峪长城 | Mutianyu Great Wall | shuttle | Qianmen Street north entrance (Beijing H | 07:30 | 10:30 | 90 | verified | official |  | https://en.mutianyugreatwall.com/pdf/one-day |
| 北京 | 慕田峪长城索道滑道 | Mutianyu Great Wall Cableway and Slide | shuttle | 前门站 | 07:00 | 12:00 | 109 | verified | baidu | official | https://en.mutianyugreatwall.com/pdf/one-day |
| 北京 | 潭柘寺 | Tanzhe Temple | shuttle | 东城三里河站 | 09:00 | 09:00 | 61 | verified | baidu | official | https://s.visitbeijing.com.cn/attraction/117841 |
| 北京 | 焦庄户村 | Jiaozhuanghu Village | shuttle | 王府井站(C4西南口) | 07:30 | 15:30 | 113 | verified | baidu | official | http://www.bjsupervision.gov.cn/lzdt/202101/t20210105_72 |
| 北京 | 百里山水画廊 | Baili Landscape Gallery | shuttle | 王府井站(C4西南口) | 09:10 | 09:10 | 181 | verified | baidu | official | http://www.blsshl.com/index.php/menpiao.html |
| 北京 | 箭扣长城 | Jiankou Great Wall | bus | 王府井站(C4西南口) | 05:50 | 20:00 | 119 | no_official_page | baidu |  |  |
| 北京 | 詹天佑纪念馆 | Zhan Tianyou Memorial Hall | shuttle | 前门站 | 06:30 | 11:00 | 92 | verified | baidu | official | https://s.visitbeijing.com.cn/attraction/101638 |
| 北京 | 长城之漫观景台 | Great Wall Romance Viewing Platform | shuttle | 前门站 | 06:30 | 11:00 | 92 | verified | baidu |  | https://www.badaling.cn/ |
| 北京 | 雁柏山庄 | Yanbai Villa | shuttle | 王府井站(C4西南口) | 09:10 | 09:10 | 101 | verified | baidu |  | https://www.slhhotels.cn/hotel/yanbai-villa |
| 北京 | 雁栖湖 | Yanqi Lake | shuttle | 王府井站(C4西南口) | 09:10 | 09:10 | 101 | no_official_page | baidu |  |  |
| 南京 | 濮塘风景区 | Putang Scenic Area | shuttle | 鸡鸣寺站(5口) | 13:10 | 13:10 | 113 | pending | baidu |  |  |
| 广州 | 广州融创乐园 | Guangzhou Sunac Land | train | 北京路站(B口) | 08:48 | 08:48 | 87 | pending | baidu |  |  |
| 广州 | 广州融创体育世界 | Guangzhou Sunac Sports World | train | 纪念堂站(D1口) | 09:12 | 09:12 | 68 | pending | baidu |  |  |
| 广州 | 广州融创大马戏-奇幻秘境 | Guangzhou Sunac Grand Circus - Fantasy Secret Realm | train | 纪念堂站(D1口) | 09:12 | 09:12 | 68 | pending | baidu |  |  |
| 广州 | 蝴蝶谷 | Butterfly Valley | train | 中山纪念堂(市总工会)③站 | 09:26 | 20:45 | 202 | pending | baidu |  |  |
| 成都 | 中铁花水湾四季温泉谷 | CRETC Huashuiwan Four Seasons Hot Spring Valley | shuttle | 孵化园站(E1口) | 10:50 | 10:50 | 129 | pending | baidu |  |  |
| 成都 | 九龙峡漂流 | Jiulong Gorge Rafting | shuttle | 锦悦西路站 | 13:40 | 13:40 | 168 | no_official_page | baidu |  |  |
| 成都 | 伏龙观 | Fulong Temple | train | 孵化园站(E1口) | 07:36 | 07:36 | 333 | pending | baidu |  |  |
| 成都 | 又一村 | Youyicun | shuttle | 孵化园站(E1口) | 07:30 | 19:00 | 369 | pending | baidu |  |  |
| 成都 | 四川建川博物馆聚落 | Jianchuan Museum Cluster, Sichuan | shuttle | 孵化园站(E1口) | 08:45 | 17:15 | 72 | verified | baidu | official | https://www.jc-museum.cn/en/ticket |
| 成都 | 四川省建川博物馆 | Jianchuan Museum, Sichuan Province | shuttle | 孵化园站(E1口) | 08:45 | 17:15 | 72 | verified | baidu | official | https://www.jc-museum.cn/en/ticket |
| 成都 | 天然图画 | Natural Picture Scenic Spot | train | 孵化园站(E1口) | 07:36 | 07:36 | 333 | pending | baidu |  |  |
| 成都 | 安仁古镇-公馆老街 | Anren Ancient Town - Mansion Old Street | bus | 孵化园站(E1口) | 08:30 | 08:30 | 66 | verified | baidu | official | https://new.china-anren.com/ |
| 成都 | 安仁古镇景区 | Anren Ancient Town Scenic Area | shuttle | 孵化园站(E1口) | 08:45 | 17:15 | 57 | verified | baidu | official | https://new.china-anren.com/ |
| 成都 | 安仁镇 | Anren Town | shuttle | 孵化园站(E1口) | 08:45 | 17:15 | 57 | verified | baidu | official | https://new.china-anren.com/ |
| 成都 | 宝山旅游景区 | Baoshan Tourist Attraction | shuttle | 孵化园站(E1口) | 06:40 | 17:30 | 170 | verified | baidu | official | https://baike.baidu.com/item/宝山旅游景区/17644705 |
| 成都 | 宝山温泉 | Baoshan Hot Springs | shuttle | 孵化园站(E1口) | 06:40 | 17:30 | 175 | verified | baidu | official | https://baike.baidu.com/item/宝山旅游景区/17644705 |
| 成都 | 成都市西岭雪山景区 | Xiling Snow Mountain Scenic Area, Chengdu | shuttle | 孵化园站(E1口) | 10:50 | 10:50 | 167 | verified | baidu | official | https://www.xiling.cn/website/survey/tour |
| 成都 | 日月坪 | Riyueping | shuttle | 孵化园站(E1口) | 10:50 | 10:50 | 167 | verified | baidu | official | https://www.xiling.cn/website/survey/tour |
| 成都 | 普照寺 | Puzhao Temple | train | 孵化园站(E1口) | 07:36 | 07:36 | 334 | pending | baidu |  |  |
| 成都 | 月城湖 | Yuecheng Lake | train | 孵化园站(E1口) | 07:36 | 07:36 | 333 | pending | baidu |  |  |
| 成都 | 泰安古镇 | Tai'an Ancient Town | shuttle | 孵化园站(E1口) | 07:30 | 19:00 | 369 | pending | baidu |  |  |
| 成都 | 浪朗地中海水上乐园 | Langlang Mediterranean Water Park | shuttle | 孵化园站(E1口) | 07:10 | 19:30 | 105 | no_official_page | baidu |  |  |
| 成都 | 熊猫小匠研学体验基地 | Panda Little Craftsman Study Tour Experience Base | train | 孵化园站(E1口) | 07:36 | 07:36 | 336 | no_official_page | baidu |  |  |
| 成都 | 花水湾温泉度假区 | Huashuiwan Hot Spring Resort | shuttle | 孵化园站(E1口) | 10:50 | 10:50 | 129 | pending | baidu |  |  |
| 成都 | 花水湾第一村温泉 | Huashuiwan First Village Hot Springs | shuttle | 孵化园站(E1口) | 10:50 | 10:50 | 129 | pending | baidu |  |  |
| 成都 | 花水湾豪生百乐汤温泉 | Huashuiwan Howard Johnson Bailetang Hot Spring | shuttle | 孵化园站(E1口) | 10:50 | 10:50 | 129 | pending | baidu |  |  |
| 成都 | 西岭峡谷漂流 | Xiling Gorge Rafting | shuttle | 孵化园站(E1口) | 10:50 | 10:50 | 143 | verified | baidu | official | https://www.xiling.cn/website/survey/tour |
| 成都 | 西岭雪山 | Xiling Snow Mountain | shuttle | 孵化园站(E1口) | 10:50 | 10:50 | 167 | verified | baidu | official | https://www.xiling.cn/website/survey/tour |
| 成都 | 都江堰中华大熊猫苑(原熊猫乐园) | Dujiangyan Panda Base (formerly Panda Paradise) | train | 孵化园站(E1口) | 07:36 | 07:36 | 327 | pending | baidu |  |  |
| 成都 | 青城前山-索道 | Qingcheng Front Mountain - Ropeway | train | 孵化园站(E1口) | 07:36 | 07:36 | 333 | pending | baidu |  |  |
| 成都 | 青城山 | Mount Qingcheng | train | 孵化园站(E1口) | 07:36 | 07:36 | 327 | pending | baidu |  |  |
| 成都 | 青城山尊铂森林温泉 | Mount Qingcheng Zunbo Forest Hot Springs | train | 孵化园站(E1口) | 07:36 | 07:36 | 333 | pending | baidu |  |  |
| 成都 | 飞沙堰 | Flying Sand Weir | train | 孵化园站(E1口) | 07:36 | 07:36 | 333 | pending | baidu |  |  |
| 成都 | 黄龙溪廊桥 | Huanglongxi Corridor Bridge | shuttle | 锦城广场东站(A口) | 09:00 | 09:00 | 47 | no_official_page | baidu |  |  |
| 杭州 | COOL漂流乐园 | COOL Rafting Park | shuttle | 武林门站 | 09:30 | 15:30 | 172 | pending | baidu |  |  |
| 杭州 | OMG心跳乐园 | OMG Heartbeat Park | shuttle | 武林门站(A2口) | 13:00 | 13:00 | 223 | pending | baidu |  |  |
| 杭州 | 三渡悬崖漂流 | Sandu Cliff Rafting | shuttle | 武林门站 | 09:30 | 15:30 | 136 | pending | baidu |  |  |
| 杭州 | 下姜村 | Xiajiang Village | train | 武林门站 | 10:30 | 15:30 | 696 | no_official_page | baidu |  |  |
| 杭州 | 临安博物馆 | Lin'an Museum | shuttle | 武林广场北②站 | 07:10 | 19:30 | 58 | pending | baidu |  |  |
| 杭州 | 九溪十八涧 | Jiuxi Shibajian (Nine Creeks and Eighteen Gullies) | shuttle | 武林门站 | 09:30 | 15:30 | 151 | pending | baidu |  |  |
| 杭州 | 九溪烟树 | Nine Creeks and Misty Trees | shuttle | 武林门站 | 09:30 | 15:30 | 151 | pending | baidu |  |  |
| 杭州 | 九龙溪漂流 | Jiulongxi Rafting | shuttle | 武林门站 | 11:00 | 11:00 | 318 | no_official_page | baidu |  |  |
| 杭州 | 凌云天桥 | Lingyun Sky Bridge | shuttle | 武林门站(A2口) | 13:00 | 13:00 | 223 | pending | baidu |  |  |
| 杭州 | 千岛湖冰火岛ATV山地越野车俱乐部 | Qiandao Lake Ice-Fire Island ATV Mountain Off-Road Club | shuttle | 武林门站 | 11:00 | 11:00 | 765 | no_official_page | baidu |  |  |
| 杭州 | 千岛湖华美胜地度假区 | Qiandao Lake Huamei Resort Area | shuttle | 武林门站 | 11:00 | 11:00 | 1073 | no_official_page | baidu |  |  |
| 杭州 | 千岛湖城中湖休闲游 | Qiandao Lake City Lake Leisure Cruise | shuttle | 武林门站 | 11:00 | 11:00 | 596 | no_official_page | baidu |  |  |
| 杭州 | 千岛湖景区 | Qiandao Lake Scenic Area | shuttle | 武林门站 | 11:00 | 11:00 | 596 | no_official_page | baidu |  |  |
| 杭州 | 千岛湖红叶湾水上乐园 | Qiandao Lake Red Leaf Bay Water Park | shuttle | 武林门站 | 11:00 | 11:00 | 507 | no_official_page | baidu |  |  |
| 杭州 | 千岛湖豪华休闲游 | Qiandao Lake Deluxe Leisure Tour | shuttle | 武林门站 | 11:00 | 11:00 | 596 | no_official_page | baidu |  |  |
| 杭州 | 千岛湖鱼跃龙门漂流 | Qiandao Lake Yuyue Longmen Rafting | shuttle | 武林门站 | 11:00 | 11:00 | 294 | no_official_page | baidu |  |  |
| 杭州 | 千岛湖龙晨水搏乐园 | Qiandao Lake Longchen Water Park | shuttle | 武林门站 | 11:00 | 11:00 | 316 | no_official_page | baidu |  |  |
| 杭州 | 千岛秘境 | Hidden Realm of the Thousand Islands | shuttle | 混堂桥站 | 09:30 | 09:30 | 292 | no_official_page | baidu |  |  |
| 杭州 | 双溪漂流景区 | Shuangxi Rafting Scenic Area | shuttle | 密渡桥站 | 08:00 | 08:00 | 98 | no_official_page | baidu |  |  |
| 杭州 | 垂云通天河 | Chuiyun Tongtian River | shuttle | 武林门站(A2口) | 13:00 | 13:00 | 223 | pending | baidu |  |  |
| 杭州 | 天子地梦幻乐园 | Tianzidi Dreamland | shuttle | 庆丰村1 |  |  | 129 | pending |  |  |  |
| 杭州 | 天目大峡谷 | Tianmu Grand Canyon | shuttle | 武林门站 | 09:30 | 15:30 | 145 | no_official_page | baidu |  |  |
| 杭州 | 天目山景区 | Tianmu Mountain Scenic Area | shuttle | 武林门站 | 09:30 | 15:30 | 119 | no_official_page | baidu |  |  |
| 杭州 | 天目溪漂流 | Tianmu Creek Rafting | shuttle | 武林门站(A2口) | 13:00 | 13:00 | 223 | pending | baidu |  |  |
| 杭州 | 天路飞车 | Tianlu Stunt Car Show | shuttle | 武林门站(A2口) | 13:00 | 13:00 | 227 | pending | baidu |  |  |
| 杭州 | 富春桃源 | Fuchun Taoyuan | shuttle | 武林门站(A2口) | 09:40 | 09:40 | 141 | pending | baidu |  |  |
| 杭州 | 富阳龙鳞坝景区 | Fuyang Longlin Dam Scenic Area | shuttle | 武林门站(A2口) | 10:00 | 10:00 | 135 | pending | baidu |  |  |
| 杭州 | 山湾湾激流探险 | Shanwanwan Whitewater Rafting Adventure | shuttle | 武林门站 | 09:30 | 15:30 | 250 | pending | baidu |  |  |
| 杭州 | 径山寺 | Jingshan Temple | shuttle | 密渡桥站 | 08:00 | 08:00 | 98 | no_official_page | baidu |  |  |
| 杭州 | 杭州国家版本馆 (文润阁) |  | shuttle |  |  |  |  |  |  |  |  |
| 杭州 | 杭州径山寺溪山竹院 | Xishan Bamboo Courtyard, Jingshan Temple, Hangzhou | shuttle | 密渡桥站 | 08:00 | 08:00 | 107 | no_official_page | baidu |  |  |
| 杭州 | 柳溪江 | Liuxi River | shuttle | 武林门站 | 09:30 | 15:30 | 129 | pending | baidu |  |  |
| 杭州 | 浙西凉源峡漂流 | Liangyuan Gorge Rafting, Western Zhejiang | shuttle | 混堂桥站 | 09:00 | 09:00 | 199 | pending | baidu |  |  |
| 杭州 | 湖源溪漂流 | Huyuan Stream Rafting | shuttle | 武林门站(A2口) | 10:00 | 10:00 | 145 | pending | baidu |  |  |
| 杭州 | 王子谷漂流 | Wangzi Valley Rafting | shuttle | 混堂桥站 | 09:30 | 09:30 | 283 | no_official_page | baidu |  |  |
| 杭州 | 瑶琳仙境 | Yaolin Fairyland | shuttle | 混堂桥站 | 09:40 | 09:40 | 189 | pending | baidu |  |  |
| 杭州 | 石舍村 | Shishe Village | bus | 武林门站(A2口) | 12:20 | 12:20 | 305 | pending | baidu |  |  |
| 杭州 | 禅源寺 | Chanyuan Temple | shuttle | 武林门站 | 09:30 | 15:30 | 119 | no_official_page | baidu |  |  |
| 杭州 | 红叶湾景点 | Hongye Bay Scenic Spot | shuttle | 武林门站 | 11:00 | 11:00 | 371 | no_official_page | baidu |  |  |
| 杭州 | 良渚博物院 |  | shuttle |  |  |  |  |  |  |  |  |
| 杭州 | 良渚古城遗址 |  | shuttle |  |  |  |  |  |  |  |  |
| 杭州 | 良渚文化村 |  | shuttle |  |  |  |  |  |  |  |  |
| 杭州 | 蓝湾水上乐园 | Lanwan Water Park | shuttle | 武林门站 | 11:00 | 11:00 | 340 | no_official_page | baidu |  |  |
| 杭州 | 西天目风景区 | West Tianmu Mountain Scenic Area | shuttle | 武林门站 | 09:30 | 15:30 | 122 | no_official_page | baidu |  |  |
| 杭州 | 轻野小坞Glamping露营地 | Qingye Xiaowu Glamping Campsite | shuttle | 武林门站 | 08:00 | 08:00 | 108 | no_official_page | baidu |  |  |
| 杭州 | 金峰峡谷漂流 | Jinfeng Canyon Rafting | shuttle | 武林门站 | 11:00 | 11:00 | 526 | no_official_page | baidu |  |  |
| 杭州 | 钱王祠 | Qianwang Temple (King Qian's Shrine) | shuttle | 武林门站 | 09:30 | 15:30 | 163 | pending | baidu |  |  |
| 杭州 | 雅鲁激流探险漂流 | Yalu Rapids Adventure Rafting | shuttle | 武林门站 | 09:30 | 15:30 | 383 | pending | baidu |  |  |
| 杭州 | 青山殿村 | Qingshandian Village | shuttle | 武林门站(A2口) | 06:30 | 18:30 | 185 | pending | baidu |  |  |
| 杭州 | 青山湖水上森林 | Qingshan Lake Water Forest | shuttle | 武林广场北②站 | 07:10 | 19:30 | 66 | pending | baidu |  |  |
| 杭州 | 龙井峡漂流 | Longjing Gorge Rafting | shuttle | 武林门站 | 09:30 | 15:30 | 151 | pending | baidu |  |  |
| 杭州 | 龙潭峡谷漂流 | Longtan Gorge Rafting | shuttle | 武林门站 | 11:00 | 11:00 | 341 | no_official_page | baidu |  |  |
| 深圳 | 梧桐山艺术小镇 |  | shuttle |  |  |  |  |  |  |  |  |
| 苏州 | 七都镇 | Qidu Town | shuttle | 桐泾北路站(1口) | 06:30 | 18:10 | 93 | pending | baidu |  |  |
| 苏州 | 上方山森林动物世界 | Shangfangshan Forest Animal World | shuttle | 桐泾北路站(1口) | 06:30 | 18:10 | 105 | pending | baidu |  |  |
| 苏州 | 双湖欢乐园 | Shuanghu Amusement Park | shuttle | 桐泾北路站(1口) | 07:30 | 20:30 | 110 | pending | baidu |  |  |
| 苏州 | 淀山湖 | Dianshan Lake | bus | 桐泾北路站(1口) | 09:30 | 09:30 | 125 | pending | baidu |  |  |
| 苏州 | 淀山湖庄园露营地 | Dianshan Lake Manor Campground | bus | 桐泾北路站(1口) | 09:30 | 09:30 | 162 | pending | baidu |  |  |
| 苏州 | 苏州御窑金砖博物馆 | Suzhou Imperial Kiln Golden Brick Museum | shuttle | 桐泾北路站(1口) | 07:30 | 20:30 | 123 | pending | baidu |  |  |
| 苏州 | 阳澄湖水上公园游乐场 | Yangcheng Lake Water Park Amusement Park | shuttle | 桐泾北路站(1口) | 07:30 | 20:30 | 123 | pending | baidu |  |  |
| 苏州 | 震泽古镇 | Zhenze Ancient Town | shuttle | 桐泾北路 |  |  | 23 | pending |  |  |  |
| 苏州 | 震泽镇 | Zhenze Town | shuttle | 桐泾北路站(1口) | 09:15 | 09:15 | 139 | pending | baidu |  |  |
| 苏州 | 黎里镇 | Lili Town | shuttle | 桐泾北路站(1口) | 06:10 | 18:25 | 110 | pending | baidu |  |  |
