"""城市天气库（DESIGN §4.1 参考数据域 / §6.2 矩阵行：高德/百度天气 API）。

数据源：0-3 天实况+预报（默认跟随 settings.map_provider；上游 = 中国
气象局；按 adcode 查询，与 POI 库同键）+ Open-Meteo 14 天逐日。
上游时机：实况每小时更新、预报每日约 8/11/18 时三更；产品只需一天
一次，本侧管线每日 08:10 一班（紧跟早间更新）。2026-10-28 定稿：
**只抓 API 的就是这班管线**（请求路径 /sync 纯读表从不出网），且
默认全量 40 城——百度源免费大额；高德源 80 次/日（2 次/城）在其
~100 次/日个人配额内。全量覆盖保证新行程城市开站即有隔夜表数据。

写入语义 latest-wins：每 (source, adcode, kind) 仅一行 upsert，
report_time 保留上游侧数据时间，不堆历史。幂等可重跑。
"""

import logging
import uuid
from datetime import datetime

from app.models import Itinerary, ItineraryDay, TripItem, WeatherReport

logger = logging.getLogger(__name__)

WEATHER_SOURCE = "amap"

# 40 城市级 adcode（GB/T 2260，稳定编码）。敦煌为县级市 620982。
CITY_ADCODES = {
    "北京": "110000",
    "上海": "310000",
    "杭州": "330100",
    "苏州": "320500",
    "南京": "320100",
    "西安": "610100",
    "成都": "510100",
    "重庆": "500000",
    "广州": "440100",
    "深圳": "440300",
    "天津": "120000",
    "武汉": "420100",
    "长沙": "430100",
    "厦门": "350200",
    "青岛": "370200",
    "大连": "210200",
    "三亚": "460200",
    "丽江": "530700",
    "桂林": "450300",
    "洛阳": "410300",
    "敦煌": "620982",
    "兰州": "620100",
    "拉萨": "540100",
    "昆明": "530100",
    "大理": "532900",
    "张家界": "430800",
    "黄山": "341000",
    "无锡": "320200",
    "绍兴": "330600",
    "嘉兴": "330400",
    "舟山": "330900",
    "哈尔滨": "230100",
    "沈阳": "210100",
    "长春": "220100",
    "郑州": "410100",
    "济南": "370100",
    "福州": "350100",
    "泉州": "350500",
    "威海": "371000",
    "珠海": "440400",
    # 2026-10-30 扩容（POI 库∪预约名单缺口全量，用户拍板 any-missing-append）：
    # adcode+市中心坐标取自高德行政区划 API（/v3/config/district，官方表，
    # 非记忆数据）；坐标 GCJ-02→WGS-84。核心 40 城保持在字典前部——08:10
    # 抓取按插入序消耗百度配额，超额时新增城市退化为仅 Open-Meteo 14 天源。
    "三明": "350400",
    "上饶": "361100",
    "东营": "370500",
    "东阳": "330783",
    "中卫": "640500",
    "中山": "442000",
    "临汾": "141000",
    "临沂": "371300",
    "丹江口": "420381",
    "丽水": "331100",
    "乌鲁木齐": "650100",
    "乐山": "511100",
    "乐清": "330382",
    "九江": "360400",
    "五大连池": "231182",
    "井冈山": "360881",
    "介休": "140781",
    "伊春": "230700",
    "佛山": "440600",
    "保定": "130600",
    "保山": "530500",
    "信阳": "411500",
    "克拉玛依": "650200",
    "六安": "341500",
    "北海": "450500",
    "十堰": "420300",
    "华阴": "610582",
    "南充": "511300",
    "南宁": "450100",
    "南平": "350700",
    "南昌": "360100",
    "南通": "320600",
    "南阳": "411300",
    "句容": "321183",
    "台州": "331000",
    "合肥": "340100",
    "吐鲁番": "650400",
    "吴忠": "640300",
    "周口": "411600",
    "呼伦贝尔": "150700",
    "呼和浩特": "150100",
    "咸宁": "421200",
    "唐山": "130200",
    "商洛": "611000",
    "喀什": "653100",
    "嘉峪关": "620200",
    "大同": "140200",
    "天水": "620500",
    "太原": "140100",
    "宁安": "231084",
    "宁德": "350900",
    "宁波": "330200",
    "安庆": "340800",
    "安阳": "410500",
    "安顺": "520400",
    "宜昌": "420500",
    "宜春": "360900",
    "宝鸡": "610300",
    "宣城": "341800",
    "宿迁": "321300",
    "岳阳": "430600",
    "峨眉山": "511181",
    "崇左": "451400",
    "巴中": "511900",
    "常州": "320400",
    "常德": "430700",
    "常熟": "320581",
    "平凉": "620800",
    "平顶山": "410400",
    "广元": "510800",
    "广安": "511600",
    "庐山": "360483",
    "廊坊": "131000",
    "延安": "610600",
    "开封": "410200",
    "张掖": "620700",
    "徐州": "320300",
    "德阳": "510600",
    "忻州": "140900",
    "恩施": "422800",
    "惠州": "441300",
    "扬州": "321000",
    "承德": "130800",
    "抚州": "361000",
    "敦化": "222403",
    "新乡": "410700",
    "昆山": "320583",
    "晋中": "140700",
    "晋城": "140500",
    "普洱": "530800",
    "景德镇": "360200",
    "曲阜": "370881",
    "本溪": "210500",
    "松原": "220700",
    "林芝": "540400",
    "枣庄": "370400",
    "柳州": "450200",
    "株洲": "430200",
    "桐乡": "330483",
    "梅州": "441400",
    "武夷山": "350782",
    "毕节": "520500",
    "永城": "411481",
    "江山": "330881",
    "江门": "440700",
    "池州": "341700",
    "泰安": "370900",
    "泰州": "321200",
    "济宁": "370800",
    "海东": "630200",
    "淮安": "320800",
    "温州": "330300",
    "湖州": "330500",
    "溧阳": "320481",
    "滁州": "341100",
    "满洲里": "150781",
    "澳门": "820000",
    "灵武": "640181",
    "焦作": "410800",
    "玉树": "632700",
    "玉溪": "530400",
    "瑞金": "360781",
    "登封": "410185",
    "百色": "451000",
    "盐城": "320900",
    "盘锦": "211100",
    "石嘴山": "640200",
    "神农架林区": "429021",
    "福鼎": "350982",
    "秦皇岛": "130300",
    "红河": "532500",
    "绵阳": "510700",
    "肇庆": "441200",
    "腾冲": "530581",
    "芜湖": "340200",
    "荆门": "420800",
    "莆田": "350300",
    "萍乡": "360300",
    "蓬莱": "370614",
    "虎林": "230381",
    "衡阳": "430400",
    "衢州": "330800",
    "襄阳": "420600",
    "西双版纳": "532800",
    "西宁": "630100",
    "贵溪": "360681",
    "贵阳": "520100",
    "贺州": "451100",
    "资兴": "431081",
    "赣州": "360700",
    "赤峰": "150400",
    "运城": "140800",
    "连云港": "320700",
    "连州": "441882",
    "通化": "220500",
    "遵义": "520300",
    "遵化": "130281",
    "邯郸": "130400",
    "邵阳": "430500",
    "都江堰": "510181",
    "鄂尔多斯": "150600",
    "酒泉": "620900",
    "铜仁": "520600",
    "银川": "640100",
    "锡林郭勒": "152500",
    "镇江": "321100",
    "长治": "140400",
    "阆中": "511381",
    "阜康": "652302",
    "阜阳": "341200",
    "阳朔": "450321",
    "阳江": "441700",
    "阿坝": "513200",
    "阿拉善盟": "152900",
    "阿拉尔": "659002",
    "陇南": "621200",
    "雅安": "511800",
    "青州": "370781",
    "鞍山": "210300",
    "韶关": "440200",
    "韶山": "430382",
    "香港": "810000",
    "马鞍山": "340500",
    "驻马店": "411700",
    "龙口": "370681",
    "龙岩": "350800",
}


