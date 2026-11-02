"""tag_star_hotels：星级饭店名单 -> pois.tags(star_5/star_4) 打标（backlog #11）。"""

import uuid

from app.jobs.tag_star_hotels import (
    collect_jobs,
    make_star_tag,
    map_row,
    parse_star,
    plan_tags,
    row_matches,
    tag_hotels,
)
from app.models import Poi

# ---------- 纯函数 ----------


def test_parse_star_accepts_official_spellings():
    assert parse_star("5") == 5
    assert parse_star("4") == 4
    assert parse_star("五星") == 5
    assert parse_star("四星级") == 4
    assert parse_star("5星") == 5
    assert parse_star("★★★★★") == 5
    assert parse_star("★★★★") == 4


def test_parse_star_rejects_out_of_vocab():
    # 设计只落 star_5/star_4：三星及以下、空、乱码一律不打标
    assert parse_star("3") is None
    assert parse_star("三星") is None
    assert parse_star("★★★") is None
    assert parse_star("") is None
    assert parse_star(None) is None
    assert parse_star("金牌") is None


def test_make_star_tag_vocab():
    assert make_star_tag(5) == "star_5"
    assert make_star_tag(4) == "star_4"
    assert make_star_tag(3) is None
    assert make_star_tag(None) is None


def test_map_row_chinese_columns():
    entry = map_row({"酒店名称": " 北京饭店 ", "城市": "北京市", "星级": "五星级"})
    assert entry == {"name": "北京饭店", "city": "北京市", "star": 5}


def test_map_row_missing_city_or_name_invalid():
    assert map_row({"name": "某酒店", "star": "5"}) is None
    assert map_row({"city": "北京", "star": "5"}) is None


# ---------- 匹配 ----------


def _mk_hotel(
    name_zh, city, *, tags=None, tags_source=None, name_en=None, aliases=None
):
    return Poi(
        id=uuid.uuid4(),
        source="amap",
        source_poi_id=f"h_{uuid.uuid4().hex[:8]}",
        city=city,
        name_zh=name_zh,
        name_en=name_en,
        name_aliases=aliases,
        category="hotel",
        status="active",
        tags=tags,
        tags_source=tags_source,
    )


def test_row_matches_english_city_alias_normalized():
    row = _mk_hotel("北京饭店", "北京市", name_en="Beijing Hotel")
    assert row_matches({"name": "Beijing Hotel", "city": "Beijing"}, row) is True


def test_row_matches_via_alias_and_bracket_strip():
    row = _mk_hotel("王府井希尔顿酒店", "北京", aliases=["北京王府井希尔顿酒店"])
    assert (
        row_matches({"name": "北京王府井希尔顿酒店（五星）", "city": "北京市"}, row)
        is True
    )


def test_row_matches_rejects_other_city_and_weak_name():
    row = _mk_hotel("北京饭店", "北京市")
    assert row_matches({"name": "北京饭店", "city": "上海"}, row) is False
    # 「北京饭店」vs「北京大酒店」是两家店，严阈值 0.85 下不得串
    assert row_matches({"name": "北京大酒店", "city": "北京"}, row) is False


def test_row_matches_tolerates_same_city_prefix_either_side():
    # 官方名单常带城市前缀而库行不带（或相反）；城市已核验，前缀不参与比对
    assert row_matches(
        {"name": "和平饭店", "city": "上海"}, _mk_hotel("上海和平饭店", "上海市")
    )
    assert row_matches(
        {"name": "上海和平饭店", "city": "上海市"}, _mk_hotel("和平饭店", "上海")
    )
    # 但去前缀不能把不同店拉成同店
    assert not row_matches(
        {"name": "上海花园饭店", "city": "上海"}, _mk_hotel("和平饭店", "上海")
    )


# ---------- plan_tags：互斥 + 幂等 ----------


def test_plan_tags_appends_and_keeps_others():
    row = _mk_hotel("x", "北京", tags=["amap_top"])
    assert plan_tags(row, "star_5") == ["amap_top", "star_5"]


def test_plan_tags_swaps_star_level_exclusively():
    row = _mk_hotel("x", "北京", tags=["star_4", "amap_top"])
    assert plan_tags(row, "star_5") == ["amap_top", "star_5"]


def test_plan_tags_idempotent_when_present():
    row = _mk_hotel("x", "北京", tags=["star_5"])
    assert plan_tags(row, "star_5") is None


