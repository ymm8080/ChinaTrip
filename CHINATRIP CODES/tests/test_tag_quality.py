"""品质标签 + 补库作业测试（米其林/黑珍珠 -> restaurants，不连库）。"""

import json
import uuid

from geoalchemy2.elements import WKTElement

from app.jobs.tag_quality import (
    _slug_for,
    collect_jobs,
    entry_gcj02,
    make_tags,
    map_row,
    merge_tags,
    name_similar,
    normalize_entry_city,
    normalize_name,
    row_matches,
    same_city,
    tag_restaurants,
    within_distance,
)
from app.models import Restaurant

# ---------- map_row：列名弹性映射 ----------


def test_map_row_michelin_english_columns():
    entry = map_row(
        {
            "Name": "Noma Shanghai",
            "Latitude": "31.2304",
            "Longitude": "121.4737",
            "City": "Shanghai",
            "Cuisine": "Modern French",
            "Url": "https://guide.michelin.com/en/shanghai/restaurant/noma-sh",
            "Star": "1",
            "Bib Gourmand": "FALSE",
        }
    )
    assert entry is not None
    assert entry["name"] == "Noma Shanghai"
    assert entry["lat"] == 31.2304
    assert entry["lon"] == 121.4737
    assert entry["city"] == "Shanghai"
    assert entry["cuisine"] == "Modern French"
    assert entry["url"].endswith("noma-sh")
    assert entry["star"] == "1"
    assert entry["bib"] == "FALSE"


def test_map_row_black_pearl_chinese_columns():
    entry = map_row(
        {
            "餐厅名": "渝味晓宇火锅",
            "纬度": "29.56",
            "经度": "106.55",
            "城市": "重庆",
        }
    )
    assert entry is not None
    assert entry["name"] == "渝味晓宇火锅"
    assert entry["city"] == "重庆"
    assert entry["lat"] == 29.56
    assert entry["lon"] == 106.55


def test_map_row_michelin_location_and_award_columns():
    # 实测列型（2026-10-24）：城市在 Location 逗号前段，奖项在 Award
    entry = map_row(
        {
            "Name": "Cheng Long Hang (Huangpu)",
            "Location": "Shanghai, Chinese Mainland",
            "Latitude": "31.239067",
            "Longitude": "121.48161",
            "Cuisine": "Shanghainese",
            "Url": "https://guide.michelin.com/en/shanghai/restaurant/cheng-long-hang-huangpu",
            "Award": "1 Star",
        }
    )
    assert entry is not None
    assert entry["city"] == "Shanghai"
    assert entry["award"] == "1 Star"
    assert entry["cuisine"] == "Shanghainese"
    assert make_tags("michelin", entry) == ["michelin_1star"]
    assert make_tags("michelin", dict(entry, award="2 Stars")) == ["michelin_2star"]
    assert make_tags("michelin", dict(entry, award="3 Stars")) == ["michelin_3star"]
    assert make_tags("michelin", dict(entry, award="Bib Gourmand")) == ["bib_gourmand"]
    assert make_tags("michelin", dict(entry, award="Green Star")) == []
    # 新旧列型并存时不产生重复标签
    assert make_tags("michelin", dict(entry, star="1", bib="TRUE")) == [
        "michelin_1star",
        "bib_gourmand",
    ]


def test_row_matches_english_city_normalized():
    # 米其林英文城市 vs 中文库行：两侧须过别名归一才能匹配上
    row = _mk_row(
        "成香龙行",
        "成都市",
        name_en="Cheng Long Hang",
    )
    entry = {
        "name": "Cheng Long Hang",
        "city": "Chengdu",
        "lon": None,
        "lat": None,
    }
    assert row_matches(entry, row) is True


def test_map_row_no_name_is_invalid():
    assert map_row({"Latitude": "1.0", "City": "重庆"}) is None
    assert map_row({}) is None


def test_map_row_bad_coords_become_none():
    entry = map_row({"Name": "X", "Latitude": "abc", "Longitude": ""})
    assert entry is not None
    assert entry["lat"] is None
    assert entry["lon"] is None


# ---------- make_tags：标签生成 ----------


