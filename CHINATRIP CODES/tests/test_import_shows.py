"""演艺演出种子导入作业测试（无 DB，FakeSession 内存态）。"""

import uuid

import app.jobs.import_shows as job
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


def _row(city, name, *, source="amap", tags=None, aliases=None, booking_url=None):
    return Poi(
        id=uuid.uuid4(),
        source=source,
        source_poi_id=f"{source}:{city}:{name}",
        city=city,
        name_zh=name,
        tags=tags,
        name_aliases=aliases,
        booking_url=booking_url,
    )


def _csv(
    city,
    name,
    *,
    ctrip="",
    season="",
    session_time="",
    venue="",
    show_type="山水实景演出",
):
    return {
        "name_zh": name,
        "province": "",
        "city": city,
        "show_type": show_type,
        "venue": venue,
        "operator": "",
        "season_note": season,
        "ctrip_url": ctrip,
        "source_url": "",
        "remark": "",
        "session_time": session_time,
    }


# --- 裸名剥离 ----------------------------------------------------------------


def test_bare_name_strips_brackets_and_suffix():
    assert job.bare_name("《长恨歌》演出") == "长恨歌"
    assert job.bare_name("《驼铃传奇》秀") == "驼铃传奇"
    assert job.bare_name("西安千古情") == "西安千古情"
    assert job.bare_name("") is None


# --- 插入 --------------------------------------------------------------------


def test_insert_show_row_with_sku_url_and_evening_seed():
    s = FakeSession([])
    stats = job.apply_rows(
        s,
        [
            _csv(
                "西安",
                "《长恨歌》演出",
                ctrip="https://gs.ctrip.com/sight/136558.html",
                season="演出季约4–10月（冬季停演）",
            )
        ],  # noqa: E501
        dry_run=True,
    )
    assert stats["insert"] == 1
    row = s.rows[0]
    assert row.source == "show"
    assert row.source_poi_id.startswith("show:西安:")
    assert row.category == "entertainment"
    assert row.booking_url == "https://gs.ctrip.com/sight/136558.html"
    assert row.best_visit_time == "show"  # S5 晚间档触发键
    assert row.suggested_duration_min == job.SHOW_DURATION_MIN
    assert "show" in row.tags
    assert row.name_aliases == ["长恨歌"]  # 裸名别名（LLM/用户口语命中）
    # intro 组合（2026-11-07）：内容+场地+档期
    assert row.intro == "山水实景演出；演出季约4–10月（冬季停演）"
    assert row.intro_source == "show"
    assert row.opening_hours is None  # 本行 CSV 无 session_time
    assert s.rolled_back and not s.committed


def test_insert_carries_session_time_hours_and_venue():
    """2026-11-07 扩列：session_time → opening_hours 权威戳 + intro 场地。"""
    s = FakeSession([])
    job.apply_rows(
        s,
        [
            _csv(
                "西安",
                "《长恨歌》演出",
                session_time="仅夜场（约20:10/21:35两场）",
                venue="华清宫·九龙湖",
                season="演出季约4–10月",
            )
        ],
        dry_run=True,
    )
    row = s.rows[0]
    assert row.opening_hours == "仅夜场（约20:10/21:35两场）"
    assert row.hours_source == "show"
    assert row.hours_updated_at is not None
    assert row.intro == "山水实景演出；华清宫·九龙湖；演出季约4–10月"


# --- 等值合并 ----------------------------------------------------------------


def test_exact_name_merge_keeps_source_and_fills_url_only_if_empty():
    hit = _row("桂林", "印象刘三姐", source="ctrip", tags=["5a"], booking_url="")
    s = FakeSession([hit])
    stats = job.apply_rows(
        s,
        [_csv("桂林", "印象刘三姐", ctrip="https://gs.ctrip.com/sight/1.html")],
        dry_run=True,
    )
    assert stats["merge"] == 1
    assert hit.source == "ctrip"  # source 保留（活链不断）
    assert hit.booking_url == "https://gs.ctrip.com/sight/1.html"
    assert "show" in hit.tags and "5a" in hit.tags


def test_merge_does_not_overwrite_existing_booking_url():
    hit = _row("桂林", "印象刘三姐", source="amap", booking_url="https://old.example/u")
    s = FakeSession([hit])
    job.apply_rows(
        s,
        [_csv("桂林", "印象刘三姐", ctrip="https://gs.ctrip.com/sight/1.html")],
        dry_run=True,
    )
    assert hit.booking_url == "https://old.example/u"  # 只填空


def test_bare_alias_exact_hit_merges():
    """裸名等值命中：《长恨歌》演出 ↔ 库内已叫「长恨歌」的行。"""
    hit = _row("西安", "长恨歌", source="amap")
    s = FakeSession([hit])
    stats = job.apply_rows(
        s,
        [_csv("西安", "《长恨歌》演出", ctrip="https://gs.ctrip.com/sight/2.html")],
        dry_run=True,
    )
    assert stats["merge"] == 1 and "show" in hit.tags


