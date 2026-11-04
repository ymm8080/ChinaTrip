"""tags_source 权威闸测试（2026-11-03 铁律「导入不降权威」）。

三处导入作业（import_intl_picks / import_intl_platforms / import_shows）
merge 既有行时：新归因权威（source_tier.TAGS_SOURCE_AUTHORITY，大值=高）
严格低于既有 tags_source 时不得改写归因列，tags 并集照写；市场归因行
（glm/ctrip/无归因）被正常接管。夹具沿用既有 import 测试的 FakeSession
内存态（pois 表带 JSONB/UUID/Geography 等 PG 专有列，纯 SQLite 建不出）。
"""

import uuid

import app.jobs.import_intl_picks as picks
import app.jobs.import_intl_platforms as platforms
import app.jobs.import_shows as shows
from app.models import Poi
from app.services.source_tier import TAGS_SOURCE_AUTHORITY, tags_source_wins


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


def _row(city, name, *, source="amap", tags=None, tags_source=None):
    return Poi(
        id=uuid.uuid4(),
        source=source,
        source_poi_id=f"{source}:{city}:{name}",
        city=city,
        name_zh=name,
        tags=tags,
        tags_source=tags_source,
    )


def _pick(city, name_zh, name_en, sites, aliases=""):
    return {
        "city": city,
        "name_zh": name_zh,
        "name_en": name_en,
        "sites": sites,
        "aliases": aliases,
    }


def _show_csv(city, name, ctrip=""):
    return {
        "name_zh": name,
        "province": "",
        "city": city,
        "show_type": "山水实景演出",
        "venue": "",
        "operator": "",
        "season_note": "",
        "ctrip_url": ctrip,
        "source_url": "",
        "remark": "",
    }


# --- 共享闸函数 ---------------------------------------------------------------


def test_gate_direction_official_beats_market():
    assert not tags_source_wins("ctrip", "mct")  # 商业站点不冒充官方
    assert not tags_source_wins("sygic", "mohurd")  # 未知源(0) < 官方(3)
    assert not tags_source_wins("show", "mct")  # show(2) 挡不住 mct(3)
    assert tags_source_wins("mct", "ctrip")  # 官方接管市场
    assert tags_source_wins("show", "glm")  # show 名录 > 市场口径
    assert tags_source_wins("sygic", None)  # 未知既有=0，放行接管
    assert tags_source_wins("mct", "mct")  # 相等放行（幂等重跑）
    assert TAGS_SOURCE_AUTHORITY["mct"] == TAGS_SOURCE_AUTHORITY["mohurd"] == 3


# --- import_intl_picks：官方归因保持 + tags 并集照写 -------------------------


def test_intl_picks_never_demotes_official_but_writes_tags_union():
    row = _row(
        "北京",
        "故宫博物院",
        source="5a",
        tags=["unesco", "5a"],
        tags_source="mct",
    )
    s = FakeSession([row])
    stats = picks.apply_picks(s)
    assert stats["merge"] >= 1
    assert {"intl", "ta", "lp"} <= set(row.tags)  # tags 并集照写
    assert row.tags_source == "mct"  # 商业站点归因不冒充官方


def test_intl_picks_rerun_idempotent_no_repeat_writes():
    row = _row(
        "北京",
        "故宫博物院",
        source="5a",
        tags=["unesco", "5a"],
        tags_source="mct",
    )
    s = FakeSession([row])
    first = picks.apply_picks(s)
    assert first["merge"] >= 1
    # 第二跑：tags 无变化 + 闸挡住归因 → skip，不重复写
    second = picks.apply_picks(s)
    assert second["insert"] == 0 and second["merge"] == 0
    assert second["skip"] >= 1
    assert row.tags_source == "mct"


def test_intl_picks_unattributed_row_taken_over():
    row = _row(
        "北京",
        "故宫博物院",
        source="ctrip",
        tags=["unesco", "5a"],
        tags_source=None,
    )
    s = FakeSession([row])
    picks.apply_picks(s)
    assert row.tags_source == "tripadvisor"  # 无归因(0)与明细站点(0)平权放行


def test_intl_picks_extraction_attribution_not_demoted():
    # ctrip(1)/glm(1) 是市场口径抽取归因，高于明细站点(未知=0)：不降
    row = _row(
        "北京",
        "故宫博物院",
        source="ctrip",
        tags=["unesco", "5a"],
        tags_source="ctrip",
    )
    s = FakeSession([row])
    stats = picks.apply_picks(s)
    assert stats["merge"] >= 1
    assert {"intl", "ta", "lp"} <= set(row.tags)  # tags 并集照写
    assert row.tags_source == "ctrip"  # tripadvisor(0) 不降 ctrip(1)