def test_make_tags_michelin_star_and_bib():
    assert make_tags("michelin", {"star": "1"}) == ["michelin_1star"]
    assert make_tags("michelin", {"star": "3"}) == ["michelin_3star"]
    assert make_tags("michelin", {"star": "0"}) == []
    assert make_tags("michelin", {"star": "0", "bib": "TRUE"}) == ["bib_gourmand"]
    assert make_tags("michelin", {"star": "2", "bib": "true"}) == [
        "michelin_2star",
        "bib_gourmand",
    ]
    assert make_tags("michelin", {"star": "1", "bib": "1"}) == [
        "michelin_1star",
        "bib_gourmand",
    ]
    assert make_tags("michelin", {"star": "1", "bib": "FALSE"}) == ["michelin_1star"]


def test_make_tags_black_pearl_diamond():
    # 默认钻级 1
    assert make_tags("black_pearl", {}) == ["black_pearl_1diamond"]
    assert make_tags("black_pearl", {}, diamond_default=3) == ["black_pearl_3diamond"]
    # CSV 有 Diamond 列则优先
    assert make_tags("black_pearl", {"diamond": "2"}) == ["black_pearl_2diamond"]
    # 列值非法 -> 回退默认
    assert make_tags("black_pearl", {"diamond": "9"}) == ["black_pearl_1diamond"]


def test_make_tags_unknown_kind_empty():
    assert make_tags("zomato", {"star": "1"}) == []


# ---------- normalize_name / name_similar / same_city ----------


def test_normalize_name_strips_brackets_spaces_case():
    assert normalize_name("渝味晓宇（总店）") == "渝味晓宇"
    assert normalize_name("老店（解放碑店）(分店)") == "老店"
    assert normalize_name("Qi Lu [新店]") == "qilu"
    assert normalize_name("ＧＵＩＤＥ 米其林") == "guide米其林"
    assert normalize_name("A B  C") == "abc"


def test_name_similar_threshold_boundary():
    # SequenceMatcher("abcd","abce").ratio() == 0.75，恰好踩线
    assert name_similar("abcd", "abce", threshold=0.75) is True
    assert name_similar("abcd", "abce", threshold=0.76) is False
    assert name_similar("渝味晓宇火锅", "渝味晓宇火锅") is True
    assert name_similar("渝味晓宇火锅", "完全不同一家店") is False


def test_same_city_strips_shi_suffix():
    assert same_city("重庆", "重庆市") is True
    assert same_city("重庆市", "重庆") is True
    assert same_city("重庆", "成都") is False
    assert same_city(None, "重庆") is False


def test_normalize_entry_city_alias_and_suffix():
    assert normalize_entry_city("Shanghai") == "上海"
    assert normalize_entry_city("CHENGDU") == "成都"
    assert normalize_entry_city("重庆市") == "重庆"
    assert normalize_entry_city("Paris") == "Paris"
    assert normalize_entry_city(None) == ""


# ---------- entry_gcj02：坐标基准 ----------


def test_entry_gcj02_converts_wgs84_datum():
    entry = {"lon": 106.55, "lat": 29.56, "datum": "wgs84"}
    lon, lat = entry_gcj02(entry)
    assert (lon, lat) != (106.55, 29.56)  # 偏移量级数百米
    assert entry_gcj02({"lon": None, "lat": None, "datum": "wgs84"}) is None
    gcj02_entry = {"lon": 106.55, "lat": 29.56, "datum": "gcj02"}
    assert entry_gcj02(gcj02_entry) == (106.55, 29.56)  # 不转
    no_datum = {"lon": 106.55, "lat": 29.56}
    assert entry_gcj02(no_datum) == (106.55, 29.56)  # 缺 datum 不转


# ---------- within_distance：200m 边界 ----------


def test_within_distance_boundaries():
    assert within_distance(106.55, 29.56, 106.55, 29.56) is True  # 0m
    assert within_distance(106.55, 29.56, 106.55, 29.561) is True  # ~111m
    assert within_distance(106.55, 29.56, 106.55, 29.562) is False  # ~222m


# ---------- row_matches：坐标/无坐标/WGS84 转换两条路径 ----------


def _mk_row(name_zh, city, *, tags=None, name_en=None, location=None):
    return Restaurant(
        id=uuid.uuid4(),
        source="amap",
        source_poi_id=uuid.uuid4().hex[:12],
        city=city,
        name_zh=name_zh,
        name_en=name_en,
        tags=list(tags) if tags else None,
        location=location,
    )


