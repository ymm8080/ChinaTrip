"""poi_seed 骨架导入存储层测试（内存 FakeSession，不连真库）."""

from uuid import uuid4

from geoalchemy2.elements import WKTElement

from app.models import Poi, Restaurant
from app.services.poi_seed import mark_status, normalize_category, seed_upsert


class FakeSession:
    """内存会话：只实现 seed_upsert 用到的 query 链 + add/commit."""

    def __init__(self, rows=None, fail_on=None):
        self.rows = list(rows or [])  # 已持久化行
        self.added = []  # add() 过的对象（commit 后保留，便于断言）
        self.commits = 0
        self._fail_on = fail_on  # "query" | "commit"
        self._kw: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
        if self._fail_on == "query":
            raise RuntimeError("db down")
        return self

    def filter_by(self, **kw):
        self._kw = kw
        return self

    def one_or_none(self):
        for row in self.rows:
            if all(getattr(row, k, None) == v for k, v in self._kw.items()):
                return row
        return None

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
