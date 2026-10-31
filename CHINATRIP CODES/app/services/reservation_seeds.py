"""G1 预约制门票名单 v0（DESIGN §14.3-G1，2026-10-25 校订）。

入境第一实操痛：故宫类提前 N 天放票秒光、外国手机号常失败——
Trip.com/Klook 代抢是外国人标准解法。值结构化 {days, release, note}：
release=放票时刻（L1 放票提醒任务推算用，"00:00"=未注明）；
后续由携程 sight 页「需预约」标识回源补量 + poi.reservation_
required 落库接管（本名单只在库列空时兜底）。

官方口径校订 2026-10-25（二轮全量核对，来源含各馆官网/预约须知/
官方公告）：天安门/布达拉宫/熊猫基地/湖南博物院/秦汉馆/八达岭/
雍和宫 7 处已按最新口径修正；故宫/国博/陕历博/三星堆/南博/
毛主席纪念堂 与官方一致。三轮官方直核补正 2 处（同日晚）：恭王府
7→10 天（文旅部 2019-12 全网售票公告：提前 10 天预售、十日前 20:00
可订）、莫高窟 15→30 天（敦煌市政府 2025 公告/新华网：门票可提前
30 天在莫高窟参观预约网预订）。差异项与待人工确认清单见
DESIGN/reservation_seeds_核对_2026-10-25.md。

双语补丁 2026-10-25：每条 note 增补 note_en（H5 英文态渲染），
FOREIGNER_TIP 配套 FOREIGNER_TIP_EN；中文键值字节不变，只加字段。

扩充 10 项（2026-10-26，用户点名「扩充的10项要的」，官方口径本轮直核）：
兵马俑（官方票务 bmy.albatrip.cn，平日 7 天/节假日 10 天，未授权第三方）、
上海天文馆（前 7 天含当日 9:30 开售）、中国科学技术馆（官网实名购票，
预售期未注明）、国家自然博物馆（提前 3 天每日 11:00）、苏州博物馆
（提前 7 天每日凌晨 0 点）、上海博物馆（14 天每日 12:00；东馆常设展
试行免预约）、湖北省博物馆（5 天每日 17:18）、河南博物院（官方未注明
——note 注明以公众号为准）、甘肃省博物馆（3 天每日 17:00）、梵净山
（当天 07:00 三轮投放，days=0=当天票）。

批 2（沪苏杭）：中共一大纪念馆（免费，1-7 天实名全预约，周一闭馆）、拙政园
（7 天/零点放票，现场无售票）、灵隐飞来峰（分时预约，提前 1 天；门票+香花券
分开买）并入，西湖/朱家角/黄浦江游览/平江路/七里山塘/虎丘/周庄 7 行 无需预约。
批 3（广深）：大梅沙海滨公园（旺季 5-10 月免费实名预约提前 7 天，淡季免约）
并入，广州塔/沙面岛/长隆/珠江夜游/陈家祠/光孝寺/世界之窗/OCT-LOFT/深圳湾公园
9 行 无需预约。批 4（渝汉西安）10 行全 无需预约。批 5（丽江/哈尔滨/闽/黄山/
港/鄂西北/晋中）：黄山风景区（强实名分时预约至少提前 1 天，现场不售票）
并入，丽江古城/冰雪大世界/圣索菲亚/鼓浪屿（船票瓶颈）/永定土楼/太平山顶/
武当山/平遥古城/西递宏村 9 行 无需预约。差异项与批次明细见
DESIGN/reservation_seeds_核对_2026-10-25.md。

外籍渠道轮（2026-10-29）：09 号表与 data/reservation_pois.csv 新增
official_channel_foreign 列（38 馆逐馆直核+129 行分类规则）；陕历博口径
修正（官网票务系统护照+国际手机号可约、到馆人工窗口换票，小程序仍限二代
身份证）、河南博 days 2→3（官网明示提前 3 日、护照为五种有效证件之一）、
布达拉宫 note 补外籍随团入藏、上博 note 补英文预约系统；FOREIGNER_TIP
双语重写。详见核对 md「外籍渠道分列核查」章节（含灵隐免票传闻/大梅沙
预约下架两条待人工确认）。
"""