def normalize_city_name(city: str) -> str:
    """「市」后缀容错 + 英文别名归一（SHANGHAI→上海，2026-10-28 流水线日志
    实测行程城市含英文名）。CITY_ALIASES 惰性导入防循环依赖。"""
    s = city.strip().removesuffix("市")
    if s not in CITY_ADCODES:
        from app.services.agent.plan import CITY_ALIASES

        s = CITY_ALIASES.get(s.lower(), s)
    return s


def city_to_adcode(city: str | None) -> str | None:
    """城市名 → adcode；「市」后缀容错；6 位数字直接视为 adcode 透传。"""
    if not city:
        return None
    s = city.strip()
    if s.isdigit() and len(s) == 6:
        return s
    return CITY_ADCODES.get(normalize_city_name(s))


def parse_report_time(value: str | None) -> datetime | None:
    """高德 reporttime 形如 "2026-10-23 08:12:36"（北京时间，naive）。"""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _f_str(celsius: object) -> str | None:
    try:
        return str(round(float(celsius) * 9 / 5 + 32))
    except (TypeError, ValueError):
        return None


def _with_fahrenheit(payload: dict | None) -> dict | None:
    """入库时按摄氏派生华氏（口径 2026-10-24：库里 C/F 双存）——casts 补
    day_temp_f/night_temp_f，实况补 temperature_f。高德/OM 两源都过这个
    写入闸口，一处补齐；非数字派生失败留空，不阻断入库。"""
    if not isinstance(payload, dict):
        return payload
    if payload.get("temperature"):
        temp_f = _f_str(payload["temperature"])
        if temp_f is not None:
            payload["temperature_f"] = temp_f
    for cast in payload.get("casts") or []:
        for ckey, fkey in (("day_temp", "day_temp_f"), ("night_temp", "night_temp_f")):
            if cast.get(ckey):
                temp_f = _f_str(cast[ckey])
                if temp_f is not None:
                    cast[fkey] = temp_f
    return payload


