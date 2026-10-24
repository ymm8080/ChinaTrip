"""14 天预报源 Open-Meteo（用户指定 TREK 方案的第二轨；DESIGN §6.2）。

高德免费接口只给 3 天预报，覆盖不到「未来 14 天」的产品需求；Open-Meteo
免 key、forecast_days 上限 16、逐日数据覆盖中国（模式推算，精度低于高德
的气象局实况口径——所以 0-3 天仍以高德为准，4-14 天用本源补齐）。

无配额压力（免费档 1 万次/日）：40 城每次运行 40 次调用，可随三班调度
每次全量。写入复用 weather_reports 表 latest-wins：
source="open-meteo"、kind="forecast14"、payload 与高德 forecast 同构
（casts 数组，date/day_weather/day_temp/night_temp），前端按日期匹配时
两源无差别。

purge_stale：latest-wins 不堆历史，但已不再抓取的城市行会滞留——按用户
口径 fetched_at 超过 7 天的行删除。
"""

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete

from app.models import WeatherReport

logger = logging.getLogger(__name__)

OPEN_METEO_SOURCE = "open-meteo"
FORECAST14_KIND = "forecast14"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
STALE_DAYS = 7

# 与 app.services.weather.CITY_ADCODES 同一批 40 城（市中心坐标，WGS-84）
CITY_COORDS: dict[str, tuple[float, float]] = {
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "杭州": (30.2741, 120.1551),
    "苏州": (31.2989, 120.5853),
    "南京": (32.0603, 118.7969),
    "西安": (34.3416, 108.9398),
    "成都": (30.5728, 104.0668),
    "重庆": (29.5630, 106.5516),
    "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579),
    "天津": (39.3434, 117.3616),
    "武汉": (30.5928, 114.3055),
    "长沙": (28.2282, 112.9388),
    "厦门": (24.4798, 118.0894),
    "青岛": (36.0671, 120.3826),
    "大连": (38.9140, 121.6147),
    "三亚": (18.2528, 109.5119),
    "丽江": (26.8721, 100.2300),
    "桂林": (25.2742, 110.2902),
    "洛阳": (34.6197, 112.4540),
    "敦煌": (40.1421, 94.6620),
    "兰州": (36.0611, 103.8343),
    "拉萨": (29.6520, 91.1721),
    "昆明": (24.8801, 102.8329),
    "大理": (25.6065, 100.2676),
    "张家界": (29.1170, 110.4793),
    "黄山": (29.7147, 118.3376),
    "无锡": (31.4912, 120.3119),
    "绍兴": (30.0300, 120.5804),
    "嘉兴": (30.7464, 120.7550),
    "舟山": (29.9853, 122.2072),
    "哈尔滨": (45.8038, 126.5349),
    "沈阳": (41.8057, 123.4315),
    "长春": (43.8171, 125.3245),
    "郑州": (34.7466, 113.6254),
    "济南": (36.6512, 117.1201),
    "福州": (26.0745, 119.2965),
    "泉州": (24.8741, 118.6757),
    "威海": (37.5128, 122.1201),
    "珠海": (22.2707, 113.5767),
}

# WMO 4677 天气码 → 高德风格中文文本（前端 wxIcon 直接复用）
WMO_TEXT: dict[int, str] = {
    0: "晴",
    1: "晴",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾",
    51: "小雨",
    53: "小雨",
    55: "小雨",
    56: "冻雨",
    57: "冻雨",
    66: "冻雨",
    67: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "小雪",
    80: "小雨",
    81: "中雨",
    82: "大雨",
    85: "小雪",
    86: "中雪",
    95: "雷阵雨",
    96: "雷阵雨",
    99: "雷阵雨",
}


def wmo_text(code) -> str:
    try:
        return WMO_TEXT.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def _temp_str(values: list, i: int) -> str:
    """浮点温度 → 整数字符串（与高德口径一致）；缺值/越界返回空串。"""
    if i < len(values) and values[i] is not None:
        return str(round(float(values[i])))
    return ""


def normalize_daily(city: str, adcode: str, data: dict) -> dict:
    """Open-Meteo 响应 → weather_reports 报告（payload 与高德 forecast 同构）。"""
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    codes = daily.get("weather_code") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    casts = [
        {
            "date": d,
            "day_weather": wmo_text(c),
            "day_temp": _temp_str(tmax, i),
            "night_temp": _temp_str(tmin, i),
        }
        for i, (d, c) in enumerate(zip(dates, codes))
    ]
    return {
        "kind": FORECAST14_KIND,
        "city": city,
        "adcode": adcode,
        "report_time": None,  # Open-Meteo 响应不带上游生成时间
        "payload": {"city": city, "adcode": adcode, "casts": casts},
    }


async def fetch_forecast14(
    session_factory,
    cities: list[str],
    *,
    timeout_seconds: float = 15.0,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """逐城拉 14 天预报并 latest-wins 落库；逐城降级，失败不中断。

    client 可注入（测试 MockTransport）；缺省自建。
    """
    from app.services.weather import city_to_adcode, upsert_weather

    stats = {
        "cities": 0,
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    async with client or httpx.AsyncClient(timeout=timeout_seconds) as http:
        for city in cities:
            coords = CITY_COORDS.get(city.removesuffix("市"))
            adcode = city_to_adcode(city)
            if not coords or not adcode:
                stats["skipped"] += 1
                logger.warning("weather14: 未收录城市，跳过: %s", city)
                continue
            stats["cities"] += 1
            try:
                resp = await http.get(
                    OPEN_METEO_URL,
                    params={
                        "latitude": coords[0],
                        "longitude": coords[1],
                        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                        "forecast_days": 14,
                        "timezone": "Asia/Shanghai",
                    },
                )
                resp.raise_for_status()
                report = normalize_daily(city, adcode, resp.json())
            except Exception as exc:
                stats["errors"] += 1
                logger.warning("weather14: %s 拉取失败: %s", city, exc)
                continue
            if not report["payload"]["casts"]:
                stats["skipped"] += 1
                continue
            with session_factory() as session:
                action = upsert_weather(session, report, source=OPEN_METEO_SOURCE)
                session.commit()
            stats["fetched"] += 1
            stats[action] += 1
    return stats


async def purge_stale(session_factory, *, days: int = STALE_DAYS) -> int:
    """删除 fetched_at 早于 N 天的行（不再抓取的城市滞留数据）；返回删除数。"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    with session_factory() as session:
        result = session.execute(
            delete(WeatherReport).where(
                WeatherReport.fetched_at.is_not(None),
                WeatherReport.fetched_at < cutoff,
            )
        )
        session.commit()
        return getattr(result, "rowcount", 0) or 0