# 名字 → {days 提前天数, release 放票时刻, note 渠道提示}；
# 名字匹配走 _same_site 同款容错
RESERVATION_V0: dict[str, dict] = {
    "故宫": {
        "days": 7,
        "release": "20:00",
        "note": "微信小程序「故宫博物院」每日 20:00 放 7 天后门票，护照可约",
        "note_en": "WeChat mini-program 'The Palace Museum' releases tickets 7 days out daily at 20:00; passports accepted for booking",  # noqa: E501
    },
    "故宫博物院": {
        "days": 7,
        "release": "20:00",
        "note": "同「故宫」——微信小程序 20:00 放票，护照可约",
        "note_en": "Same as the Palace Museum — tickets released daily at 20:00 on the WeChat mini-program; passports accepted",  # noqa: E501
    },
    "中国国家博物馆": {
        "days": 7,
        "release": "17:00",
        "note": "官网/小程序提前约 7 天，每日 17:00 放免费票",
        "note_en": "Official website/mini-program, book up to 7 days ahead; free tickets released daily at 17:00",  # noqa: E501
    },
    "天安门广场": {
        "days": 1,
        "release": "12:00",
        "note": "「天安门广场预约参观」小程序提前 1-7 天，每日 12:00 放第 7 天票",
        "note_en": "'Tiananmen Square Visit Reservation' mini-program, book 1-7 days ahead; day-7 tickets released daily at 12:00",  # noqa: E501
    },
    "毛主席纪念堂": {
        "days": 1,
        "release": "00:00",
        "note": "「毛主席纪念堂预约」小程序提前 1-6 天（仅上午开放）",
        "note_en": "'Chairman Mao Memorial Hall Reservation' mini-program, book 1-6 days ahead (morning-only opening)",  # noqa: E501
    },
    "陕西历史博物馆": {
        "days": 5,
        "release": "17:00",
        "note": "官方微信提前 5 天 17:00 放免费票，秒光；小程序仅限二代身份证，外籍走官网票务系统护照预约、到馆人工窗口换票",  # noqa: E501
        "note_en": "Official WeChat releases free tickets 5 days ahead at 17:00, sells out within seconds; the mini-program needs a 2nd-gen Chinese ID — foreigners book on the official website with passport + international phone number, then exchange the ticket at the manual window",  # noqa: E501
    },
    "陕西历史博物馆秦汉馆": {
        "days": 5,
        "release": "17:30",
        "note": "官方微信提前 5 天 17:30 放票（较主馆晚半小时）",
        "note_en": "Official WeChat releases tickets 5 days ahead at 17:30 (half an hour later than the main museum)",  # noqa: E501
    },
    "三星堆博物馆": {
        "days": 5,
        "release": "20:00",
        "note": "官方小程序提前 5 天 20:00 放票；设境外游客单独预约通道",
        "note_en": "Official mini-program releases tickets 5 days ahead at 20:00; a separate booking channel is available for overseas visitors",  # noqa: E501
    },
    "湖南博物院": {
        "days": 7,
        "release": "20:00",
        "note": "官方微信公众号/小程序提前 7 天，每日 20:00 放免费票（以公众号最新《预约说明》为准）",  # noqa: E501
        "note_en": "Official WeChat account/mini-program, book up to 7 days ahead; free tickets released daily at 20:00 (subject to the latest Booking Notice on the official account)",  # noqa: E501
    },
    "南京博物院": {
        "days": 7,
        "release": "18:00",
        "note": "官方小程序提前 7 天 18:00 放票（免费）",
        "note_en": "Official mini-program releases tickets 7 days ahead at 18:00 (free)",  # noqa: E501
    },
    "八达岭长城": {
        "days": 7,
        "release": "00:00",
        "note": "「长城内外旅游」小程序/badaling.cn 提前 7 天分时预约，现场不售票",
        "note_en": "'Great Wall Inside & Outside Travel' mini-program/badaling.cn, timed-entry booking 7 days ahead; no tickets sold on site",  # noqa: E501
    },
    "雍和宫": {
        "days": 7,
        "release": "00:00",
        "note": "「雍和宫游客信众服务」公众号/小程序提前 1-7 天购票（未授权第三方）",
        "note_en": "'Yonghe Temple Visitors & Pilgrims Service' WeChat account/mini-program, buy 1-7 days ahead (no third-party channels are authorized)",  # noqa: E501
    },
    "恭王府": {
        "days": 10,
        "release": "20:00",
        "note": "官网 pgm.org.cn/官方渠道提前 10 天预售，最早参观十日前 20:00 可订（文旅部 2019-12 全网售票公告口径）",  # noqa: E501
        "note_en": "Official site pgm.org.cn/official channels presale 10 days ahead; earliest booking at 20:00 ten days before the visit (per the Ministry of Culture and Tourism 2019-12 network-wide ticketing announcement)",  # noqa: E501
    },
    "四川大熊猫繁育研究基地": {
        "days": 14,
        "release": "00:00",
        "note": "官方小程序/美团/携程提前 14 天可订，分上下午票（携程为官方授权渠道）",
        "note_en": "Official mini-program/Meituan/Ctrip bookable 14 days ahead, split into morning and afternoon tickets (Ctrip is the officially authorized channel)",  # noqa: E501
    },
    "成都大熊猫繁育研究基地": {
        "days": 14,
        "release": "00:00",
        "note": "同「四川大熊猫繁育研究基地」——提前 14 天可订",
        "note_en": "Same as the Sichuan Giant Panda Breeding Research Base — bookable 14 days ahead",  # noqa: E501
    },
    "敦煌莫高窟": {
        "days": 30,
        "release": "00:00",
        "note": "「莫高窟参观预约网」(mgk.org.cn) 提前 30 天预订（敦煌市政府 2025 公告/新华网口径），旺季秒光",  # noqa: E501
        "note_en": "Mogao Caves Visit Reservation site (mgk.org.cn), book 30 days ahead (per the Dunhuang Municipal Government 2025 announcement/Xinhua); sells out within minutes in peak season",  # noqa: E501
    },
    "布达拉宫": {
        "days": 10,
        "release": "00:00",
        "note": "「布达拉宫票务预订系统」小程序提前 10 天，须本人微信端购票+人脸认证；外籍须随团入藏（入藏函），由旅行社凭护照代订",  # noqa: E501
        "note_en": "'Potala Palace Ticket Booking System' mini-program, book 10 days ahead; must be purchased on the visitor's own WeChat account with facial-recognition verification; foreigners must join an organized tour (Tibet travel permit) with agency booking",  # noqa: E501
    },
    "秦始皇帝陵博物院": {
        "days": 7,
        "release": "00:00",
        "note": "官方票务系统 bmy.albatrip.cn/官方公众号：平日提前 7 天、节假日提前 10 天；博物院未授权任何第三方销售",  # noqa: E501
        "note_en": "Official ticketing system bmy.albatrip.cn / official WeChat: 7 days ahead (10 days on holidays); no third-party sellers are authorized",  # noqa: E501
    },
    "兵马俑": {
        "days": 7,
        "release": "00:00",
        "note": "同「秦始皇帝陵博物院」",
        "note_en": "Same as the Emperor Qinshihuang's Mausoleum Site Museum",
    },
    "上海天文馆": {
        "days": 7,
        "release": "09:30",
        "note": "参观票前 7 天（含当日）9:30 开售、电影票 10:00（官方公告口径）；暑期秒光，参观日前一天 23:30 前可退",  # noqa: E501
        "note_en": "Visit tickets go on sale 7 days ahead (including the visit day) at 09:30, movie tickets at 10:00; sells out instantly in summer; refunds until 23:30 the day before",  # noqa: E501
    },
    "中国科学技术馆": {
        "days": 7,
        "release": "00:00",
        "note": "官网 pcticket.cstm.org.cn 实名购票；官方预售期未注明，以官网为准（OTA 有当日/次日票）",  # noqa: E501
        "note_en": "Real-name purchase on the official site pcticket.cstm.org.cn; official presale window not stated — follow the official site",  # noqa: E501
    },
    "国家自然博物馆": {
        "days": 3,
        "release": "11:00",
        "note": "官网/微信公众号提前 3 日预约，每日 11:00 更新（官方口径）；免费，团体提前 4 日",  # noqa: E501
        "note_en": "Book free tickets 3 days ahead on the official site/WeChat, refreshed daily at 11:00; groups 4 days ahead",  # noqa: E501
    },
    "苏州博物馆": {
        "days": 7,
        "release": "00:00",
        "note": "本馆全预约制：提前 7 天（含当天）官网/公众号/「苏州博物馆全预约」小程序，每日凌晨 0 点放票；当日有余票可当日约",  # noqa: E501
        "note_en": "Full reservation system: book 7 days ahead (including the visit day) via the official site/WeChat/'Suzhou Museum Full Reservation' mini-program, released at midnight daily; same-day slots possible if any remain",  # noqa: E501
    },
    "上海博物馆": {
        "days": 14,
        "release": "12:00",
        "note": "预约制期间散客提前 14 天、每日 12:00 放票（2024-04 起）；东馆常设展 2024-09 起试行免预约凭证入馆，特展以官方小程序为准；境外游客可用英文预约系统 reservation.shanghaimuseum.net/en（邮箱注册）",  # noqa: E501
        "note_en": "During reservation periods individuals book 14 days ahead, released daily at 12:00 (since 2024-04); the East Hall's permanent galleries have piloted walk-in entry since 2024-09 — special exhibitions follow the official mini-program; overseas visitors can use the English booking system reservation.shanghaimuseum.net/en (email sign-up)",  # noqa: E501
    },
    "湖北省博物馆": {
        "days": 5,
        "release": "17:18",
        "note": "官方微信公众号/官网提前 5 天，每日 17:18 放票；免费，每单最多 5 张，周一闭馆（节假日除外）",  # noqa: E501
        "note_en": "Book free tickets 5 days ahead via the official WeChat account/site, released daily at 17:18; up to 5 per order; closed Mondays (except holidays)",  # noqa: E501
    },
    "河南博物院": {
        "days": 3,
        "release": "00:00",
        "note": "官方微信公众号/官网分时段实名预约（免费，护照为五种有效证件之一）；官网明示提前 3 日，放票时刻未注明",  # noqa: E501
        "note_en": "Free timed-entry reservation via the official WeChat account/site — passports are one of five accepted ID types; officially 3 days ahead (release time not stated)",  # noqa: E501
    },
    "甘肃省博物馆": {
        "days": 3,
        "release": "17:00",
        "note": "微信公众号「甘肃省博物馆」提前 3 天（含当天）实名预约，每日 17:00 放票；免费，日限额 12000 人、4 场次",  # noqa: E501
        "note_en": "Book free tickets 3 days ahead (including the visit day) on the official WeChat account, released daily at 17:00; daily cap 12,000 across 4 time slots",  # noqa: E501
    },
    "梵净山": {
        "days": 0,
        "release": "07:00",
        "note": "官方 fanjingshan.gz.cn 实名分时预约：线上 5800 张/日三轮投放，散客票 07:00 起（节假日或提前至 06:30），当天 6:30-15:00 售当天票，22:00 后不售票；现场无售票窗口，旺季建议提前 1-3 天",  # noqa: E501
        "note_en": "Official fanjingshan.gz.cn timed reservation: 5,800 online tickets/day in three rounds, individual tickets from 07:00 (possibly 06:30 on holidays), same-day tickets sold 06:30-15:00, none after 22:00; no on-site ticket windows — book 1-3 days ahead in peak season",  # noqa: E501
    },
    # 批量核查并入（2026-10-29，data/reservation_pois.csv 待核 05 荐点批线上
    # 直核：人民网/上海本地宝、苏州园林旅游官方口径、搜狐/大河票务预约指南）
    "中共一大纪念馆": {
        "days": 7,
        "release": "00:00",
        "note": "免费参观：公众号/小程序「中共一大纪念馆」实名全预约（提前 1-7 天，护照可约），分时段入馆；周一闭馆（国定假日除外）；一大会址与纪念馆两个入口分开预约",  # noqa: E501
        "note_en": "Free entry by mandatory timed reservation (1-7 days ahead) on the official WeChat mini-program; passports accepted; closed Mondays; the CPC founding site and the memorial hall book separately",  # noqa: E501
    },
    "拙政园": {
        "days": 7,
        "release": "00:00",
        "note": "全网实名分时预约（现场无售票窗口）：公众号「苏州园林旅游」/官网最多提前 7 天，热门日零点放票秒空；护照可约；夜游《拙政问雅》单独购票",  # noqa: E501
        "note_en": "Mandatory real-name timed reservation (no on-site ticket windows) via the 'Suzhou Gardens Tourism' WeChat account or website, up to 7 days ahead; hot dates sell out at midnight release; passports accepted; night show ticketed separately",  # noqa: E501
    },
    "灵隐飞来峰": {
        "days": 1,
        "release": "00:00",
        "note": "线上预约入园（上午场 7:30-12:00 / 下午场 12:00-17:00，可提前 1 天约）：官方公众号或「西湖旅游」；飞来峰门票 45 元与灵隐寺香花券 30 元分开购买",  # noqa: E501
        "note_en": "Online timed reservation required (morning 7:30-12:00 / afternoon 12:00-17:00 sessions, bookable 1 day ahead) via the official WeChat account; Feilai Peak admission (CNY 45) and Lingyin Temple incense ticket (CNY 30) are sold separately",  # noqa: E501
    },
    "大梅沙海滨公园": {
        "days": 7,
        "release": "00:00",
        "note": "旺季（每年 5-10 月）免费实名预约入园：小程序「大梅沙旅游」提前 7 天约，日限流约 8 万，凭身份证/手机号；淡季（11-4 月）无需预约直接入园；免费，谨防第三方收费代订",  # noqa: E501
        "note_en": "Peak season (May-Oct): free real-name reservation required via the 'Dameisha Tourism' mini-program, bookable 7 days ahead, ~80k daily cap, ID/phone needed; off-season (Nov-Apr) walk in free; beware paid third-party resellers",  # noqa: E501
    },
    "黄山风景区": {
        "days": 1,
        "release": "00:00",
        "note": "强实名分时预约，现场不售票：小程序「黄山旅游官方平台」至少提前 1 天（当日不可约当日）；旺季 3-11 月建议提前 3 天、节假日提前 3-7 天抢热门时段；首次检票后 3 天内可多次入园",  # noqa: E501
        "note_en": "Strict real-name timed reservation, no on-site ticket sales: book on the 'Huangshan Tourism Official Platform' mini-program at least 1 day ahead (no same-day booking); in peak season (Mar-Nov) book 3 days ahead, 3-7 days for holidays to catch popular slots; re-entry allowed within 3 days of first ticket check",  # noqa: E501
    },
    "殷墟": {
        "days": 3,
        "release": "00:00",
        "note": "实名制售检票（2024-06-01 起）：公众号「殷墟博物馆」/官网/OTA 可预约购买 3 日内门票，二维码入馆凭本人身份证；新馆 80 元，联票两日内有效",  # noqa: E501
        "note_en": "Real-name booking and ticket checks (since 2024-06-01): book tickets within the next 3 days on the 'Yinxu Museum' WeChat account, official site or OTA; enter with QR code + your own ID; new museum CNY 80, combo ticket valid 2 days",  # noqa: E501
    },
    "中山陵": {
        "days": 7,
        "release": "16:00",
        "note": "陵寝免费但必须实名预约（提前 1-7 天，日限约 8 万）：服务号「中山陵园票务中心」/小程序「钟山风景区」，放票约每日 16:00（以公众号公告为准）；节假日提前 7 天零点蹲守；音乐台 10 元另购",  # noqa: E501
        "note_en": "The mausoleum is free but requires a real-name reservation (1-7 days ahead, ~80k daily cap) via the 'Zhongshan Mausoleum Ticket Center' service account or 'Zhongshan Scenic Area' mini-program; tickets release ~16:00 daily (check the official account); grab slots 7 days out on holidays; Music Stage CNY 10 separately",  # noqa: E501
    },
    "侵华日军南京大屠杀遇难同胞纪念馆": {
        "days": 7,
        "release": "08:00",
        "note": "免费但必须实名预约（提前 1-7 天）：公众号/小程序「侵华日军南京大屠杀遇难同胞纪念馆」，每日 8:00 放票（主史实展 17:00 补放）；三个展馆分开预约，凭二维码+证件原件入馆；周一闭馆",  # noqa: E501
        "note_en": "Free but mandatory real-name reservation (1-7 days ahead) via the memorial's official WeChat account; tickets release 08:00 daily (history exhibit re-releases at 17:00); the three exhibition halls book separately; enter with QR code + original ID; closed Mondays",  # noqa: E501
    },
    "澄江化石地": {
        "days": 1,
        "release": "00:00",
        "note": "澄江化石地世界自然遗产博物馆（云南省自然博物馆）免费开放，须预约：公众号「澄江化石地自然博物馆」提前约或现场扫码，凭码入馆；周一闭馆（法定假日除外）16:00 停止入场",  # noqa: E501
        "note_en": "The Chengjiang Fossil Site World Natural Heritage Museum (Yunnan Natural Museum) is free with reservation: book on the official WeChat account or scan on site; closed Mondays (open on statutory holidays), last entry 16:00",  # noqa: E501
    },
    "景德镇中国陶瓷博物馆": {
        "days": 1,
        "release": "00:00",
        "note": "免费但必须提前预约：小程序「畅游景德镇」/「景博预约」或官方公众号（唯一官方渠道，谨防收费代约）；周一闭馆；镇馆之宝「无语菩萨」（沉思罗汉）；境外游客凭护照享免预约入馆便利，热门时段名额紧张",  # noqa: E501
        "note_en": "Free with mandatory advance booking via the 'Changyou Jingdezhen' or 'Jingbo Yuyue' mini-programs (the only official channels); closed Mondays; home of the viral 'Speechless Bodhisattva'; foreign visitors may enter on passport without booking; hot periods sell out",  # noqa: E501
    },
}

FOREIGNER_TIP = (
    "外国手机号/护照在小程序常失败——Trip.com/Klook 代抢是标准解法"
    "（故宫官网/三星堆境外通道/熊猫基地携程频道/上博英文预约系统=护照可自助；"
    "陕历博小程序仅限二代身份证、官网可护照预约；布达拉宫外籍须随团由旅行社代订）"
)

# 英文版（H5 英文态渲染用；与上面中文版口径一致）
FOREIGNER_TIP_EN = (
    "Foreign phone numbers/passports often fail in WeChat mini-programs — "
    "booking via Trip.com/Klook is the standard workaround "
    "(Forbidden City official site / Sanxingdui overseas channel / "
    "Panda Base Ctrip channel / Shanghai Museum English booking site "
    "accept passports for self-service; Shaanxi History Museum's "
    "mini-program needs a 2nd-gen Chinese ID — book on its official "
    "website instead; Potala Palace requires an organized tour with "
    "agency booking)"
)


def reservation_meta_for(name: str) -> dict | None:
    """精确名命中（调用方先用 _same_site 判同一性，这里只做字典命中）。"""
    return RESERVATION_V0.get((name or "").strip())