# --- import_intl_platforms：同款闸 -------------------------------------------


def test_intl_platforms_never_demotes_official_but_writes_tags_union():
    row = _row("北京", "故宫", source="museum1", tags=["ta"], tags_source="mohurd")
    s = FakeSession([row])
    stats = platforms.apply_rows(
        s, [_pick("北京", "故宫", "Forbidden City", "sygic;klook")], dry_run=True
    )
    assert stats["merge"] == 1
    assert {"sygic", "klook", "intl"} <= set(row.tags)  # tags 并集照写
    assert row.tags_source == "mohurd"  # 平台站点归因不降官方名录


def test_intl_platforms_rerun_idempotent_and_market_takeover():
    row = _row("北京", "故宫", source="museum1", tags=["ta"], tags_source="mohurd")
    s = FakeSession([row])
    pick = _pick("北京", "故宫", "Forbidden City", "sygic;klook")
    platforms.apply_rows(s, [pick], dry_run=True)
    assert row.tags_source == "mohurd"
    # 第二跑：无变化 + 闸挡住归因 → skip，不重复写
    second = platforms.apply_rows(s, [pick], dry_run=True)
    assert second["merge"] == 0 and second["skip"] == 1
    assert row.tags_source == "mohurd"
    # 无归因行被平台站点接管（未知源平权放行）
    mkt = _row("北京", "天坛", source="5a", tags=["5a"], tags_source=None)
    s2 = FakeSession([mkt])
    platforms.apply_rows(
        s2, [_pick("北京", "天坛", "Temple of Heaven", "layla")], dry_run=True
    )
    assert "layla" in mkt.tags
    assert mkt.tags_source == "layla"
    # glm/ctrip 抽取归因(1)高于平台站点(0)：不被降权
    extract_row = _row("北京", "北海公园", source="5a", tags=["5a"], tags_source="glm")
    s3 = FakeSession([extract_row])
    platforms.apply_rows(
        s3, [_pick("北京", "北海公园", "Beihai Park", "klook")], dry_run=True
    )
    assert "klook" in extract_row.tags
    assert extract_row.tags_source == "glm"


# --- import_shows：show(2) 挡不住 mct/mohurd(3) -------------------------------


def test_shows_never_demotes_official_but_writes_tags_union():
    hit = _row("西安", "长恨歌", source="amap", tags=["5a"], tags_source="mct")
    s = FakeSession([hit])
    stats = shows.apply_rows(s, [_show_csv("西安", "《长恨歌》演出")], dry_run=True)
    assert stats["merge"] == 1
    assert "show" in hit.tags and "5a" in hit.tags  # tags 并集照写
    assert hit.tags_source == "mct"  # show(2) 不降 mct(3)


def test_shows_gate_does_not_block_url_fill():
    hit = _row("西安", "长恨歌", source="amap", tags=["5a"], tags_source="mohurd")
    s = FakeSession([hit])
    stats = shows.apply_rows(
        s,
        [
            _show_csv(
                "西安", "《长恨歌》演出", ctrip="https://gs.ctrip.com/sight/9.html"
            )
        ],
        dry_run=True,
    )
    assert stats["merge"] == 1
    assert hit.booking_url == "https://gs.ctrip.com/sight/9.html"  # 只填空不受闸
    assert "show" in hit.tags
    assert hit.tags_source == "mohurd"  # 归因列保持官方


def test_shows_rerun_idempotent_and_market_takeover():
    hit = _row("西安", "长恨歌", source="amap", tags=["5a"], tags_source="mct")
    s = FakeSession([hit])
    rows = [_show_csv("西安", "《长恨歌》演出")]
    shows.apply_rows(s, rows)
    assert hit.tags_source == "mct"
    # 第二跑：tags/url/别名均无变化 + 闸挡住归因 → skip，不重复写
    second = shows.apply_rows(s, rows)
    assert second["insert"] == 0 and second["merge"] == 0 and second["skip"] == 1
    assert hit.tags_source == "mct"
    # 市场归因行被 show 正常接管（show 2 > glm 1）
    mkt = _row("杭州", "宋城千古情", source="ctrip", tags_source="glm")
    s2 = FakeSession([mkt])
    shows.apply_rows(s2, [_show_csv("杭州", "宋城千古情")])
    assert "show" in mkt.tags
    assert mkt.tags_source == "show"
