"""import_chinatravel job 测试（stub seed/amap/ping，不连真库不联网）."""

import asyncio
import json
import math

import pandas as pd

from app.jobs import import_chinatravel as job
from app.models import Poi, Restaurant
from app.services.coords import wgs84_to_gcj02

#: 铁律：parquet 时间敏感字段绝不落库
TIME_COLS = ("opentime", "endtime", "price", "recommendmintime", "recommendmaxtime")

BJ_LON, BJ_LAT = 116.3972, 39.9163


class SeedStub:
    """可注入 seed_upsert：捕获调用参数，恒返回固定结果."""

    def __init__(self, result: str = "created"):
        self.calls: list[tuple[object, dict]] = []
        self.result = result

    def __call__(self, session_factory, model, **kwargs):
        self.calls.append((model, kwargs))
        return self.result


class AmapStub:
    """search_poi 按关键词返回坐标（location 形如 amap _normalize_poi）."""

    def __init__(self, locs: dict[str, tuple[float, float]]):
        self.locs = {k: {"lon": lo, "lat": la} for k, (lo, la) in locs.items()}
        self.calls: list[tuple[str, str | None]] = []

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append((keywords, city))
        loc = self.locs.get(keywords)
        return [{"location": dict(loc)}] if loc else []


def _base_rows() -> list[dict]:
    return [
        {
            "language": "zh",
            "city": "北京",
            "id": 3,
            "name": "故宫",
            "type": "博物馆/纪念馆",
            "lat": BJ_LAT,
            "lon": BJ_LON,
            "opentime": "08:30",
            "endtime": "17:00",
            "price": 60.0,
            "recommendmintime": 2.0,
            "recommendmaxtime": 4.0,
        },
        {
            "language": "zh",
            "city": "重庆",
            "id": 7,
            "name": "洪崖洞",
            "type": "观景台/地标",
            "lat": 29.5628,
            "lon": 106.5786,
            "opentime": "00:00",
            "endtime": "23:59",
            "price": 0.0,
            "recommendmintime": 1.0,
            "recommendmaxtime": 2.0,
        },
        {
            "language": "zh",
            "city": "火星市",
            "id": 9,
            "name": "火星基地",
            "type": "其他",
            "lat": 10.0,
            "lon": 20.0,
            "opentime": None,
            "endtime": None,
            "price": None,
            "recommendmintime": None,
            "recommendmaxtime": None,
        },
    ]


def _write_parquet(tmp_path, rows, name="ct.parquet") -> str:
    path = tmp_path / name
    pd.DataFrame(rows).to_parquet(path)
    return str(path)


def _run(
    capsys,
    parquet,
    *,
    kind="attraction",
    seed=None,
    amap=None,
    extra=(),
    ping_ok=True,
):
    seed = SeedStub() if seed is None else seed
    rc = job.main(
        ["--parquet", parquet, "--kind", kind, *extra],
        seed=seed,
        session_factory=object(),
        amap=amap,
        ping=(lambda: True) if ping_ok else (lambda: False),
    )
    stats = json.loads(capsys.readouterr().out)
    return rc, seed, stats


def test_city_filter_and_stats(tmp_path, capsys):
    path = _write_parquet(tmp_path, _base_rows())
    rc, seed, stats = _run(capsys, path, extra=("--assume", "gcj02"))
    assert rc == 0
    assert stats["read"] == 3
    assert stats["skipped_city"] == 1  # 火星市被滤掉
    assert stats["imported"] == 2
    assert stats["exists"] == 0
    assert set(stats["per_city"]) == {"北京", "重庆"}
    assert stats["per_city"]["北京"] == {"imported": 1, "exists": 0}
    assert stats["read"] == stats["imported"] + stats["exists"] + stats["skipped"]
    assert all(kwargs["city"] != "火星市" for _, kwargs in seed.calls)