def upsert_weather(session, report: dict, *, source: str = WEATHER_SOURCE) -> str:
    """latest-wins 落库；返回 "updated" | "inserted"。"""
    existing = (
        session.query(WeatherReport)
        .filter_by(source=source, adcode=report["adcode"], kind=report["kind"])
        .one_or_none()
    )
    row = existing or WeatherReport(
        id=uuid.uuid4(), source=source, adcode=report["adcode"], kind=report["kind"]
    )
    row.city = report.get("city") or row.city or ""
    row.report_time = parse_report_time(report.get("report_time"))
    row.payload = _with_fahrenheit(report.get("payload"))
    # 每次刷新盖最新时间戳——server_default 只在 INSERT 生效，UPDATE 不触发；
    # 漏掉会让 fetched_at 停在首次入库时间，7 天清理会误删活跃行
    row.fetched_at = datetime.utcnow()
    if existing is None:
        session.add(row)
    return "updated" if existing is not None else "inserted"


def trip_cities(session) -> list[str]:
    """行程涉及城市去重（行程中心 + 行程域），供默认抓取范围。

    统一去「市」后缀——同城的「西安/西安市」算一城，省配额。
    """
    names = {n.removesuffix("市") for n in _raw_trip_city_names(session) if n}
    return sorted(names)


def _raw_trip_city_names(session) -> list[str]:
    names: list[str] = []
    for (cities,) in session.query(Itinerary.cities).all():
        names.extend(cities or [])
    for (city,) in session.query(ItineraryDay.base_city).distinct().all():
        names.append(city)
    for (city,) in session.query(TripItem.city).distinct().all():
        names.append(city)
    return names