# --- 防误合（演出 ≠ 所在景区） -------------------------------------------------


def test_scenic_area_not_merged_by_containment():
    """「西安千古情景区」≠ 演出「《西安千古情》」：不走包含匹配，分开两行。"""
    area = _row("西安", "西安千古情景区", source="5a", tags=["5a"])
    s = FakeSession([area])
    stats = job.apply_rows(
        s,
        [_csv("西安", "《西安千古情》", ctrip="https://gs.ctrip.com/sight/3.html")],
        dry_run=True,
    )
    assert stats["insert"] == 1 and stats["merge"] == 0
    assert "show" not in (area.tags or [])  # 景区行不被误标晚间档


def test_same_name_different_city_not_merged():
    hit = _row("杭州", "宋城千古情", source="amap")
    s = FakeSession([hit])
    stats = job.apply_rows(
        s,
        [_csv("三亚", "宋城千古情", ctrip="https://gs.ctrip.com/sight/4.html")],
        dry_run=True,
    )
    assert stats["insert"] == 1


# --- 幂等 --------------------------------------------------------------------


def test_rerun_is_idempotent():
    s = FakeSession([])
    rows = [_csv("西安", "《长恨歌》演出", ctrip="https://gs.ctrip.com/sight/5.html")]
    job.apply_rows(s, rows)
    stats2 = job.apply_rows(s, rows)
    assert stats2["insert"] == 0  # 同批重跑不二插（等值命中 → 无变化 skip）
    assert len([r for r in s.rows if r.source == "show"]) == 1


# --- 场次扩列（2026-11-07） -----------------------------------------------------


def test_merge_show_row_stamps_hours_and_rerun_skips():
    """本命行：10-31 手工场次补权威戳+冷却戳；齐备后重跑不再写。"""
    hit = _row("西安", "长恨歌", source="show", tags=["show"])
    hit.opening_hours = "仅夜场（约20:10/21:35两场）"
    s = FakeSession([hit])
    csv_row = _csv(
        "西安",
        "《长恨歌》演出",
        session_time="仅夜场（约20:10/21:35两场）",
        show_type="",
    )
    stats = job.apply_rows(s, [csv_row], dry_run=True)
    assert stats["merge"] == 1
    assert hit.hours_source == "show"
    assert hit.hours_updated_at is not None
    assert hit.opening_hours == "仅夜场（约20:10/21:35两场）"
    stats2 = job.apply_rows(s, [csv_row], dry_run=True)
    assert stats2["skip"] == 1 and stats2["merge"] == 0


def test_merge_show_row_refreshes_session_text():
    """本命行同源刷新：CSV 重核场次后覆盖旧文本。"""
    hit = _row("西安", "长恨歌", source="show", tags=["show"])
    hit.opening_hours = "仅夜场（约20:10一场）"
    hit.hours_source = "show"
    s = FakeSession([hit])
    job.apply_rows(
        s,
        [
            _csv(
                "西安",
                "《长恨歌》演出",
                session_time="仅夜场（约20:10/21:35两场）",
                show_type="",
            )
        ],
        dry_run=True,
    )
    assert hit.opening_hours == "仅夜场（约20:10/21:35两场）"


def test_merge_foreign_row_keeps_existing_hours():
    """他源行的图商场馆开放时间不被场次覆写（只填空纪律）。"""
    hit = _row("西安", "长恨歌", source="amap")
    hit.opening_hours = "08:00-18:00"
    s = FakeSession([hit])
    stats = job.apply_rows(
        s,
        [_csv("西安", "《长恨歌》演出", session_time="仅夜场", show_type="")],
        dry_run=True,
    )
    assert stats["merge"] == 1  # tags/别名照常并入
    assert hit.opening_hours == "08:00-18:00"
    assert hit.hours_source is None


def test_merge_foreign_row_fills_null_hours():
    hit = _row("西安", "长恨歌", source="amap")
    s = FakeSession([hit])
    job.apply_rows(
        s,
        [_csv("西安", "《长恨歌》演出", session_time="仅夜场", show_type="")],
        dry_run=True,
    )
    assert hit.opening_hours == "仅夜场"
    assert hit.hours_source == "show"


def test_intro_fill_null_only_and_show_source_upgrade():
    """intro 只填空；intro_source='show' 同源升级。"""
    hit = _row("西安", "长恨歌", source="amap")
    hit.intro = "手工简介"
    hit.intro_source = "ctrip"
    s = FakeSession([hit])
    job.apply_rows(s, [_csv("西安", "《长恨歌》演出")], dry_run=True)
    assert hit.intro == "手工简介"  # 他源归因不覆盖

    hit2 = _row("西安", "驼铃传奇", source="show", tags=["show"])
    hit2.intro = "旧show简介"
    hit2.intro_source = "show"
    s2 = FakeSession([hit2])
    job.apply_rows(
        s2, [_csv("西安", "《驼铃传奇》秀", show_type="室内行走演出")], dry_run=True
    )
    assert hit2.intro == "室内行走演出"  # 同源升级
