"""城市注册面一致性锁：plan.KNOWN_CITIES 与 poi_city.canonical 全集不得再分叉。

2026-11-02 拍板「规划宇宙 226→411 扩表」的批次 3 收口。两套注册表分叉曾造成
「硬骨头 515」名单层清障后被池外城市闸挡住（gap 185 城含石家庄/咸阳/烟台）；
本锁保证：canonical 真源演进（GB/T 索引新增地级）时必须同步 KNOWN_CITIES。
"""

from app.services.agent.plan import KNOWN_CITIES
from app.services.poi_city import known_cities
from app.services.weather import CITY_ADCODES
from app.services.weather_open_meteo import CITY_COORDS


def test_known_cities_equals_canonical_universe():
    assert set(KNOWN_CITIES) == set(known_cities())


def test_weather_adcode_cities_are_registered():
    # 气象局源城市必须已在规划宇宙内，否则用户可规划城市拿不到天气
    assert set(CITY_ADCODES) <= set(KNOWN_CITIES)


def test_om_coord_cities_are_registered():
    # Open-Meteo 源城市同理（无 adcode 城退化为仅 OM 源，见 weather.py 批次注释）
    assert set(CITY_COORDS) <= set(KNOWN_CITIES)


def test_expansion_unlocks_hard_bone_gap_cities():
    # backlog #4 点名的 515 硬骨头 gap 城市样例（国保/名村/风景区长尾所在）
    for city in ("石家庄", "咸阳", "烟台", "汉中", "榆林", "河池"):
        assert city in KNOWN_CITIES


def test_coord_pairs_within_china_bbox():
    for city, (lat, lon) in CITY_COORDS.items():
        assert 3 < lat < 54 and 73 < lon < 136, city
