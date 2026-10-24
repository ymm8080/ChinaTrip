"""城市天气库（DESIGN §4.1 参考数据域 / §6.2 矩阵行：高德天气 API）。

数据源：高德 /v3/weather/weatherInfo（上游 = 中国气象局；按 adcode 查询，
与 POI 库同键）。上游时机：实况每小时更新、预报每日约 8/11/18 时三次，
本侧作业紧跟其后拉取（每日 08:10/11:10/18:10）。个人 key 免费额度约
100 次/日（以高德控制台为准）——每城每次 2 次调用（实况+预报），
40 城全量×3 次/日 = 240 次/日会超配额，故默认只抓行程涉及城市，
--all 才全量。

写入语义 latest-wins：每 (source, adcode, kind) 仅一行 upsert，
report_time 保留高德侧数据时间，不堆历史。幂等可重跑。
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
}


def city_to_adcode(city: str | None) -> str | None:
    """城市名 → adcode；「市」后缀容错；6 位数字直接视为 adcode 透传。"""
    if not city:
        return None
    s = city.strip()
    if s.isdigit() and len(s) == 6:
        return s
    return CITY_ADCODES.get(s.removesuffix("市"))


def parse_report_time(value: str | None) -> datetime | None:
    """高德 reporttime 形如 "2026-10-23 08:12:36"（北京时间，naive）。"""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


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
    row.payload = report.get("payload")
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


async def fetch_and_store(
    session_factory,
    client,
    cities: list[str],
    *,
    kinds: tuple[str, ...] = ("live", "forecast"),
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
                action = upsert_weather(session, report)
                session.commit()
            stats["fetched"] += 1
            stats[action] += 1
    return stats