def test_source_poi_id_format(tmp_path, capsys):
    path = _write_parquet(tmp_path, _base_rows())
    rc, seed, _ = _run(capsys, path, extra=("--assume", "gcj02"))
    assert rc == 0
    model, kwargs = seed.calls[0]
    assert model is Poi
    assert kwargs["source"] == "chinatravel"
    assert kwargs["source_poi_id"] == "ct_北京_3"
    assert kwargs["origin"] == "chinatravel"
    assert kwargs["name_zh"] == "故宫"
    assert seed.calls[1][1]["source_poi_id"] == "ct_重庆_7"


def test_time_fields_never_written(tmp_path, capsys):
    path = _write_parquet(tmp_path, _base_rows())
    rc, seed, _ = _run(capsys, path, extra=("--assume", "gcj02"))
    assert rc == 0
    assert len(seed.calls) == 2
    for _, kwargs in seed.calls:
        assert not (set(TIME_COLS) & set(kwargs))


def test_gcj02_assume_no_conversion(tmp_path, capsys):
    path = _write_parquet(tmp_path, _base_rows())
    rc, seed, stats = _run(capsys, path, extra=("--assume", "gcj02"))
    assert rc == 0
    assert stats["coord_system"] == "gcj02"
    assert stats["assumed"] is False
    _, kwargs = seed.calls[0]
    assert kwargs["lonlat"] == (BJ_LON, BJ_LAT)  # 原样入库
    assert "wgs84_lonlat" not in kwargs


def test_wgs84_assume_converts(tmp_path, capsys):
    path = _write_parquet(tmp_path, _base_rows())
    rc, seed, stats = _run(capsys, path, extra=("--assume", "wgs84"))
    assert rc == 0
    assert stats["coord_system"] == "wgs84"
    _, kwargs = seed.calls[0]
    assert kwargs["wgs84_lonlat"] == (BJ_LON, BJ_LAT)  # 原始值留存
    converted = kwargs["lonlat"]
    expected = wgs84_to_gcj02(BJ_LON, BJ_LAT)
    assert math.isclose(converted[0], expected[0], abs_tol=1e-9)
    assert math.isclose(converted[1], expected[1], abs_tol=1e-9)
    assert converted != (BJ_LON, BJ_LAT)  # 坐标变了


def test_auto_judge_gcj02(tmp_path, capsys):
    # 高德回查坐标与源一致（<50m）→ 判 GCJ-02，不转换
    amap = AmapStub({"北京故宫": (BJ_LON, BJ_LAT), "重庆洪崖洞": (106.5786, 29.5628)})
    path = _write_parquet(tmp_path, _base_rows())
    rc, seed, stats = _run(capsys, path, amap=amap)
    assert rc == 0
    assert stats["coord_system"] == "gcj02"
    assert stats["assumed"] is False
    assert amap.calls[0] == ("北京故宫", "北京")
    _, kwargs = seed.calls[0]
    assert kwargs["lonlat"] == (BJ_LON, BJ_LAT)
    assert "wgs84_lonlat" not in kwargs


def test_auto_judge_wgs84(tmp_path, capsys):
    # 高德回查坐标偏 ~850m（>150m）→ 源是 WGS84，需转换
    amap = AmapStub(
        {
            "北京故宫": (BJ_LON + 0.01, BJ_LAT),
            "重庆洪崖洞": (106.5886, 29.5628),
        }
    )
    path = _write_parquet(tmp_path, _base_rows())
    rc, seed, stats = _run(capsys, path, amap=amap)
    assert rc == 0
    assert stats["coord_system"] == "wgs84"
    assert stats["assumed"] is False
    _, kwargs = seed.calls[0]
    assert kwargs["wgs84_lonlat"] == (BJ_LON, BJ_LAT)
    assert kwargs["lonlat"] != (BJ_LON, BJ_LAT)


def test_auto_no_amap_assumed_wgs84(tmp_path, capsys, monkeypatch):
    # auto 默认但高德不可用 → 退 WGS84 假设 + assumed 标记
    monkeypatch.setattr(job, "_default_amap", lambda: None)
    path = _write_parquet(tmp_path, _base_rows())
    rc, _, stats = _run(capsys, path, amap=None)
    assert rc == 0
    assert stats["coord_system"] == "wgs84"
    assert stats["assumed"] is True