def test_row_matches_distance_gate_with_coords():
    row = _mk_row(
        "渝味晓宇火锅",
        "重庆市",
        location=WKTElement("POINT(106.55 29.56)", srid=4326),
    )
    near = {"name": "渝味晓宇火锅", "city": "重庆", "lon": 106.55, "lat": 29.561}
    far = {"name": "渝味晓宇火锅", "city": "重庆", "lon": 106.55, "lat": 29.562}
    assert row_matches(near, row) is True  # ~111m < 200m
    assert row_matches(far, row) is False  # ~222m >= 200m


def test_row_matches_no_coords_source_uses_stricter_threshold():
    row = _mk_row("渝味晓宇火锅", "重庆市")
    exact = {"name": "渝味晓宇火锅", "city": "重庆", "lon": None, "lat": None}
    fuzzy = {"name": "渝味晓宇", "city": "重庆", "lon": None, "lat": None}
    # ratio 0.8：无坐标源阈值 0.85，不放行
    assert row_matches(fuzzy, row) is False
    assert row_matches(exact, row) is True


def test_row_matches_michelin_wgs84_converted_before_distance():
    from app.services.coords import wgs84_to_gcj02

    # 库行 location 是 GCJ-02（同入库口径）；米其林 entry 是 WGS84
    wgs_lon, wgs_lat = 121.4737, 31.2304
    gcj_lon, gcj_lat = wgs84_to_gcj02(wgs_lon, wgs_lat)
    row = _mk_row(
        "Noma Shanghai",
        "上海",
        location=WKTElement(f"POINT({gcj_lon} {gcj_lat})", srid=4326),
    )
    entry = {
        "name": "Noma Shanghai",
        "city": "上海",
        "lon": wgs_lon,
        "lat": wgs_lat,
        "datum": "wgs84",
    }
    # 不转换则偏移数百米必超 200m；转换后应命中
    assert row_matches(dict(entry, datum="gcj02"), row) is False
    assert row_matches(entry, row) is True


# ---------- _slug_for：稳定 source_poi_id ----------


def test_slug_for_uses_url_tail():
    entry = {"name": "X", "url": "https://guide.michelin.com/en/restaurant/noma-sh"}
    assert _slug_for("michelin", "上海", entry) == "上海:noma-sh"


def test_slug_for_hash_fallback_is_stable():
    entry = {"name": "渝味晓宇火锅", "url": None}
    a = _slug_for("black_pearl", "重庆", entry)
    b = _slug_for("black_pearl", "重庆", entry)
    assert a == b and a.startswith("重庆:") and len(a) > len("重庆:")


# ---------- tag_restaurants：假 session 主流程 ----------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_criterion):
        return self  # 城市过滤由 row_matches 兜底

    def filter_by(self, **kw):
        out = [
            r
            for r in self._rows
            if all(getattr(r, k, None) == v for k, v in kw.items())
        ]
        return _FakeQuery(out)

    def distinct(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self.first()


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.added: list = []
        self.commit_count = 0

    def query(self, *cols):
        if cols and cols[0] is not Restaurant:  # query(Restaurant.city) 列查询
            cities = [(r.city,) for r in self._rows if getattr(r, "city", None)]
            return _FakeQuery(cities)
        return _FakeQuery(self._rows)

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commit_count += 1

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _fake_factory(rows):
    created: list = []

    def factory():
        session = _FakeSession(rows)
        created.append(session)
        return session

    factory.created = created
    return factory


def test_tag_restaurants_hit_and_union():
    hit_row = _mk_row("渝味晓宇火锅", "重庆市", tags=["amap_top"])
    factory = _fake_factory([hit_row])
    jobs = [
        {
            "entry": {
                "name": "渝味晓宇火锅（总店）",
                "city": "重庆",
                "lat": None,
                "lon": None,
            },
            "tags": ["michelin_1star", "bib_gourmand"],
        },
    ]
    stats = tag_restaurants(factory, jobs, kind="michelin")
    assert stats["matched"] == 1
    assert stats["tagged_rows"] == 1
    assert stats["appended"] == 0
    # 并集去重保序：旧 tags 在前
    assert hit_row.tags == ["amap_top", "michelin_1star", "bib_gourmand"]
    assert hit_row.tags_source == "michelin"
    assert factory.created[0].commit_count == 1


def test_tag_restaurants_appends_missing_row():
    # 闸门：库内有同城行才允许补库
    factory = _fake_factory([_mk_row("随便一家店", "重庆市")])
    jobs = [
        {
            "entry": {
                "name": "查无此店",
                "city": "重庆",
                "lat": 29.56,
                "lon": 106.55,
                "datum": "gcj02",
                "cuisine": "Hotpot",
                "url": "",
            },
            "tags": ["michelin_2star"],
        }
    ]
    stats = tag_restaurants(factory, jobs, kind="michelin")
    assert stats["matched"] == 0
    assert stats["appended"] == 1
    assert stats["appended_detail"][0]["name"] == "查无此店"
    session = factory.created[0]
    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, Restaurant)
    assert row.source == "michelin"
    assert row.source_poi_id.startswith("重庆:")
    assert row.city == "重庆"
    assert row.name_zh == "查无此店"
    assert row.cuisine == "Hotpot"
    assert row.tags == ["michelin_2star"]
    assert row.tags_source == "michelin"
    assert row.status == "active"
    assert row.location is not None  # gcj02 坐标入库
    assert row.wgs84_location is None  # 非 WGS84 源不写
    assert row.address is None and row.opening_hours is None  # 铁律：时间敏感不写


