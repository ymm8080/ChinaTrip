"""poi_seed 骨架导入存储层测试（内存 FakeSession，不连真库）."""

from uuid import uuid4

from geoalchemy2.elements import WKTElement

from app.models import Poi, Restaurant
from app.services.coords import make_point
from app.services.poi_seed import mark_status, normalize_category, seed_upsert


class FakeSession:
    """内存会话：只实现 seed_upsert 用到的 query 链 + add/commit."""

    def __init__(self, rows=None, fail_on=None):
        self.rows = list(rows or [])  # 已持久化行
        self.added = []  # add() 过的对象（commit 后保留，便于断言）
        self.commits = 0
        self._fail_on = fail_on  # "query" | "commit"
        self._kw: dict = {}
        self._crit: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
        if self._fail_on == "query":
            raise RuntimeError("db down")
        self._kw = {}
        self._crit = []
        return self

    def filter_by(self, **kw):
        self._kw = kw
        return self

    def filter(self, *crit):
        self._crit = list(crit)
        return self

    def _crit_match(self, row):
        """评估简单等值表达式（col.key == param.value）。"""
        for c in self._crit:
            left, right = getattr(c, "left", None), getattr(c, "right", None)
            key = getattr(left, "key", None) if left is not None else None
            if key is None:
                return False
            if getattr(row, key, None) != getattr(right, "value", None):
                return False
        return True

    def one_or_none(self):
        for row in self.rows:
            if all(getattr(row, k, None) == v for k, v in self._kw.items()):
                return row
        return None

    def all(self):
        return [row for row in self.rows if self._crit_match(row)]

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        if self._fail_on == "commit":
            raise RuntimeError("db down")
        self.commits += 1
        self.rows.extend(self.added)


class FakeFactory:
    def __init__(self, session=None):
        self.session = session or FakeSession()

    def __call__(self):
        return self.session


def test_normalize_category_exact_tables():
    assert normalize_category(" 博物馆/纪念馆 ") == "museum"
    assert normalize_category("公园/广场") == "park"
    assert normalize_category("历史遗迹") == "historic"
    assert normalize_category("寺庙/教堂") == "temple"
    assert normalize_category("自然风光") == "nature"
    assert normalize_category("游乐园") == "theme_park"
    assert normalize_category("动物园/植物园") == "zoo"
    assert normalize_category("观景台/地标") == "viewpoint"
    assert normalize_category("文化村/古镇") == "ancient_town"
    assert normalize_category("其他") == "other"
    for osm in (
        "attraction",
        "museum",
        "gallery",
        "zoo",
        "theme_park",
        "viewpoint",
        "ruins",
        "castle",
        "memorial",
        "temple",
        "church",
        "park",
        "garden",
    ):
        assert normalize_category(osm) == osm


def test_normalize_category_contains_and_case():
    assert normalize_category("国家博物馆") == "museum"
    assert normalize_category("纪念馆") == "museum"
    assert normalize_category("海滨广场") == "park"
    assert normalize_category("Museum") == "museum"
    assert normalize_category("Theme_Park") == "theme_park"


def test_normalize_category_unmatched():
    assert normalize_category("购物中心") is None
    assert normalize_category("") is None
    assert normalize_category("   ") is None
    assert normalize_category(None) is None


