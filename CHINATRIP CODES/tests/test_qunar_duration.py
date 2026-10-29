"""enrich_qunar_duration 离线单测：时长解析/名字变体/写库升级语义/slug 表。

纯离线（FakeSession 模式对齐 tests/test_poi_seed.py），绝不连网连库；
网络层不在本文件覆盖范围（真库小样由作业 CLI 自验）。
"""

from uuid import uuid4

from app.jobs.enrich_qunar_duration import (
    QUNAR_CITY_SLUGS,
    _city_page_ok,
    _lookup,
    _name_variants,
    _write_row,
    build_name_index,
    extract_duration_text,
    parse_duration_minutes,
    parse_list_page,
)
from app.models import Poi

# --- 时长解析 ---------------------------------------------------------------


def test_parse_duration_range_hours():
    assert parse_duration_minutes("4-6小时") == 300
    assert parse_duration_minutes("3-5小时") == 240
    assert parse_duration_minutes("2-3小时") == 150


def test_parse_duration_decimal_range():
    assert parse_duration_minutes("2-3.5小时") == 165
    assert parse_duration_minutes("0.5-1小时") == 45


def test_parse_duration_days_range():
    # 「天」按 8 小时=480 分算，取区间中值
    assert parse_duration_minutes("0.5-1天") == 360
    assert parse_duration_minutes("1天") == 480
    assert parse_duration_minutes("0.5天") == 240


def test_parse_duration_single_value():
    assert parse_duration_minutes("1小时") == 60
    assert parse_duration_minutes("2.5小时") == 150
    assert parse_duration_minutes("45分钟") == 45


def test_parse_duration_missing_forms():
    assert parse_duration_minutes("暂无") is None
    assert parse_duration_minutes("") is None
    assert parse_duration_minutes(None) is None
    assert parse_duration_minutes("半天") is None


def test_parse_duration_gate_out_of_range():
    assert parse_duration_minutes("12小时") is None  # 720 > 600
    assert parse_duration_minutes("0.1小时") is None  # 6 < 15
    assert parse_duration_minutes("2天") is None  # 960 > 600


def test_extract_duration_text_real_shape():
    html = (
        '<div class="sg-kv"><div class="item">'
        '<span class="k">建议用时</span><span class="v">2-3小时</span>'
        "</div></div>"
    )
    assert extract_duration_text(html) == "2-3小时"
    assert parse_duration_minutes(extract_duration_text(html)) == 150


def test_extract_duration_text_tolerant_and_missing():
    tolerant = '建议用时 </span>  <span class="v">1小时</span>'
    assert extract_duration_text(tolerant) == "1小时"
    assert extract_duration_text("<html>建议游玩时间</html>") is None
    assert extract_duration_text("") is None
    no_data = '建议用时</span><span class="v">暂无</span>'
    assert extract_duration_text(no_data) == "暂无"
    assert parse_duration_minutes(extract_duration_text(no_data)) is None


# --- 名字变体匹配 -----------------------------------------------------------


def test_name_variants_prefix_strip():
    vs = _name_variants("酉阳土家族苗族自治县桃花源旅游景区")
    assert "桃花源旅游景区" in vs
    assert "桃花源" in vs
    assert vs[0] == "酉阳土家族苗族自治县桃花源旅游景区"


def test_name_variants_suffix_strip():
    vs = _name_variants("武汉东湖风景区")
    assert "武汉东湖" in vs
    assert _name_variants("黄鹤楼") == ["黄鹤楼"]


def test_name_match_suffix_and_miss():
    index = build_name_index([("黄鹤楼公园", "11"), ("武汉长江大桥", "22")])
    assert _lookup(index, "黄鹤楼") == "11"  # list 名剥尾缀后放行
    assert _lookup(index, "武汉长江大桥") == "22"
    assert _lookup(index, "武汉大学") is None  # 完全不同不匹配


def test_name_match_prefix_admin():
    index = build_name_index([("黄鹤楼", "11")])
    assert _lookup(index, "武汉市黄鹤楼") == "11"  # 库名剥前缀行政区后命中


# --- list 页解析 / 串城守门 --------------------------------------------------