def store_cities(store, trip_item_svc) -> list[str]:
    """H5 状态域（行程记录 + 行程中心条目）涉及城市——与 trip_cities
    （PG 三表）并集后作为默认抓取范围：H5 行程实际落状态库（SQLite，
    2026-10 起迁 PG），不在 PG 三表里，只查 trip_cities 永远为空
    （2026-10-25 排障）。store 侧取 plan.cities + days[].base_city
    （ItineraryStore.list_all），条目侧取 list_groups(None) 各组 city；
    去「市」后缀去重，口径与 trip_cities 一致。"""
    names: list[str] = []
    for record in store.list_all():
        names.extend(record.plan.cities or [])
        for day in record.plan.days:
            names.append(day.base_city)
    for group in trip_item_svc.list_groups(None).values():
        for item in group:
            names.append(item.get("city"))
    return sorted({n.removesuffix("市") for n in names if n})


def daily_weather_text(
    session_factory, city: str, date_iso: str
) -> tuple[str, str] | None:
    """行程日双窗天气文本（(白天, 夜间)；雨天分窗判定用）。

    规划雨天感知（2026-10-30 用户拍板：有雨自动排室内，不问用户）的
    唯一读口：forecast（百度 0-7 天）优先、forecast14（Open-Meteo
    14 天）兜底，按 cast.date == date_iso 精确匹配。三轮拍板
    （2026-10-30 深夜）：白天/夜间两个时间窗分开回——白天雨管白天
    露天点，夜间雨只影响游船观景/夜游等夜间露天活动；无数据返回
    None（调用方视为未知，不阻断规划）。纯 DB 读零外呼——新鲜度由
    每日 08:10 管线保证。
    """
    adcode = city_to_adcode(city)
    if not adcode or not date_iso:
        return None
    try:
        with session_factory() as session:
            rows = (
                session.query(WeatherReport)
                .filter(WeatherReport.adcode == adcode)
                .all()
            )
    except Exception:
        logger.warning(
            "weather: daily_weather_text read failed city=%s date=%s",
            city,
            date_iso,
            exc_info=True,
        )
        return None
    ordered = sorted(rows, key=lambda r: 0 if r.kind == "forecast" else 1)
    for row in ordered:
        payload = row.payload if isinstance(row.payload, dict) else {}
        for cast in payload.get("casts") or []:
            if isinstance(cast, dict) and cast.get("date") == date_iso:
                day = str(cast.get("day_weather") or "")
                night = str(cast.get("night_weather") or "")
                return day, night
    return None


async def fetch_and_store(
    session_factory,
    client,
    cities: list[str],
    *,
    kinds: tuple[str, ...] = ("live", "forecast"),
    source: str | None = None,
) -> dict:
    """逐城拉取实况+预报并 latest-wins 落库；失败降级为 warning 不中断。"""
    stats = {
        "cities": 0,
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    for city in cities:
        adcode = city_to_adcode(city)
        if not adcode:
            stats["skipped"] += 1
            logger.warning("weather: 未收录城市，跳过: %s", city)
            continue
        stats["cities"] += 1
        for kind in kinds:
            extensions = "base" if kind == "live" else "all"
            try:
                report = await client.get_weather(adcode, extensions=extensions)
            except Exception as exc:  # AmapError/timeout/网络，逐城降级
                stats["errors"] += 1
                logger.warning("weather: %s %s 拉取失败: %s", city, kind, exc)
                continue
            if not report:
                stats["skipped"] += 1
                logger.warning("weather: %s %s 无数据行，跳过", city, kind)
                continue
            report["adcode"] = report.get("adcode") or adcode
            with session_factory() as session:
                action = (
                    upsert_weather(session, report, source=source)
                    if source
                    else upsert_weather(session, report)
                )
                session.commit()
            stats["fetched"] += 1
            stats[action] += 1
    return stats
