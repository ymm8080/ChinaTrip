"""博物馆分级名单导入测试（CSV 解析/映射/幂等，不连真库）."""

import json

from app.jobs import import_museum_grades as job
from app.models import Poi

# ---------- grade_source / slug_for ----------


def test_grade_source_mapping():
    assert job.grade_source("国家一级博物馆") == "museum1"
    assert job.grade_source(" 国家二级博物馆 ") == "museum2"
    assert job.grade_source("三级") == "museum3"  # 简写容忍
    assert job.grade_source("5A景区") is None
    assert job.grade_source("") is None
    assert job.grade_source(None) is None


def test_slug_for_stable_and_distinct():
    a = job.slug_for(1, "故宫博物院")
    assert a == job.slug_for(1, "故宫博物院")
    assert a.startswith("m1_")
    assert a != job.slug_for(1, "中国国家博物馆")
    assert a != job.slug_for(2, "故宫博物院")  # 级别进键


# ---------- load_rows ----------


def test_load_rows_parses_and_normalizes(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text(
        "name_zh,province,city,grade,batch,alias_zh,source_url\n"
        "故宫博物院,北京,,国家一级博物馆,1,,http://x/1\n"
        "湖南博物院,湖南,长沙,一级,5,湖南省博物馆,http://x/2\n"
        "坏行,河北,,不知道,1,,\n"
        ",北京,北京,国家一级博物馆,1,,\n",
        encoding="utf-8",
    )
    rows, invalid = job.load_rows(str(p))
    assert invalid == 2
    assert len(rows) == 2
    gugong = rows[0]
    assert gugong["source"] == "museum1"
    assert gugong["city"] == "北京"  # 直辖市：city 缺省回退 province
    assert gugong["label"] == "国家一级博物馆"
    hunan = rows[1]
    assert hunan["city"] == "长沙"
    assert hunan["aliases"] == ["湖南省博物馆"]
    assert hunan["batch"] == "5"
    assert hunan["source_poi_id"] == job.slug_for(1, "湖南博物院")


def test_load_rows_bom_tolerant(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text(
        "\ufeffname_zh,province,city,grade,batch,alias_zh,source_url\n"
        "中国国家博物馆,北京,北京,国家一级博物馆,1,,http://x\n",
        encoding="utf-8",
    )
    rows, invalid = job.load_rows(str(p))
    assert invalid == 0
    assert rows[0]["name_zh"] == "中国国家博物馆"


# ---------- run_import ----------


class _FakeSession:
    def __init__(self, existing=()):
        self._existing = set(existing)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
        return self

    def filter_by(self, **kw):
        self._kw = kw
        return self

    def one_or_none(self):
        key = (self._kw.get("source"), self._kw.get("source_poi_id"))
        return object() if key in self._existing else None


class _FakeFactory:
    def __init__(self, existing=()):
        self.session = _FakeSession(existing)

    def __call__(self):
        return self.session


def _rows():
    return [
        {
            "source": "museum1",
            "source_poi_id": "m1_aaa",
            "city": "北京",
            "name_zh": "故宫博物院",
            "label": "国家一级博物馆",
            "batch": "1",
            "aliases": [],
        },
        {
            "source": "museum1",
            "source_poi_id": "m1_bbb",
            "city": "长沙",
            "name_zh": "湖南博物院",
            "label": "国家一级博物馆",
            "batch": "5",
            "aliases": ["湖南省博物馆"],
        },
    ]


def test_run_import_dry_run_is_readonly(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry-run 不得触发 seed_upsert")

    monkeypatch.setattr(job, "seed_upsert", boom)
    stats = job.run_import(
        _FakeFactory(existing={("museum1", "m1_aaa")}), _rows(), dry_run=True
    )
    assert stats["created"] == 1
    assert stats["exists"] == 1
    assert stats["by_source"] == {"museum1": 2}


def test_run_import_calls_seed_with_skeleton_kwargs(monkeypatch):
    seen = []

    def fake_seed(factory, model, **kw):
        seen.append((model, kw))
        return "created"

    monkeypatch.setattr(job, "seed_upsert", fake_seed)
    stats = job.run_import(_FakeFactory(), _rows())
    assert stats["created"] == 2
    assert stats["skipped"] == 0
    (model, kw1), (_, kw2) = seen
    assert model is Poi
    assert kw1["source"] == "museum1"
    assert kw1["category"] == "博物馆/纪念馆"
    assert kw1["origin"] == "cma"
    assert kw1["tags"] == ["国家一级博物馆"]
    assert kw1["tags_source"] == "cma"
    assert kw1["name_aliases"] is None
    assert kw2["name_aliases"] == ["湖南省博物馆"]


def test_run_import_tallies_skip(monkeypatch):
    monkeypatch.setattr(job, "seed_upsert", lambda *a, **k: "skipped")
    stats = job.run_import(_FakeFactory(), _rows())
    assert stats["skipped"] == 2


# ---------- main：文件缺失 / DB 不可达路径 ----------


def test_main_missing_csv(capsys):
    rc = job.main(["--csv", "no_such_file.csv"])
    assert rc == 1
    assert json.loads(capsys.readouterr().out)["error"].startswith("csv not found")


def test_main_db_unreachable(monkeypatch, tmp_path, capsys):
    p = tmp_path / "m.csv"
    p.write_text(
        "name_zh,province,city,grade,batch,alias_zh,source_url\n"
        "故宫博物院,北京,北京,国家一级博物馆,1,,http://x\n",
        encoding="utf-8",
    )

    class _DownFactory:
        def __call__(self):
            raise RuntimeError("db down")

    import app.db as app_db

    monkeypatch.setattr(app_db, "get_session_factory", lambda: _DownFactory())
    rc = job.main(["--csv", str(p)])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"].startswith("db_unreachable")


# ---------- seed_upsert 集成：tags/aliases 真落骨架行 ----------


class _SeedSession:
    def __init__(self):
        self.rows = []
        self.added = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
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
        self.rows.extend(self.added)


class _SeedFactory:
    def __init__(self):
        self.session = _SeedSession()

    def __call__(self):
        return self.session


def test_seed_upsert_persists_tags_and_aliases():
    from app.services.poi_seed import seed_upsert

    factory = _SeedFactory()
    out = seed_upsert(
        factory,
        Poi,
        source="museum1",
        source_poi_id="m1_test",
        city="江苏",
        name_zh="南京博物院",
        category="博物馆/纪念馆",
        origin="cma",
        tags=["国家一级博物馆"],
        tags_source="cma",
        name_aliases=["南京博物馆"],
    )
    assert out == "created"
    (row,) = factory.session.added
    assert row.tags == ["国家一级博物馆"]
    assert row.tags_source == "cma"
    assert row.name_aliases == ["南京博物馆"]
    assert row.category == "museum"
    assert row.city == "江苏"

    # 幂等：同键重跑不覆盖任何字段
    again = seed_upsert(
        factory,
        Poi,
        source="museum1",
        source_poi_id="m1_test",
        city="江苏",
        name_zh="南京博物院",
    )
    assert again == "exists"
    assert len(factory.session.added) == 1


# ---------- artmuseum：国家重点美术馆 / 未评级 ----------


def test_grade_source_art_system():
    assert job.grade_source("国家重点美术馆") == "artmuseum"
    assert job.grade_source("未评级") == "artmuseum"


def test_load_rows_art_ungraded_has_no_label(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(
        "name_zh,province,city,grade,batch,alias_zh,source_url\n"
        "浦东美术馆,上海,上海,未评级,,,http://x\n",
        encoding="utf-8",
    )
    rows, invalid = job.load_rows(str(p))
    assert invalid == 0 and len(rows) == 1
    assert rows[0]["source"] == "artmuseum"
    assert rows[0]["label"] is None
    assert rows[0]["origin"] == "curated"
    assert rows[0]["source_poi_id"].startswith("a1_")


def test_run_import_ungraded_no_tag(monkeypatch):
    seen = []

    def fake_seed(factory, model, **kw):
        seen.append(kw)
        return "created"

    monkeypatch.setattr(job, "seed_upsert", fake_seed)
    job.run_import(
        _FakeFactory(),
        [
            {
                "source": "artmuseum",
                "source_poi_id": "a1_x",
                "city": "上海",
                "name_zh": "浦东美术馆",
                "label": None,
                "origin": "curated",
                "batch": "",
                "aliases": [],
            }
        ],
    )
    kw = seen[0]
    assert kw["tags"] is None
    assert kw["tags_source"] is None
    assert kw["origin"] == "curated"
