"""poi_classify 词典行为锁定（含 2026-10-25 扩容词与类别地板表）。"""

from types import SimpleNamespace

from app.services.poi_classify import classify as _classify
from app.services.poi_classify import duration_upgradable


def _c(name, cat=None):
    return _classify(name, cat)


def test_indoor_hints_first_hit_wins():
    cat, indoor, rain_ok, floor = _c("北京故宫博物院")
    assert (cat, indoor, rain_ok) == ("museum", True, True)
    assert floor == 120


def test_theme_park_hints():
    for name in ("武汉野生动物王国", "上海迪士尼乐园", "北京动物园"):
        cat, indoor, rain_ok, floor = _c(name)
        assert cat == "theme_park", name
        assert floor == 240


def test_heritage_hints():
    for name in ("杭州孔庙", "雨花台烈士陵园", "禹稷行宫", "张裕爱斐堡酒庄"):
        cat, indoor, rain_ok, floor = _c(name)
        assert cat == "attraction", name
        assert floor == 90


def test_cave_hints_rain_ok():
    cat, indoor, rain_ok, floor = _c("莫高窟")
    assert (cat, indoor, rain_ok, floor) == ("nature", False, True, 180)


def test_outdoor_before_park():
    cat, _, _, floor = _c("西岭雪山")
    assert cat == "nature" and floor == 180


def test_park_hints():
    cat, indoor, _, floor = _c("苏州园林曲园")
    assert cat == "park" and floor == 90


def test_urban_hints_extended():
    for name in ("南滨路", "意大利风情街", "苏州古运河游船(相门码头)"):
        cat, _, _, floor = _c(name)
        assert cat == "attraction", name
        assert floor == 90


def test_second_pass_hints():
    cases = {
        "成都融创文旅城": "theme_park",
        "晴川阁": "attraction",
        "媽閣廟": "attraction",
        "桦墅村": "attraction",
        "森林小火车站": "attraction",
        "七星湾游艇会": "attraction",
    }
    for name, want in cases.items():
        cat, _, _, _ = _c(name)
        assert cat == want, name


def test_low_confidence_stays_none():
    cat, indoor, rain_ok, floor = _c("昆曲茶社")
    assert cat is None and indoor is None and rain_ok is None and floor is None


def test_existing_category_short_circuits():
    cat, indoor, _, floor = _c("某某馆", "theme_park")
    assert cat == "theme_park" and indoor is False and floor == 240


def test_extended_category_floors():
    """受控类别（seed 层 normalize_category 产物）也直接有地板。"""
    cases = {
        ("大昭寺", "temple"): ("temple", 60),
        ("北京海洋馆西郊分馆", "zoo"): ("zoo", 180),
        ("乌镇", "ancient_town"): ("ancient_town", 180),
        ("圣约瑟夫教堂", "church"): ("church", 30),
        ("某某遗址公园", "ruins"): ("ruins", 90),
        ("某某艺廊", "gallery"): ("gallery", 60),
    }
    for (name, cat_in), (want_cat, want_floor) in cases.items():
        cat, _, _, floor = _c(name, cat_in)
        assert cat == want_cat and floor == want_floor, name


def test_other_category_no_floor():
    cat, indoor, rain_ok, floor = _c("某某综合体", "other")
    assert cat == "other" and indoor is None and rain_ok is None and floor is None


def test_duration_upgradable_semantics():
    """真值源升级闸：空值/启发式可写，其它真值不互覆（2026-10-25 拍板）。"""
    assert duration_upgradable(
        SimpleNamespace(suggested_duration_min=None, duration_source=None)
    )
    assert duration_upgradable(
        SimpleNamespace(suggested_duration_min=240, duration_source="heuristic")
    )
    assert not duration_upgradable(
        SimpleNamespace(suggested_duration_min=120, duration_source="ctrip")
    )
    assert not duration_upgradable(
        SimpleNamespace(suggested_duration_min=120, duration_source="qunar")
    )
