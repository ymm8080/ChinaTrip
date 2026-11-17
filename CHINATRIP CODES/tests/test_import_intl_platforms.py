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


def test_dish_named_store_pick_skipped_not_inserted():
    """菜名店名不含「餐厅」字样的餐饮 pick 整行不入（2026-11-06 水盆羊肉
    案：崇辉澄城水盆羊肉(钟楼西一路总店) 曾插成 attraction 骨架进观光池
    被排成景点）。分店后缀（总店/分店/旗舰店/加盟店）也是闸标。"""
    s = FakeSession([])
    stats = job.apply_rows(
        s,
        [
            _pick(
                "西安",
                "崇辉澄城水盆羊肉(钟楼西一路总店)",
                "Chengcheng Shuipen Lamb",
                "layla",
            ),
            _pick("西安", "钟楼", "Bell Tower", "sygic"),
        ],
        dry_run=True,
    )
    assert stats["skip"] == 1 and stats["insert"] == 1
    assert all("水盆羊肉" not in r.name_zh for r in s.rows)


def test_branch_suffixed_row_not_merge_target():
    """已入库的菜名店（无「餐厅」字样、带分店后缀）也不是归并目标。"""
    row = _row("西安", "崇辉澄城水盆羊肉(钟楼西一路总店)", source="baidu")
    row.category = "food"
    s = FakeSession([row])
    stats = job.apply_rows(
        s, [_pick("西安", "崇辉澄城水盆羊肉", "Shuipen Lamb", "layla")], dry_run=True
    )
    assert stats["insert"] == 1 and stats["merge"] == 0
    assert row.tags is None  # 旧行不被打上 intl 标


def test_experience_venue_branch_rows_not_merge_targets():
    """体验类门店不挂街区荐点（2026-11-07 宽窄巷子/春熙路 12 行污染收口）：
    双向包含把 春熙路/锦里/田子坊 pick 错挂到 温泉/写真/鬼校/飞行影院
    门店上——荐点挂在街区上，不挂在该街区的门店上。"""
    spa = _row("成都", "汤悦温泉(春熙路)店", source="chinatravel")
    spa.category = "entertainment"
    hanfu = _row("成都", "沐云紫汉服体验写真(武侯锦里店)", source="chinatravel")
    hanfu.category = "entertainment"
    ghost = _row("成都", "长藤鬼校(春熙路IFS店)", source="chinatravel")
    ghost.category = "entertainment"
    flying = _row("上海", "飞跃上海(南京路步行街来福士店)", source="chinatravel")
    flying.category = "entertainment"
    s = FakeSession([spa, hanfu, ghost, flying])
    stats = job.apply_rows(
        s,
        [
            _pick("成都", "春熙路", "Chunxi Road", "layla"),
            _pick("成都", "锦里", "Jinli", "layla"),
            _pick("上海", "南京路步行街", "Nanjing Road", "kkday"),
        ],
        dry_run=True,
    )
    assert stats["merge"] == 0
    assert all(r.tags is None for r in (spa, hanfu, ghost, flying))


def test_hotel_branch_row_without_stay_word_not_merge_target():
    """酒店行 category 已挡（733c596），此例验证无分类字样的尾缀「店」行
    同样被闸（丽呈别院/梵隐类不带「酒店」后缀的登记名变体）。"""
    row = _row("上海", "丽呈别院(上海三甲新天地旅游度假区店)", source="chinatravel")
    row.category = "hotel"
    s = FakeSession([row])
    stats = job.apply_rows(
        s, [_pick("上海", "新天地", "Xintiandi", "sygic")], dry_run=True
    )
    assert stats["insert"] == 1 and stats["merge"] == 0
    assert row.tags is None
