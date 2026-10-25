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
        "note": "官方微信提前 5 天 17:00 放免费票，秒光；仅二代身份证，外籍需代订",
        "note_en": "Official WeChat releases free tickets 5 days ahead at 17:00, sells out within seconds; 2nd-gen Chinese ID only — foreigners must use a proxy booking",  # noqa: E501
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
        "note": "「布达拉宫票务预订系统」小程序提前 10 天，须本人微信端购票+人脸认证",
        "note_en": "'Potala Palace Ticket Booking System' mini-program, book 10 days ahead; must be purchased on the visitor's own WeChat account with facial-recognition verification",  # noqa: E501
    },
}

FOREIGNER_TIP = (
    "外国手机号/护照在小程序常失败——Trip.com/Klook 代抢是标准解法"
    "（故宫官网/三星堆境外通道/熊猫基地携程频道护照可自助；"
    "陕历博仅限二代身份证，必须代订）"
)

# 英文版（H5 英文态渲染用；与上面中文版口径一致）
FOREIGNER_TIP_EN = (
    "Foreign phone numbers/passports often fail in WeChat mini-programs — "
    "booking via Trip.com/Klook is the standard workaround "
    "(Forbidden City official site / Sanxingdui overseas channel / "
    "Panda Base Ctrip channel accept passports for self-service; "
    "Shaanxi History Museum requires a 2nd-gen Chinese ID — "
    "must use a proxy booking)"
)


def reservation_meta_for(name: str) -> dict | None:
    """精确名命中（调用方先用 _same_site 判同一性，这里只做字典命中）。"""
    return RESERVATION_V0.get((name or "").strip())