def test_tag_restaurants_city_not_covered_skips_append():
    factory = _fake_factory([])
    jobs = [
        {
            "entry": {
                "name": "Paris Bistro",
                "city": "Paris",
                "lat": None,
                "lon": None,
            },
            "tags": ["michelin_1star"],
        }
    ]
    stats = tag_restaurants(factory, jobs, kind="michelin")
    assert stats["appended"] == 0
    assert stats["unmatched"] == 1
    assert stats["unmatched_detail"][0]["reason"] == "city_not_covered"
    assert factory.created[0].added == []


def test_tag_restaurants_english_city_normalized_before_append():
    factory = _fake_factory([_mk_row("随便一家店", "上海")])
    jobs = [
        {
            "entry": {
                "name": "Noma Shanghai",
                "city": "Shanghai",
                "lat": 31.2304,
                "lon": 121.4737,
                "datum": "wgs84",
                "url": "https://guide.michelin.com/en/restaurant/noma-sh",
            },
            "tags": ["michelin_1star"],
        }
    ]
    stats = tag_restaurants(factory, jobs, kind="michelin")
    assert stats["appended"] == 1
    row = factory.created[0].added[0]
    assert row.city == "上海"
    assert row.source_poi_id == "上海:noma-sh"
    # WGS84 源：location 存 GCJ-02、wgs84_location 存原值
    assert row.location is not None
    assert row.wgs84_location is not None


def test_tag_restaurants_hong_kong_macau_taipei_always_covered():
    # 港澳台进表（用户拍板 2026-10-24）：空库也放行，不受底库闸门限制
    factory = _fake_factory([])
    jobs = [
        {
            "entry": {
                "name": "Amber",
                "city": "Hong Kong",
                "lat": 22.277,
                "lon": 114.158,
                "datum": "wgs84",
            },
            "tags": ["black_pearl_2diamond"],
        },
        {
            "entry": {"name": "Jade Dragon", "city": "Macau", "lat": None, "lon": None},
            "tags": ["black_pearl_3diamond"],
        },
        {
            "entry": {
                "name": "LOGY",
                "city": "Taipei",
                "lat": 25.033,
                "lon": 121.565,
                "datum": "wgs84",
            },
            "tags": ["michelin_1star"],
        },
    ]
    stats = tag_restaurants(factory, jobs, kind="black_pearl")
    assert stats["appended"] == 3
    assert [r.city for r in factory.created[0].added] == ["香港", "澳门", "台北"]


