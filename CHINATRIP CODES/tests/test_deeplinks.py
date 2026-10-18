# -*- coding: utf-8 -*-
"""出租/自驾 deeplink 组装测试（设计 v2.2 §6.13）。

核心回归：所有产出 URL 不得含 "key="（铁律：key 永不进客户端）。
"""

import pytest

from app.services.deeplinks import compose_deeplink

NAME = "北京天安门"
NAME_ENC = "%E5%8C%97%E4%BA%AC%E5%A4%A9%E5%AE%89%E9%97%A8"  # quote(NAME, safe="")
LON, LAT = 116.397428, 39.90923


def _all_urls(result: dict) -> list:
    return [v for v in result.values() if isinstance(v, str) and v != result["source"]]


class TestTaxi:
    def test_prefix(self):
        r = compose_deeplink("taxi", NAME, LON, LAT)
        assert r["app_deeplink"].startswith("amapuri://drive/taxi/")

    def test_dlon_before_dlat(self):
        r = compose_deeplink("taxi", NAME, LON, LAT)
        url = r["app_deeplink"]
        assert url.index("dlon=") < url.index("dlat=")
        assert f"dlon={LON}" in url and f"dlat={LAT}" in url

    def test_chinese_name_encoded(self):
        r = compose_deeplink("taxi", NAME, LON, LAT)
        assert f"dname={NAME_ENC}" in r["app_deeplink"]
        assert "%E5%8C%97" in r["app_deeplink"]  # "北"
        assert NAME not in r["app_deeplink"]

    def test_web_fallback_amap(self):
        # 滴滴旧 H5(webapp/driverDepart)已 404；网页无法叫车 → 高德路线页
        r = compose_deeplink("taxi", NAME, LON, LAT)
        fb = r["web_fallback"]
        assert fb.startswith("https://uri.amap.com/navigation")
        assert f"to={LON},{LAT},{NAME_ENC}" in fb
        assert "mode=car" in fb
        assert "callnative=1" in fb
        assert NAME not in fb

    def test_mode_and_source(self):
        r = compose_deeplink("taxi", NAME, LON, LAT)
        assert r["mode"] == "taxi"
        assert r["source"] == "chinatrip"


class TestDriving:
    def test_params(self):
        url = compose_deeplink("driving", NAME, LON, LAT)["app_deeplink"]
        assert url.startswith("amapuri://route/plan/")
        assert "sourceApplication=chinatrip" in url
        assert url.rstrip("0").endswith("t=") or "&t=0" in url
        assert "dev=0" in url
        assert url.index("dlon=") < url.index("dlat=")

    def test_web_fallback_amap_navigation(self):
        fb = compose_deeplink("driving", NAME, LON, LAT)["web_fallback"]
        assert fb.startswith("https://uri.amap.com/navigation")
        assert f"to={LON},{LAT},{NAME_ENC}" in fb
        assert "mode=car" in fb
        assert "coordinate=gaode" in fb
        assert "callnative=1" in fb
        assert NAME not in fb

    def test_ios_alternative_apple_maps(self):
        alt = compose_deeplink("driving", NAME, LON, LAT)["ios_alternative"]
        assert alt.startswith("https://maps.apple.com/")
        assert f"dname={NAME_ENC}" in alt
        assert f"dlat={LAT}" in alt and f"dlon={LON}" in alt
        assert "dirflg=r" in alt

    def test_mode_and_source(self):
        r = compose_deeplink("driving", NAME, LON, LAT)
        assert r["mode"] == "driving"
        assert r["source"] == "chinatrip"


class TestNoKeyLeak:
    """铁律回归：deeplink 出现 key= 即事故。"""

    @pytest.mark.parametrize("mode", ["taxi", "driving"])
    def test_no_key_in_any_url(self, mode):
        r = compose_deeplink(mode, NAME, LON, LAT)
        for url in _all_urls(r):
            assert "key=" not in url


class TestValidation:
    def test_bad_mode(self):
        with pytest.raises(ValueError):
            compose_deeplink("walk", NAME, LON, LAT)

    def test_lon_out_of_range(self):
        with pytest.raises(ValueError):
            compose_deeplink("taxi", NAME, 200.0, LAT)

    def test_lat_nan(self):
        with pytest.raises(ValueError):
            compose_deeplink("taxi", NAME, float("nan"), LAT)

    def test_empty_name(self):
        with pytest.raises(ValueError):
            compose_deeplink("taxi", "   ", LON, LAT)


class TestBoundary:
    def test_china_corner_legal(self):
        r = compose_deeplink("taxi", NAME, 73.0, 54.0)
        assert "dlon=73.0" in r["app_deeplink"]
        r2 = compose_deeplink("driving", NAME, 136.0, 3.0)
        assert r2["mode"] == "driving"