# ---------- tag_hotels：假 session 主流程 ----------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_criterion):
        return self  # 城市/类别过滤由 row_matches 与夹具兜底

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.added: list = []
        self.commit_count = 0

    def query(self, *_cols):
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


def _job(name, city, tag):
    return {"entry": {"name": name, "city": city, "star": 5}, "tag": tag}


def test_tag_hotels_dry_run_reports_but_never_commits():
    row = _mk_hotel("北京饭店", "北京市", tags=["amap_top"])
    factory = _fake_factory([row])
    stats = tag_hotels(factory, [_job("北京饭店", "北京", "star_5")], tags_source="mct")
    assert stats["mode"] == "dry-run"
    assert stats["matched"] == 1 and stats["tagged_rows"] == 1
    assert factory.created[0].commit_count == 0
    # dry-run 仍在内存对象上标记（便于报告），但不 commit
    assert stats["tagged_detail"][0]["tag"] == "star_5"


def test_tag_hotels_apply_commits_per_row_and_tags():
    rows = [
        _mk_hotel("北京饭店", "北京市"),
        _mk_hotel("上海和平饭店", "上海市", tags=["star_4"]),
    ]
    factory = _fake_factory(rows)
    jobs = [_job("北京饭店", "北京", "star_5"), _job("和平饭店", "上海", "star_5")]
    stats = tag_hotels(factory, jobs, tags_source="mct", apply=True)
    assert stats["mode"] == "apply"
    assert stats["tagged_rows"] == 2
    assert rows[0].tags == ["star_5"] and rows[0].tags_source == "mct"
    # 升星：star_4 被替换，不并存
    assert rows[1].tags == ["star_5"]
    # 逐行 commit（2 行）+ 收尾 1 次
    assert factory.created[0].commit_count == 3


def test_tag_hotels_rerun_is_idempotent():
    row = _mk_hotel("北京饭店", "北京市", tags=["star_5"], tags_source="mct")
    factory = _fake_factory([row])
    stats = tag_hotels(
        factory, [_job("北京饭店", "北京", "star_5")], tags_source="mct", apply=True
    )
    assert stats["matched"] == 1
    assert stats["tagged_rows"] == 0 and stats["already_ok"] == 1
    assert factory.created[0].commit_count == 1  # 仅收尾 commit，无脏写


def test_tag_hotels_low_authority_source_never_overrides_official():
    # 行已是 mct 官方标，glm 市场口径不得改写 tags_source（不冒充官方）
    row = _mk_hotel("北京饭店", "北京市", tags=["star_5"], tags_source="mct")
    factory = _fake_factory([row])
    stats = tag_hotels(factory, [_job("北京饭店", "北京", "star_5")], tags_source="glm")
    assert stats["kept_official"] == 1 and stats["tagged_rows"] == 0
    assert row.tags_source == "mct"


def test_tag_hotels_fills_missing_source_when_tag_present():
    row = _mk_hotel("北京饭店", "北京市", tags=["star_5"], tags_source=None)
    factory = _fake_factory([row])
    stats = tag_hotels(factory, [_job("北京饭店", "北京", "star_5")], tags_source="mct")
    assert stats["tagged_rows"] == 1
    assert row.tags == ["star_5"] and row.tags_source == "mct"


def test_tag_hotels_unmatched_goes_to_review_and_never_creates_rows():
    factory = _fake_factory([_mk_hotel("北京饭店", "北京市")])
    stats = tag_hotels(
        factory, [_job("不存在的酒店", "北京", "star_4")], tags_source="mct", apply=True
    )
    assert stats["matched"] == 0 and stats["unmatched"] == 1
    assert stats["unmatched_detail"][0]["name"] == "不存在的酒店"
    # 只打标不建骨架行
    assert factory.created[0].added == []


# ---------- collect_jobs ----------


def test_collect_jobs_bom_columns_limit_and_out_of_vocab(tmp_path):
    p = tmp_path / "stars.csv"
    p.write_text(
        "\ufeff城市,酒店名称,星级\n北京,北京饭店,五星\n上海,某三星宾馆,三星\n广州,白天鹅宾馆,5\n杭州,无名,4\n",
        encoding="utf-8",
    )
    jobs, stats = collect_jobs(str(p), limit=3)
    assert stats["read"] == 3
    assert stats["no_qualifying_star"] == 1
    assert stats["no_star_detail"][0]["name"] == "某三星宾馆"
    assert [j["tag"] for j in jobs] == ["star_5", "star_5"]
    assert jobs[0]["entry"]["city"] == "北京"