def test_tag_restaurants_taichung_kaohsiung_always_covered():
    # 港澳台全口径（2026-10-24）：米其林台中/高雄指南同样豁免闸门
    factory = _fake_factory([])
    jobs = [
        {
            "entry": {
                "name": "Forchetta",
                "city": "Taichung",
                "lat": 24.15,
                "lon": 120.68,
                "datum": "wgs84",
            },
            "tags": ["michelin_1star"],
        },
        {
            "entry": {
                "name": "Haili",
                "city": "Kaohsiung",
                "lat": None,
                "lon": None,
            },
            "tags": ["michelin_bib"],
        },
    ]
    stats = tag_restaurants(factory, jobs, kind="michelin")
    assert stats["appended"] == 2
    assert [r.city for r in factory.created[0].added] == ["台中", "高雄"]


def test_tag_restaurants_other_overseas_still_blocked():
    factory = _fake_factory([])
    jobs = [
        {
            "entry": {"name": "Odette", "city": "Singapore", "lat": None, "lon": None},
            "tags": ["michelin_2star"],
        }
    ]
    stats = tag_restaurants(factory, jobs, kind="michelin")
    assert stats["appended"] == 0
    assert stats["unmatched_detail"][0]["reason"] == "city_not_covered"
    assert factory.created[0].added == []


def test_tag_restaurants_rerun_is_idempotent():
    # 第一次：未命中 -> 补建（闸门：库内已有同城行）
    factory = _fake_factory([_mk_row("随便一家店", "重庆")])
    jobs = [
        {
            "entry": {"name": "渝味晓宇火锅", "city": "重庆", "lat": None, "lon": None},
            "tags": ["black_pearl_2diamond"],
        }
    ]
    first = tag_restaurants(factory, jobs, kind="black_pearl")
    assert first["appended"] == 1
    appended_row = factory.created[0].added[0]
    # 第二次：补建行已在"库"里（无坐标、名称精确）-> matched，不重复建
    factory2 = _fake_factory([appended_row])
    second = tag_restaurants(factory2, jobs, kind="black_pearl")
    assert second["matched"] == 1
    assert second["appended"] == 0
    assert second["tagged_rows"] == 0  # 标签未变化
    assert factory2.created[0].added == []


def test_tag_restaurants_overwrite_replaces_tags():
    row = _mk_row("渝味晓宇火锅", "重庆市", tags=["old_tag", "bib_gourmand"])
    factory = _fake_factory([row])
    jobs = [
        {
            "entry": {"name": "渝味晓宇火锅", "city": "重庆", "lat": None, "lon": None},
            "tags": ["michelin_1star"],
        }
    ]
    stats = tag_restaurants(factory, jobs, kind="michelin", overwrite=True)
    assert stats["tagged_rows"] == 1
    assert row.tags == ["michelin_1star"]


def test_tag_restaurants_multi_hit_same_name_tags_all():
    row_a = _mk_row("渝味晓宇火锅", "重庆市")
    row_b = _mk_row("渝味晓宇火锅", "重庆")
    factory = _fake_factory([row_a, row_b])
    jobs = [
        {
            "entry": {"name": "渝味晓宇火锅", "city": "重庆", "lat": None, "lon": None},
            "tags": ["black_pearl_2diamond"],
        }
    ]
    stats = tag_restaurants(factory, jobs, kind="black_pearl")
    assert stats["matched"] == 1
    assert stats["tagged_rows"] == 2
    assert row_a.tags == ["black_pearl_2diamond"]
    assert row_b.tags == ["black_pearl_2diamond"]


def test_tag_restaurants_missing_city_goes_unmatched():
    row = _mk_row("渝味晓宇火锅", "重庆市")
    factory = _fake_factory([row])
    jobs = [
        {
            "entry": {"name": "渝味晓宇火锅", "city": None, "lat": None, "lon": None},
            "tags": ["michelin_1star"],
        }
    ]
    stats = tag_restaurants(factory, jobs, kind="michelin")
    assert stats["matched"] == 0
    assert stats["unmatched"] == 1
    assert stats["unmatched_detail"][0]["reason"] == "no_city"
    assert row.tags is None
    assert factory.created[0].added == []


def test_merge_tags_dedup_keeps_order():
    assert merge_tags(["b", "a"], ["a", "c"]) == ["b", "a", "c"]
    assert merge_tags(None, ["x"]) == ["x"]


# ---------- collect_jobs：tmp_path CSV（BOM + 列映射 + datum） ----------


