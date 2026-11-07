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


def test_show_hints_beat_museum_20261107():
    """2026-11-07 拍板：SHOW/ENTERTAINMENT 优先级大于 MUSEUM。"""
    cat, indoor, rain_ok, floor = _c("梅花剧社·非遗川剧变脸")
    assert (cat, indoor, rain_ok, floor) == ("entertainment", True, True, 80)


def test_show_hint_overrides_museum_hint():
    cat, indoor, rain_ok, _ = _c("非遗博物馆小剧场")
    assert (cat, indoor, rain_ok) == ("entertainment", True, True)


def test_show_hints_venues():
    for name in ("四川省川剧院", "湖广会馆戏楼", "梨园剧场", "茶馆相声演出"):
        cat, indoor, rain_ok, floor = _c(name)
        assert (cat, indoor, rain_ok, floor) == ("entertainment", True, True, 80), name


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


def test_heritage_hints_20261106_extension():
    """殿/王府 → attraction；古城 → attraction（城市人文）。"""
    for name in ("呼和浩特和硕恪靖公主府王府", "叶赫王府", "即墨古城"):
        cat, indoor, rain_ok, floor = _c(name)
        assert cat == "attraction", name


def test_scenic_mark_bare_mingshengqu():
    """裸「名胜区」（无风景/景区前缀）归 scenic 口径 nature（对齐 scenic 源）。"""
    cat, indoor, rain_ok, floor = _c("昆明市金殿名胜区")
    assert (cat, indoor) == ("nature", False)
    assert floor == 180  # 市区档（无县/镇等郊野标记）


def test_cave_hints_rain_ok():
    cat, indoor, rain_ok, floor = _c("莫高窟")
    assert (cat, indoor, rain_ok, floor) == ("nature", False, True, 180)


def test_outdoor_before_park():
    cat, _, _, floor = _c("西岭雪山")
    assert cat == "nature" and floor == 180


def test_park_hints():
    cat, indoor, _, floor = _c("苏州园林曲园")
    assert cat == "park" and floor == 90


def test_accommodation_names_guard_to_hotel():
    """2026-10-31 清洗拍板：名称含住宿词一律 hotel，优先于裸「园」hint
    与上游类别（桔子水晶北京朝阳公园酒店 曾被误归 park 污染公园池）。"""
    cases = (
        "桔子水晶北京朝阳公园酒店",
        "南京竹官园宾馆",
        "隐栖堂美学生活酒店(宽窄巷子人民公园地铁站店)",
        "杭州余杭温德姆花园酒店",
        "全季酒店",
        "老门东客栈",
    )
    for name in cases:
        cat, indoor, rain_ok, floor = _c(name)
        assert cat == "hotel", name
        assert indoor is True and floor is None, name
    # 上游误标 park/attraction 也被名称证据盖掉
    for cat_in in ("park", "attraction", "garden"):
        cat, indoor, _, floor = _c("桔子水晶北京朝阳公园酒店", cat_in)
        assert cat == "hotel" and floor is None, cat_in
    # 非住宿公园不受守卫影响
    cat, _, _, floor = _c("朝阳公园")
    assert cat == "park" and floor == 90


def test_is_accommodation_tokens():
    from app.services.poi_classify import is_accommodation

    assert is_accommodation("北京国贸潘家园亚朵酒店")
    assert is_accommodation("檀香花园酒店(茶店子客运站地铁店)")
    assert is_accommodation("拾穗花园民宿")
    assert is_accommodation("云颐自在酒店公寓")
    assert is_accommodation("老宅客栈")
    assert not is_accommodation("北海公园")
    assert not is_accommodation("苏州园林曲园")
    assert not is_accommodation("")
    # 度假村歧义不进守卫（温泉/景区度假村常即目的地本身）
    assert not is_accommodation("南温泉度假村")


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


def test_scenic_area_urban_180():
    """2026-10-31 二次拍板：市区风景区 180——名称无城外行政标记按市区档。"""
    for name in ("黄山风景区", "东湖生态旅游风景区", "漓江旅游区", "乐山大佛景区"):
        cat, indoor, rain_ok, floor = _c(name)
        assert cat == "nature" and indoor is False and rain_ok is False, name
        assert floor == 180, name


def test_scenic_area_suburb_240_by_address():
    """地址命中县/镇/乡等城外标记 → 城市外档 240。"""
    for name, addr in (
        ("黄山风景区", "安徽省黄山市黄山区汤口镇"),
        ("四面山景区", "重庆市江津区四面山镇"),
        ("玉龙雪山景区", "云南省丽江市玉龙纳西族自治县大具乡"),
        ("淀山湖风景区", "上海市青浦区朱家角镇彩虹桥"),
    ):
        cat, _, _, floor = _classify(name, None, addr)
        assert cat == "nature" and floor == 240, name


def test_scenic_area_suburb_240_by_name():
    """名称自带县标（无地址）即可判城市外档。"""
    for name in ("婺源县江湾景区", "涞源县白石山景区", "上杭县古田旅游区"):
        cat, _, _, floor = _c(name)
        assert cat == "nature" and floor == 240, name


def test_scenic_mark_lifts_category_floor():
    """已有类别行名称带景区标记：地板抬到对应档，类别与属性不覆盖。"""
    cases = (
        ("灵隐飞来峰景区", "temple", None, 180),
        ("某某陵园风景区", "memorial", None, 180),
        ("缙云仙都景区", "attraction", "浙江省丽水市缙云县壶镇镇", 240),
    )
    for name, cat_in, addr, want in cases:
        cat, _, _, floor = _classify(name, cat_in, addr)
        assert cat == cat_in and floor == want, name


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


# --- 名×城定读覆盖（2026-11-07 拍板） -----------------------------------


def test_name_city_override_renmin_park_tea():
    """成都人民公园 → tea_experience（雨日可游，60min 地板）；city 未传
    且无上游类别时仍走名称推断（park）。"""
    cat, indoor, rain_ok, floor = _classify("人民公园", "attraction", city="成都")
    assert (cat, indoor, rain_ok, floor) == ("tea_experience", None, True, 60)
    cat2, indoor2, rain_ok2, _f2 = _classify("人民公园", None)
    assert (cat2, indoor2, rain_ok2) == ("park", False, None)


def test_name_city_override_citywalk_family():
    """成都四街一坊 + 武侯祠·锦里 → citywalk（非室内，120 地板）；上游
    类别（attraction/historic）被覆盖。"""
    for name, up in (
        ("宽窄巷子", "attraction"),
        ("春熙路", "attraction"),
        ("西蜀第一街牌坊", "attraction"),
        ("锦里古街", "attraction"),
        ("武侯祠·锦里", "historic"),
    ):
        cat, indoor, rain_ok, floor = _classify(name, up, city="成都")
        assert (cat, indoor, rain_ok, floor) == ("citywalk", False, None, 120), name


def test_name_city_override_city_suffix_and_other_city():
    """「成都市」后缀剥除命中覆盖；上海人民公园不命中覆盖走 park 推断。"""
    cat, *_ = _classify("人民公园", "attraction", city="成都市")
    assert cat == "tea_experience"
    cat2, *_ = _classify("人民公园", None, city="上海")
    assert cat2 == "park"