def test_judge_coords_branches():
    samples = [("北京", "故宫", BJ_LON, BJ_LAT)]
    near = AmapStub({"北京故宫": (BJ_LON, BJ_LAT)})  # 0m < 50m
    assert asyncio.run(job._judge_coords(samples, near)) == "gcj02"
    far = AmapStub({"北京故宫": (BJ_LON + 0.01, BJ_LAT)})  # ~853m > 150m
    assert asyncio.run(job._judge_coords(samples, far)) == "wgs84"


def test_judge_coords_uncertain():
    # 偏 ~85m（50-150m 之间）→ uncertain
    amap = AmapStub({"北京故宫": (BJ_LON + 0.001, BJ_LAT)})
    samples = [("北京", "故宫", BJ_LON, BJ_LAT)]
    assert asyncio.run(job._judge_coords(samples, amap)) == "uncertain"


def test_judge_coords_no_hits_is_uncertain():
    class Empty(AmapStub):
        async def search_poi(self, keywords, *, city=None, page=1):
            return []

    samples = [("北京", "故宫", BJ_LON, BJ_LAT)]
    assert asyncio.run(job._judge_coords(samples, Empty({}))) == "uncertain"


def test_restaurant_kind_uses_restaurant_model(tmp_path, capsys):
    # poi_zh 同构：无 type 列（有 id）
    rows = [
        {
            "language": "zh",
            "city": "成都",
            "id": 5,
            "name": "小龙坎",
            "lat": 30.57,
            "lon": 104.06,
            "opentime": "10:00",
        }
    ]
    path = _write_parquet(tmp_path, rows)
    rc, seed, stats = _run(capsys, path, kind="restaurant", extra=("--assume", "gcj02"))
    assert rc == 0
    model, kwargs = seed.calls[0]
    assert model is Restaurant
    assert kwargs["category"] is None  # 无 type 列 → 归一后 None
    assert kwargs["source_poi_id"] == "ct_成都_5"


def test_no_id_column_falls_back_to_row_label(tmp_path, capsys):
    # poi_zh.parquet 真实形态：无 id 列 → 文件行号做稳定伪 id
    rows = [
        {
            "language": "zh",
            "city": "北京",
            "name": "北京站",
            "lat": 39.9028,
            "lon": 116.4279,
        },
        {
            "language": "zh",
            "city": "北京",
            "name": "天安门",
            "lat": 39.9087,
            "lon": 116.3975,
        },
    ]
    path = _write_parquet(tmp_path, rows)
    rc, seed, stats = _run(capsys, path, extra=("--assume", "gcj02"))
    assert rc == 0
    assert stats["imported"] == 2
    assert seed.calls[0][1]["source_poi_id"] == "ct_北京_0"
    assert seed.calls[1][1]["source_poi_id"] == "ct_北京_1"


def test_ping_gate_blocks(tmp_path, capsys):
    path = _write_parquet(tmp_path, _base_rows())
    rc, seed, stats = _run(capsys, path, ping_ok=False)
    assert rc == 1
    assert "error" in stats
    assert seed.calls == []


def test_missing_parquet(tmp_path, capsys):
    rc, _, stats = _run(capsys, str(tmp_path / "nope.parquet"))
    assert rc == 1
    assert "error" in stats


def test_zero_rows_after_filter_hint(tmp_path, capsys):
    rows = [
        {
            "language": "zh",
            "city": "火星市",
            "id": 1,
            "name": "x",
            "lat": 1.0,
            "lon": 1.0,
        }
    ]
    path = _write_parquet(tmp_path, rows)
    rc, seed, stats = _run(capsys, path, extra=("--assume", "gcj02"))
    assert rc == 0
    assert "hint" in stats
    assert stats["skipped_city"] == 1
    assert seed.calls == []


def test_limit_caps_rows(tmp_path, capsys):
    path = _write_parquet(tmp_path, _base_rows())
    rc, seed, stats = _run(capsys, path, extra=("--assume", "gcj02", "--limit", "1"))
    assert rc == 0
    assert len(seed.calls) == 1
    assert stats["imported"] == 1
