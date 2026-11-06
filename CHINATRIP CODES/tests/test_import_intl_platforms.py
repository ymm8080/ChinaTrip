"""intl 平台荐点导入作业测试（无 DB，FakeSession 内存态）。"""

import uuid

import app.jobs.import_intl_platforms as job
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


def _row(city, name, *, source="amap", tags=None, aliases=None):
    return Poi(
        id=uuid.uuid4(),
        source=source,
        source_poi_id=f"{source}:{city}:{name}",
        city=city,
        name_zh=name,
        tags=tags,
        name_aliases=aliases,
    )


def _pick(city, name_zh, name_en, sites, aliases=""):
    return {
        "city": city,
        "name_zh": name_zh,
        "name_en": name_en,
        "sites": sites,
        "aliases": aliases,
    }


def test_merge_keeps_source_and_appends_site_tags():
    row = _row("北京", "故宫博物院", source="museum1", tags=["ta", "lp", "intl"])
    s = FakeSession([row])
    stats = job.apply_rows(
        s, [_pick("北京", "故宫", "Forbidden City", "sygic;klook")], dry_run=True
    )
    assert stats["merge"] == 1 and stats["insert"] == 0
    assert row.source == "museum1"  # source 列保留原值
    assert "sygic" in row.tags and "klook" in row.tags and "intl" in row.tags
    assert row.tags_source == "sygic"
    assert s.rolled_back and not s.committed


def test_containment_alias_hits_existing_row():
    """故宫↔故宫博物院、天坛↔天坛公园：缩写/全称跨源去重（用户 2026-10-27 指令）。"""
    row = _row("北京", "天坛公园", source="5a", tags=["5a"])
    s = FakeSession([row])
    stats = job.apply_rows(
        s, [_pick("北京", "天坛", "Temple of Heaven", "layla")], dry_run=True
    )
    assert stats["merge"] == 1 and stats["insert"] == 0
    assert row.source == "5a"
    assert "layla" in row.tags


def test_insert_new_row_when_no_hit():
    s = FakeSession([])
    stats = job.apply_rows(
        s,
        [_pick("西安", "长安十二时辰主题街区", "Chang'an Block", "sygic")],
        dry_run=True,
    )
    assert stats["insert"] == 1
    row = s.rows[0]
    assert row.source == "sygic"
    assert row.category == "attraction"
    assert "intl" in row.tags and "sygic" in row.tags
    assert row.source_poi_id.startswith("sygic:西安:")


def test_same_name_different_city_not_merged():
    """同名不同场馆（孙中山纪念馆 南京/广州 式）不受去重影响。"""
    row = _row("南京", "中山陵", source="amap")
    s = FakeSession([row])
    stats = job.apply_rows(
        s, [_pick("广州", "中山陵", "Sun Yat-sen Mausoleum", "klook")], dry_run=True
    )
    assert stats["insert"] == 1 and stats["merge"] == 0


def test_stay_food_rows_not_merge_targets():
    """住宿/餐饮行不做归并目标：磁器口 pick 不得挂到「磁器口地铁站店」酒店
    （2026-11-06 171 行酒店污染根修）。无其他命中时落 insert 而非 merge。"""
    hotel = _row("重庆", "恋磁逸客酒店(重庆磁器口地铁站店)", source="chinatravel")
    hotel.category = "hotel"
    hotel2 = _row("重庆", "重庆悦磁江景花园酒店(磁器口古镇店)", source="chinatravel")
    hotel2.category = "hotel"
    food = _row("成都", "饕林餐厅(春熙路店)", source="baidu")
    s = FakeSession([hotel, hotel2, food])
    stats = job.apply_rows(
        s,
        [
            _pick("重庆", "磁器口", "Ciqikou", "tui"),
            _pick("成都", "春熙路", "Chunxi Road", "layla"),
        ],
        dry_run=True,
    )
    assert stats["insert"] == 2 and stats["merge"] == 0
    assert hotel.tags is None and food.tags is None
    assert hotel.source == "chinatravel"  # source 列不动


def test_attraction_with_branch_word_still_merges_when_category_clean():
    """名字含地名但非住宿餐饮的行（如 古镇/街区/转运楼）仍是合法归并目标。"""
    row = _row("重庆", "重庆磁器口古镇", source="4a", tags=["4a"])
    row.category = "ancient_town"
    s = FakeSession([row])
    stats = job.apply_rows(s, [_pick("重庆", "磁器口", "Ciqikou", "tui")], dry_run=True)
    assert stats["merge"] == 1
    assert "intl" in row.tags and "tui" in row.tags