_LIST_HTML = (
    '<script type="application/ld+json">{"@type":"ItemList",'
    '"name":"武汉景点","numberOfItems":10,'
    '"spatialCoverage":{"@type":"City","name":"武汉",'
    '"address":{"@type":"PostalAddress","addressCountry":"CN",'
    '"addressLocality":"武汉"}},'
    '"itemListElement":['
    '{"@type":"ListItem","position":1,"name":"黄鹤楼",'
    '"url":"https://sight.qunar.com/898602836"},'
    '{"@type":"ListItem","position":2,"name":"武汉动物园",'
    '"url":"https://sight.qunar.com/3304877313"},'
    '{"@type":"ListItem","position":3,"name":"黄鹤楼",'
    '"url":"https://sight.qunar.com/898602836"}]}</script>'
)


def test_parse_list_page_items_and_locality():
    items, locality = parse_list_page(_LIST_HTML)
    assert items == [("黄鹤楼", "898602836"), ("武汉动物园", "3304877313")]
    assert locality == "武汉"


def test_parse_list_page_empty():
    assert parse_list_page("<html></html>") == ([], None)


def test_city_page_ok_slug_url_or_locality():
    ok_url = "https://sight.qunar.com/list?city=wuhan&page=1"
    assert _city_page_ok("wuhan", ok_url, "武汉", "武汉")
    # 错误 slug 302 到 beijing 默认列表 → 串城拒收
    assert not _city_page_ok(
        "zzznotacity",
        "https://sight.qunar.com/list?city=beijing&page=1",
        "北京",
        "武汉",
    )
    # slug 被规范化跳转但 ItemList 城市名对得上 → 放行
    assert _city_page_ok("wuhan2", ok_url, "武汉", "武汉")
    # locality 带「市」后缀也能对上（去后缀归一）
    assert _city_page_ok("x", "https://other.example/", "武汉市", "武汉")


# --- 写库升级语义（FakeSession 模式，参考 tests/test_poi_seed.py）------------


class FakeSession:
    """内存会话：只实现 _write_row 用到的 get/commit + 上下文协议。"""

    def __init__(self, rows):
        self.rows = {r.id: r for r in rows}
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, _model, pk):
        return self.rows.get(pk)

    def commit(self):
        self.commits += 1


class FakeFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


def _poi(duration, source):
    return Poi(
        id=uuid4(),
        source="osm",
        source_poi_id=uuid4().hex[:8],
        city="武汉",
        name_zh="黄鹤楼",
        status="active",
        suggested_duration_min=duration,
        duration_source=source,
    )


def test_write_row_null_fills():
    row = _poi(None, None)
    factory = FakeFactory(FakeSession([row]))
    assert _write_row(factory, row.id, 150) is True
    assert row.suggested_duration_min == 150
    assert row.duration_source == "qunar"
    assert factory.session.commits == 1


def test_write_row_heuristic_overwrites():
    row = _poi(90, "heuristic")
    factory = FakeFactory(FakeSession([row]))
    assert _write_row(factory, row.id, 150) is True
    assert row.suggested_duration_min == 150  # 真值覆盖 heuristic 地板
    assert row.duration_source == "qunar"


def test_write_row_ctrip_protected():
    row = _poi(120, "ctrip")
    factory = FakeFactory(FakeSession([row]))
    assert _write_row(factory, row.id, 150) is False
    assert row.suggested_duration_min == 120  # 既有真值不动
    assert row.duration_source == "ctrip"
    assert factory.session.commits == 0


def test_write_row_missing_poi():
    factory = FakeFactory(FakeSession([]))
    assert _write_row(factory, uuid4(), 150) is False


# --- slug 映射表 ------------------------------------------------------------


def test_slug_table_unique_values():
    values = list(QUNAR_CITY_SLUGS.values())
    assert len(set(values)) == len(values)  # 无重复值（泰州/抚州/宜春类已剔除）


def test_slug_table_identity_samples():
    assert QUNAR_CITY_SLUGS["北京"] == "beijing"
    assert QUNAR_CITY_SLUGS["武汉"] == "wuhan"
    assert QUNAR_CITY_SLUGS["重庆"] == "chongqing"
    assert QUNAR_CITY_SLUGS["西安"] == "xian"
    assert len(QUNAR_CITY_SLUGS) >= 100  # 覆盖真库普查绝大多数城市
