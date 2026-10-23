"""品质标签作业测试（米其林/黑珍珠 -> restaurants.tags，不连库）。"""

import uuid

from geoalchemy2.elements import WKTElement

from app.jobs.tag_quality import (
    collect_jobs,
    make_tags,
    map_row,
    merge_tags,
    name_similar,
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
            "Star": "1",
            "Bib Gourmand": "FALSE",
        }
    )
    assert entry is not None
    assert entry["name"] == "Noma Shanghai"
    assert entry["lat"] == 31.2304
    assert entry["lon"] == 121.4737
    assert entry["city"] == "Shanghai"
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


# ---------- within_distance：200m 边界 ----------


def test_within_distance_boundaries():
    assert within_distance(106.55, 29.56, 106.55, 29.56) is True  # 0m
    assert within_distance(106.55, 29.56, 106.55, 29.561) is True  # ~111m
    assert within_distance(106.55, 29.56, 106.55, 29.562) is False  # ~222m


# ---------- row_matches：坐标/无坐标两条路径 ----------


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


# ---------- tag_restaurants：假 session 主流程 ----------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_criterion):
        return self  # 城市过滤由 row_matches 兜底

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.commit_count = 0

    def query(self, *_cols):
        return _FakeQuery(self._rows)

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


def test_tag_restaurants_hit_miss_and_union():
    hit_row = _mk_row("渝味晓宇火锅", "重庆市", tags=["amap_top"])
    miss_row = _mk_row("随便一家店", "重庆市")
    factory = _fake_factory([hit_row, miss_row])
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
        {
            "entry": {"name": "查无此店", "city": "重庆", "lat": None, "lon": None},
            "tags": ["michelin_2star"],
        },
    ]
    stats = tag_restaurants(factory, jobs, kind="michelin")
    assert stats["matched"] == 1
    assert stats["unmatched"] == 1
    assert stats["tagged_rows"] == 1
    assert stats["unmatched_detail"][0]["name"] == "查无此店"
    assert stats["unmatched_detail"][0]["reason"] == "no_db_match"
    # 并集去重保序：旧 tags 在前
    assert hit_row.tags == ["amap_top", "michelin_1star", "bib_gourmand"]
    assert hit_row.tags_source == "michelin"
    assert miss_row.tags is None
    assert factory.created[0].commit_count == 1


def test_tag_restaurants_rerun_dedupes_without_retagging():
    row = _mk_row("渝味晓宇火锅", "重庆市", tags=["bib_gourmand"])
    factory = _fake_factory([row])
    jobs = [
        {
            "entry": {"name": "渝味晓宇火锅", "city": "重庆", "lat": None, "lon": None},
            "tags": ["bib_gourmand", "michelin_1star"],
        }
    ]
    first = tag_restaurants(factory, jobs, kind="michelin")
    assert first["matched"] == 1 and first["tagged_rows"] == 1
    assert row.tags == ["bib_gourmand", "michelin_1star"]
    second = tag_restaurants(factory, jobs, kind="michelin")
    assert second["matched"] == 1
    assert second["tagged_rows"] == 0  # 无变化不重复写
    assert row.tags == ["bib_gourmand", "michelin_1star"]


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


def test_merge_tags_dedup_keeps_order():
    assert merge_tags(["b", "a"], ["a", "c"]) == ["b", "a", "c"]
    assert merge_tags(None, ["x"]) == ["x"]


# ---------- collect_jobs：tmp_path CSV（BOM + 列映射） ----------


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
    assert jobs[0]["tags"] == ["black_pearl_2diamond"]  # Diamond 列优先
    assert jobs[1]["tags"] == ["black_pearl_1diamond"]  # 缺列回退默认
    limited, lstats = collect_jobs(str(path), "black_pearl", limit=1)
    assert lstats["read"] == 1 and len(limited) == 1


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
