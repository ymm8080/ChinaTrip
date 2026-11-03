"""tag_star_hotels：星级饭店名单 -> pois.tags(star_1…star_5) 打标（backlog #11）。"""

import uuid

from app.jobs.tag_star_hotels import (
    collect_jobs,
    collect_jobs_prematched,
    make_star_tag,
    map_row,
    parse_star,
    plan_tags,
    row_matches,
    tag_hotels,
    tag_hotels_prematched,
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


def test_parse_star_accepts_full_vocab_down_to_one_star():
    # 2026-11-03 用户拍板全档词表：三星/二星/一星也要落库
    assert parse_star("3") == 3
    assert parse_star("三星") == 3
    assert parse_star("三星级") == 3
    assert parse_star("★★★") == 3
    assert parse_star("2") == 2
    assert parse_star("二星") == 2
    assert parse_star("★★") == 2
    assert parse_star("1") == 1
    assert parse_star("一星级") == 1
    assert parse_star("★") == 1


def test_parse_star_rejects_junk_and_out_of_range():
    # 空、乱码、六星以上、0 星一律不打标（词表只有 1..5）
    assert parse_star("") is None
    assert parse_star(None) is None
    assert parse_star("金牌") is None
    assert parse_star("六星") is None
    assert parse_star("六星级") is None
    assert parse_star("0") is None
    assert parse_star("★★★★★★") is None


def test_make_star_tag_vocab():
    assert make_star_tag(5) == "star_5"
    assert make_star_tag(4) == "star_4"
    assert make_star_tag(3) == "star_3"
    assert make_star_tag(2) == "star_2"
    assert make_star_tag(1) == "star_1"
    assert make_star_tag(6) is None
    assert make_star_tag(0) is None
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
    # 全覆盖：三星升五星、五星降一星都不并存
    low = _mk_hotel("y", "北京", tags=["star_3", "amap_top"])
    assert plan_tags(low, "star_5") == ["amap_top", "star_5"]
    high = _mk_hotel("z", "北京", tags=["star_5"])
    assert plan_tags(high, "star_1") == ["star_1"]


def test_plan_tags_idempotent_when_present():
    row = _mk_hotel("x", "北京", tags=["star_5"])
    assert plan_tags(row, "star_5") is None


# ---------- tag_hotels：假 session 主流程 ----------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_criterion):
        return self  # 城市/类别过滤由 row_matches 与夹具兜底

    def filter_by(self, **kw):
        out = [
            r
            for r in self._rows
            if all(getattr(r, k, None) == v for k, v in kw.items())
        ]
        return _FakeQuery(out)  # prematched 按 id 查行走这里

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None


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


def test_collect_jobs_bom_columns_limit_and_full_vocab(tmp_path):
    p = tmp_path / "stars.csv"
    p.write_text(
        "\ufeff城市,酒店名称,星级\n北京,北京饭店,五星\n上海,某三星宾馆,三星\n"
        "广州,白天鹅宾馆,5\n杭州,某废店,金牌\n",
        encoding="utf-8",
    )
    jobs, stats = collect_jobs(str(p), limit=4)
    assert stats["read"] == 4
    assert stats["no_qualifying_star"] == 1
    assert stats["no_star_detail"][0]["name"] == "某废店"
    # 三星已在词表内（2026-11-03 全档拍板）
    assert [j["tag"] for j in jobs] == ["star_5", "star_3", "star_5"]
    assert jobs[0]["entry"]["city"] == "北京"


# ---------- 审阅包（--prematched）模式：审阅包即决定记录，按 poi_id 执行 ----------


def _prematched_csv(tmp_path, lines):
    header = "星级,市区(名单口径),饭店名称,预匹配状态,库内poi_id,库内city\n"
    p = tmp_path / "review.csv"
    p.write_text("\ufeff" + header + "".join(lines), encoding="utf-8")
    return str(p)


def test_collect_prematched_splits_branches(tmp_path):
    path = _prematched_csv(
        tmp_path,
        [
            "5,东城区,北京饭店,命中,11111111-1111-1111-1111-111111111111,北京\n",
            "4,朝阳区,某四星,命中(城市待核),22222222-2222-2222-2222-222222222222,北京\n",
            "5,东城区,未入库五星,未在库,,北京\n",
            "3,海淀区,某三星,命中,33333333-3333-3333-3333-333333333333,北京\n",
            "1,海淀区,某一星,命中,44444444-4444-4444-4444-444444444444,北京\n",
            "六星,海淀区,某废店,命中,55555555-5555-5555-5555-555555555555,北京\n",
            "5,东城区,,命中,,北京\n",  # 无名称=无效行
        ],
    )
    jobs, stats = collect_jobs_prematched(path)
    assert stats["read"] == 7 and stats["invalid"] == 1
    assert stats["not_in_library"] == 1  # 未在库五星：无行可标，不建骨架
    assert stats["no_qualifying_star"] == 1  # 六星：词表外
    assert [j["tag"] for j in jobs] == [
        "star_5",
        "star_4",
        "star_3",
        "star_1",
    ]
    # 状态注记原样保留（命中(城市待核) 等留给审阅人看）
    assert jobs[1]["entry"]["status"] == "命中(城市待核)"


def _with_id(row, hex_str):
    row.id = uuid.UUID(hex_str)
    return row


def _pjob(poi_id, name, tag="star_5", status="命中"):
    return {
        "entry": {
            "name": name,
            "city": "北京",
            "star": 5,
            "status": status,
            "poi_id": poi_id,
        },
        "tag": tag,
    }


def test_tag_prematched_tags_by_poi_id_dry_run_never_commits():
    row = _with_id(
        _mk_hotel("北京饭店", "北京市"), "11111111-1111-1111-1111-111111111111"
    )
    factory = _fake_factory([row])
    stats = tag_hotels_prematched(
        factory,
        [_pjob("11111111-1111-1111-1111-111111111111", "北京饭店")],
        tags_source="mct",
    )
    assert stats["mode"] == "dry-run"
    assert stats["matched"] == 1 and stats["tagged_rows"] == 1
    assert factory.created[0].commit_count == 0
    assert stats["tagged_detail"][0]["tag"] == "star_5"


def test_tag_prematched_apply_commits_per_row_and_swaps_star():
    row_a = _with_id(
        _mk_hotel("北京饭店", "北京市"), "11111111-1111-1111-1111-111111111111"
    )
    row_b = _with_id(
        _mk_hotel("上海和平饭店", "上海市", tags=["star_4"]),
        "22222222-2222-2222-2222-222222222222",
    )
    factory = _fake_factory([row_a, row_b])
    jobs = [
        _pjob("11111111-1111-1111-1111-111111111111", "北京饭店"),
        _pjob(
            "22222222-2222-2222-2222-222222222222",
            "上海和平饭店",
            status="命中(别名/去括号)",
        ),
    ]
    stats = tag_hotels_prematched(factory, jobs, tags_source="mct", apply=True)
    assert stats["tagged_rows"] == 2
    assert row_a.tags == ["star_5"] and row_a.tags_source == "mct"
    assert row_b.tags == ["star_5"]  # 升星互斥替换
    assert factory.created[0].commit_count == 3  # 2 行逐条 + 收尾


def test_tag_prematched_guards_poi_id_not_found_and_bad_uuid():
    row = _with_id(
        _mk_hotel("北京饭店", "北京市"), "11111111-1111-1111-1111-111111111111"
    )
    factory = _fake_factory([row])
    jobs = [
        _pjob("99999999-9999-9999-9999-999999999999", "查无此店"),
        _pjob("not-a-uuid", "坏uuid", tag="star_4"),
    ]
    stats = tag_hotels_prematched(factory, jobs, tags_source="mct", apply=True)
    assert stats["matched"] == 0 and stats["not_found"] == 2
    reasons = {d["reason"] for d in stats["skipped_detail"]}
    assert reasons == {"poi_id_not_found", "bad_poi_id"}
    assert factory.created[0].commit_count == 1  # 仅收尾


def test_tag_prematched_refuses_non_active_hotel_rows():
    wrong_cat = _with_id(
        _mk_hotel("误配餐厅", "北京市"), "11111111-1111-1111-1111-111111111111"
    )
    wrong_cat.category = "restaurant"
    hidden = _with_id(
        _mk_hotel("软删饭店", "北京市"), "22222222-2222-2222-2222-222222222222"
    )
    hidden.status = "hidden"
    factory = _fake_factory([wrong_cat, hidden])
    jobs = [
        _pjob("11111111-1111-1111-1111-111111111111", "误配餐厅"),
        _pjob("22222222-2222-2222-2222-222222222222", "软删饭店"),
    ]
    stats = tag_hotels_prematched(factory, jobs, tags_source="mct")
    assert stats["matched"] == 0 and stats["non_hotel"] == 2
    assert wrong_cat.tags is None and hidden.tags is None  # 守卫不写


def test_tag_prematched_rerun_idempotent_and_official_guard():
    poi_id = "11111111-1111-1111-1111-111111111111"
    row = _with_id(
        _mk_hotel("北京饭店", "北京市", tags=["star_5"], tags_source="mct"), poi_id
    )
    factory = _fake_factory([row])
    job = [_pjob(poi_id, "北京饭店")]
    stats = tag_hotels_prematched(factory, job, tags_source="mct", apply=True)
    assert stats["already_ok"] == 1 and stats["tagged_rows"] == 0
    # glm 市场口径不得改写已持 mct 的行（不冒充官方）
    stats2 = tag_hotels_prematched(factory, job, tags_source="glm")
    assert stats2["kept_official"] == 1 and row.tags_source == "mct"
