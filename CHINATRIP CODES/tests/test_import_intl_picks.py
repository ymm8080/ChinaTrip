"""intl 荐点种子导入作业测试（无 DB，FakeSession 内存态）。"""

import uuid

import app.jobs.import_intl_picks as job
from app.models import Poi


class FakeSession:
    def __init__(self, rows=None):
        self.rows: list[Poi] = list(rows or [])
        self.committed = False
        self.rolled_back = False

    def query(self, model):
        return self

    def all(self):
        return list(self.rows)

    def add(self, row):
        self.rows.append(row)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _row(city, name, *, source="amap", tags=None):
    return Poi(
        id=uuid.uuid4(),
        source=source,
        source_poi_id=f"{source}:{city}:{name}",
        city=city,
        name_zh=name,
        tags=tags,
    )


def test_insert_skeleton_carries_source_tags():
    s = FakeSession()
    stats = job.apply_picks(s)
    assert stats["errors"] == 0 and stats["insert"] > 0
    bund = next(r for r in s.rows if r.name_zh == "外滩" and r.source == "tripadvisor")
    assert bund.city == "上海"
    assert bund.name_en == "The Bund"
    assert bund.category == "attraction"
    assert {"intl", "ta", "lp"} <= set(bund.tags)
    assert bund.tags_source == "tripadvisor"
    assert bund.source_poi_id == "tripadvisor:上海:外滩"
    assert s.committed


def test_merge_onto_existing_exact_and_alias_keeps_source():
    existing_exact = _row("上海", "田子坊", source="amap")
    existing_alias = _row("北京", "天坛", source="5a", tags=["5a"])
    existing_twin = _row("北京", "天坛公园", source="ctrip")
    s = FakeSession([existing_exact, existing_alias, existing_twin])
    stats = job.apply_picks(s)
    # 正名/别名命中 → 只并标签，不改 source、不插重复行
    assert existing_exact.source == "amap"
    assert {"intl", "lp"} <= set(existing_exact.tags)
    assert existing_alias.source == "5a"
    assert {"5a", "intl", "ta", "lp"} <= set(existing_alias.tags)
    # 同名孪生行（天坛/天坛公园）统一打标，不因行序漏标
    assert existing_twin.source == "ctrip"
    assert {"intl", "ta", "lp"} <= set(existing_twin.tags)
    assert stats["merge"] >= 2
    # 两个既有行未被替换成 intl 行
    intl_dupes = [
        r for r in s.rows if r.source == "intl" and r.name_zh in ("田子坊", "天坛")
    ]
    assert intl_dupes == []
    assert existing_exact.tags_source == "lonelyplanet"  # 田子坊仅 lp 荐
    assert existing_alias.tags_source == "tripadvisor"  # 天坛 ta+lp → ta 主


def test_idempotent_second_run_is_all_skip():
    s = FakeSession()
    first = job.apply_picks(s)
    assert first["insert"] > 0
    second = job.apply_picks(s)
    assert second["insert"] == 0 and second["merge"] == 0
    assert second["skip"] == first["insert"] + first["merge"]


def test_subvenue_rows_untouched_and_canonical_inserted():
    """库里只有子场所行（洪崖洞重逢1980街区）时：子场所不打标，
    正名「洪崖洞民俗风貌区」插骨架——国际榜推荐的是正名景点。"""
    sub = _row("重庆", "洪崖洞重逢1980街区")
    s = FakeSession([sub])
    job.apply_picks(s)
    assert sub.tags is None
    canon = [
        r
        for r in s.rows
        if r.source == "tripadvisor" and r.name_zh == "洪崖洞民俗风貌区"
    ]
    assert len(canon) == 1


def test_legacy_intl_rows_upgraded_to_site_source():
    """旧版（2026-10-25）source='intl' 行重跑 → 升级为明细站点名，
    source_poi_id 同步重打键（2026-10-26 用户指令：不要笼统 intl）。"""
    legacy = Poi(
        id=uuid.uuid4(),
        source="intl",
        source_poi_id="intl:上海:外滩",
        city="上海",
        name_zh="外滩",
        tags=["intl", "ta", "lp"],
        tags_source="intl",
    )
    s = FakeSession([legacy])
    stats = job.apply_picks(s)
    assert stats["errors"] == 0
    assert sum(1 for r in s.rows if r.name_zh == "外滩") == 1
    assert legacy.source == "tripadvisor"
    assert legacy.source_poi_id == "tripadvisor:上海:外滩"
    assert legacy.tags_source == "tripadvisor"


def test_dry_run_rolls_back():
    s = FakeSession()
    stats = job.apply_picks(s, dry_run=True)
    assert stats["insert"] > 0
    assert s.rolled_back and not s.committed