def _write_csv(path, header, rows, *, bom=True):
    lines = [",".join(header)] + [",".join(r) for r in rows]
    text = "\r\n".join(lines) + "\r\n"
    raw = ("﻿" + text if bom else text).encode("utf-8")
    path.write_bytes(raw)


def test_collect_jobs_michelin_csv_bom_and_mapping(tmp_path):
    path = tmp_path / "michelin.csv"
    _write_csv(
        path,
        ["Name", "Latitude", "Longitude", "City", "Star", "Bib Gourmand"],
        [
            ["Noma Shanghai", "31.23", "121.47", "Shanghai", "1", "FALSE"],
            ["Bib Shop", "31.24", "121.48", "Shanghai", "0", "TRUE"],
            ["", "31.2", "121.4", "Shanghai", "0", "FALSE"],  # 无 name -> invalid
        ],
    )
    jobs, stats = collect_jobs(str(path), "michelin")
    # BOM 若未剥离，首列名变 "﻿Name"，首行会误判 invalid —— 此处须通过
    assert stats["read"] == 3
    assert stats["invalid"] == 1
    assert jobs[0]["entry"]["name"] == "Noma Shanghai"
    assert jobs[0]["entry"]["datum"] == "wgs84"  # 米其林源坐标基准
    assert jobs[0]["tags"] == ["michelin_1star"]
    assert jobs[1]["tags"] == ["bib_gourmand"]


def test_collect_jobs_black_pearl_chinese_columns_and_limit(tmp_path):
    path = tmp_path / "black_pearl.csv"
    _write_csv(
        path,
        ["餐厅名", "纬度", "经度", "城市", "Diamond"],
        [
            ["渝味晓宇火锅", "29.56", "106.55", "重庆", "2"],
            ["另一家店", "29.57", "106.56", "重庆", ""],
            ["第三家店", "29.58", "106.57", "重庆", ""],
        ],
    )
    jobs, stats = collect_jobs(str(path), "black_pearl", diamond_default=1)
    assert stats["read"] == 3
    assert stats["invalid"] == 0
    assert jobs[0]["entry"]["datum"] == "wgs84"  # gourmet-map geo 链统一 WGS84
    assert jobs[0]["tags"] == ["black_pearl_2diamond"]  # Diamond 列优先
    assert jobs[1]["tags"] == ["black_pearl_1diamond"]  # 缺列回退默认
    limited, lstats = collect_jobs(str(path), "black_pearl", limit=1)
    assert lstats["read"] == 1 and len(limited) == 1


def test_collect_jobs_black_pearl_gourmet_map_json(tmp_path):
    # 实测源（2026-10-24 jyb635050-ai/gourmet-map）：小写键 + lng + award "bp2"
    path = tmp_path / "blackpearl.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "Xin Rong Ji",
                    "city": "Shanghai",
                    "lat": 31.23,
                    "lng": 121.47,
                    "award": "bp2",
                    "cuisine": "Taizhou Cuisine",
                },
                {
                    "name": "No Coord Shop",
                    "city": "Beijing",
                    "lat": None,
                    "lng": None,
                    "award": "bp1",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    jobs, stats = collect_jobs(str(path), "black_pearl")
    assert stats["read"] == 2 and stats["invalid"] == 0
    entry = jobs[0]["entry"]
    assert entry["name"] == "Xin Rong Ji"
    assert (entry["lat"], entry["lon"]) == (31.23, 121.47)  # lng 键已识别
    assert entry["datum"] == "wgs84"
    assert jobs[0]["tags"] == ["black_pearl_2diamond"]  # award bp2 -> 钻级
    assert jobs[1]["entry"]["lon"] is None  # 未编码条目走严格名称路径
    assert jobs[1]["tags"] == ["black_pearl_1diamond"]


def test_collect_jobs_no_qualifying_tags_counted(tmp_path):
    path = tmp_path / "michelin_flat.csv"
    _write_csv(
        path,
        ["Name", "City", "Star", "Bib Gourmand"],
        [["普通餐厅", "重庆", "0", "FALSE"]],
    )
    jobs, stats = collect_jobs(str(path), "michelin")
    assert jobs == []
    assert stats["no_tags"] == 1
    assert stats["no_tags_detail"][0]["reason"] == "no_qualifying_tag"