def test_seed_upsert_creates_poi_row():
    factory = FakeFactory()
    out = seed_upsert(
        factory,
        Poi,
        source="chinatravel",
        source_poi_id="ct-1",
        city="重庆市",
        name_zh=" 洪崖洞 ",
        category="博物馆/纪念馆",
        lonlat=(106.578, 29.562),
        wgs84_lonlat=(106.571, 29.557),
        name_en=" Hongya Cave ",
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.city == "重庆"  # 去「市」后缀
    assert row.name_zh == "洪崖洞"
    assert row.name_en == "Hongya Cave"
    assert row.category == "museum"
    assert row.source == "chinatravel"
    assert row.source_poi_id == "ct-1"
    assert row.status == "active"
    assert row.origin == "chinatravel"  # 缺省 = source
    assert isinstance(row.location, WKTElement)
    assert isinstance(row.wgs84_location, WKTElement)
    assert row.location.srid == 4326


def test_seed_upsert_classifies_new_poi_at_insert():
    """2026-10-25 拍板：Poi 新行插入即分类，category/indoor/rain_ok+时长地板。"""
    factory = FakeFactory()
    out = seed_upsert(
        factory,
        Poi,
        source="osm",
        source_poi_id="n7",
        city="上海",
        name_zh="上海迪士尼乐园",
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.category == "theme_park"
    assert row.indoor is False
    assert row.rain_ok is False
    assert row.suggested_duration_min == 240
    assert row.duration_source == "heuristic"


def test_seed_upsert_normalized_category_gets_floor():
    """外部源给了类别（归一产物）也直接落属性+地板，不依赖名称关键词。"""
    factory = FakeFactory()
    out = seed_upsert(
        factory,
        Poi,
        source="chinatravel",
        source_poi_id="ct-9",
        city="成都",
        name_zh="成都大熊猫繁育研究基地",
        category="动物园/植物园",
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.category == "zoo"
    assert row.suggested_duration_min == 180
    assert row.duration_source == "heuristic"


def test_seed_upsert_low_confidence_name_stays_skeleton():
    """分类不出的名称不硬塞：地板/类别全空（清扫链后续兜底）。"""
    factory = FakeFactory()
    out = seed_upsert(
        factory, Poi, source="osm", source_poi_id="n8", city="苏州", name_zh="昆曲茶社"
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.category is None
    assert row.suggested_duration_min is None
    assert row.duration_source is None


def test_seed_upsert_restaurant_unaffected_by_classification():
    """Restaurant 无时长列：走 cuisine 映射，分类器不掺和。"""
    factory = FakeFactory()
    out = seed_upsert(
        factory,
        Restaurant,
        source="chinatravel",
        source_poi_id="r-9",
        city="成都市",
        name_zh="蜀九香",
        category="其他",
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.cuisine == "other"
    assert getattr(row, "suggested_duration_min", None) is None


def test_seed_upsert_restaurant_maps_to_cuisine():
    factory = FakeFactory()
    out = seed_upsert(
        factory,
        Restaurant,
        source="chinatravel",
        source_poi_id="r-1",
        city="成都市",
        name_zh="蜀九香",
        category="其他",
        origin="ct_backup",
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.city == "成都"
    assert row.cuisine == "other"  # Restaurant 无 category 列 → cuisine
    assert row.origin == "ct_backup"  # 显式 origin 优先


def test_seed_upsert_duplicate_exists_no_overwrite():
    existing = Poi(
        id=uuid4(),
        source="osm",
        source_poi_id="n1",
        city="北京",
        name_zh="旧名",
        status="inactive",
    )
    factory = FakeFactory(FakeSession(rows=[existing]))
    out = seed_upsert(
        factory,
        Poi,
        source="osm",
        source_poi_id="n1",
        city="上海市",
        name_zh="新名",
        category="博物馆",
        lonlat=(121.47, 31.23),
    )
    assert out == "exists"
    assert factory.session.added == []
    assert existing.name_zh == "旧名"
    assert existing.city == "北京"
    assert existing.status == "inactive"


def test_seed_upsert_chinatravel_skips_when_upgraded_twin_exists():
    """ct_* 骨架被升级成 amap（老升级 origin 留 NULL）→ 重导入视为 exists，不造影子."""
    existing = Poi(
        id=uuid4(),
        source="amap",
        source_poi_id="ct_北京_4",
        city="北京",
        name_zh="旧名",
        status="active",
    )
    factory = FakeFactory(FakeSession(rows=[existing]))
    out = seed_upsert(
        factory,
        Poi,
        source="chinatravel",
        source_poi_id="ct_北京_4",
        city="北京",
        name_zh="颐和园",
    )
    assert out == "exists"
    assert factory.session.added == []
    assert existing.name_zh == "旧名"


def test_seed_upsert_lineage_guard_only_for_chinatravel():
    """非 chinatravel 源不受血统闸影响：同 id 异源照常 create（跨源共存按设计）."""
    existing = Poi(
        id=uuid4(),
        source="amap",
        source_poi_id="5a_001",
        city="北京",
        name_zh="故宫",
        status="active",
    )
    factory = FakeFactory(FakeSession(rows=[existing]))
    out = seed_upsert(
        factory,
        Poi,
        source="5a",
        source_poi_id="5a_001",
        city="北京",
        name_zh="故宫",
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.source == "5a"


def test_seed_upsert_second_call_after_commit_is_exists():
    factory = FakeFactory()
    kw = {"source": "s", "source_poi_id": "1", "city": "北京", "name_zh": "景点A"}
    assert seed_upsert(factory, Poi, **kw) == "created"
    assert seed_upsert(factory, Poi, **kw) == "exists"
    assert factory.session.commits == 1


def test_seed_upsert_empty_name_skipped():
    factory = FakeFactory()
    out = seed_upsert(
        factory, Poi, source="s", source_poi_id="2", city="北京", name_zh="   "
    )
    assert out == "skipped"
    assert factory.session.added == []


def test_seed_upsert_db_error_skipped():
    factory = FakeFactory(FakeSession(fail_on="commit"))
    out = seed_upsert(
        factory, Poi, source="s", source_poi_id="3", city="北京", name_zh="景点B"
    )
    assert out == "skipped"


def test_seed_upsert_derives_gcj02_from_wgs84_only():
    factory = FakeFactory()
    out = seed_upsert(
        factory,
        Poi,
        source="osm",
        source_poi_id="w9",
        city="西安",
        name_zh="钟楼",
        wgs84_lonlat=(108.943, 34.261),
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.location is not None  # 仅 WGS84 → 自动派生 GCJ-02
    assert row.wgs84_location is not None
    assert row.location.data != row.wgs84_location.data  # 偏移已生效


def test_mark_status_sets_and_reports_missing():
    row = Poi(id=uuid4(), source="osm", source_poi_id="d1", name_zh="已删")
    factory = FakeFactory(FakeSession(rows=[row]))
    assert mark_status(factory, Poi, "osm", "d1", "inactive") is True
    assert row.status == "inactive"
    assert mark_status(factory, Poi, "osm", "nope", "inactive") is False


# ---------- 同馆去重闸（2026-10-26 用户令：所有入表行先过同馆去重） ----------


def _gate_row(**kw):
    base: dict = {
        "id": uuid4(),
        "source": "museum1",
        "source_poi_id": "m1_x",
        "city": "上海",
        "name_zh": "上海博物馆",
        "status": "active",
        "category": "museum",
    }
    base.update(kw)
    return Poi(**base)


def test_gate_same_name_same_city_merges_into_existing():
    existing = _gate_row()
    factory = FakeFactory(FakeSession(rows=[existing]))
    out = seed_upsert(
        factory,
        Poi,
        source="amap",
        source_poi_id="amap_1",
        city="上海",
        name_zh="上海博物馆",
        lonlat=(121.47, 31.23),
    )
    assert out == "exists"
    assert factory.session.added == []  # 不建第二行
    assert existing.location is not None  # 骨架坐标只填空回填
    assert existing.suggested_duration_min == 120  # heuristic 地板
    assert existing.duration_source == "heuristic"


def test_gate_same_name_diff_city_both_city_level_creates():
    # 孙中山纪念馆（南京/广州）——同名不同场馆，必须正常建行
    existing = _gate_row(
        source="chinatravel",
        source_poi_id="ct_nj_1",
        city="南京",
        name_zh="孙中山纪念馆",
    )
    factory = FakeFactory(FakeSession(rows=[existing]))
    out = seed_upsert(
        factory,
        Poi,
        source="chinatravel",
        source_poi_id="ct_gz_1",
        city="广州",
        name_zh="孙中山纪念馆",
    )
    assert out == "created"
    assert len(factory.session.added) == 1
    assert existing.status == "active"


def test_gate_cross_granularity_merges_and_adopts_city():
    # museum1 省级回退 city=浙江 vs 渠道行 city=杭州 —— 同馆并入并采纳市名
    existing = _gate_row(city="浙江", name_zh="中国丝绸博物馆")
    factory = FakeFactory(FakeSession(rows=[existing]))
    out = seed_upsert(
        factory,
        Poi,
        source="amap",
        source_poi_id="amap_2",
        city="杭州",
        name_zh="中国丝绸博物馆",
    )
    assert out == "exists"
    assert existing.city == "杭州"
    assert factory.session.added == []


def test_gate_curated_incoming_absorbs_channel_twin():
    # curated（museum1）来行 + 渠道孪生在库：curated 建行吸收骨架、孪生退役
    twin = _gate_row(
        source="chinatravel",
        source_poi_id="ct_hz_1",
        city="杭州",
        name_zh="中国丝绸博物馆",
        location=make_point(120.1, 30.2),
    )
    factory = FakeFactory(FakeSession(rows=[twin]))
    out = seed_upsert(
        factory,
        Poi,
        source="museum1",
        source_poi_id="m1_c",
        city="浙江",
        name_zh="中国丝绸博物馆",
        tags=["国家一级博物馆"],
        tags_source="cma",
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.source == "museum1"
    assert row.location is not None  # 吸收孪生坐标
    assert row.city == "杭州"  # 采纳精确市名
    assert twin.status == "retired"


def test_gate_alias_forward_match_merges():
    existing = _gate_row(city="江苏", name_zh="南京博物院")
    factory = FakeFactory(FakeSession(rows=[existing]))
    out = seed_upsert(
        factory,
        Poi,
        source="chinatravel",
        source_poi_id="ct_nj_9",
        city="南京",
        name_zh="南京博物馆",
        name_aliases=["南京博物院"],
    )
    assert out == "exists"
    assert factory.session.added == []
    assert existing.city == "南京"  # 跨粒度并入并采纳市名
    # 别名=目标行名本身时不入 aliases
    assert existing.name_aliases in (None, [])


def test_gate_key_conflict_shadow_wins_venue():
    # 血统影子（同键异源）是最强同馆信号：museum1 来行吸收影子骨架后建行
    shadow = _gate_row(
        source="amap",
        source_poi_id="m1_d",
        name_zh="上海科技馆",
        location=make_point(121.5, 31.2),
    )
    factory = FakeFactory(FakeSession(rows=[shadow]))
    out = seed_upsert(
        factory,
        Poi,
        source="museum1",
        source_poi_id="m1_d",
        city="上海",
        name_zh="上海科技馆",
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.source == "museum1"
    assert row.location is not None
    assert shadow.status == "retired"
