"""抢票日历/预约提示匹配守卫回归（2026-11-19 烤鸭店开抢误报修复）。

事故链：短键「故宫」⊂「四季民福烤鸭店（故宫店）」——L1 抢票日历把餐厅
名当放票任务（「2026-11-18 20:00 开抢 · 四季民福烤鸭店」）、行程卡
reservation_hint 挂故宫口径、09 表兜底吸判词。守卫四件套：剥括号注记/
城市/非游览设施词/长种子优先；精确名（正身）不设防。
"""

from app.services.reservation_seeds import (
    RESERVATION_V0,
    SEED_CITY_GUARD,
    match_reservation_csv_row,
    match_seed,
)

# --- 守卫完备性 --------------------------------------------------------------


def test_seed_city_guard_covers_every_seed():
    """新增种子必须同步登记城市白名单——守卫不静默失效。"""
    assert set(RESERVATION_V0) == set(SEED_CITY_GUARD)


# --- 误报面：分支店名 / 无括号酒店 / 跨城同名 ---------------------------------


def test_duck_restaurant_no_longer_absorbs_palace():
    """事故本体：烤鸭店（故宫店）不再吃故宫放票口径（全半角括号同杀）。"""
    assert match_seed("四季民福烤鸭店（故宫店）", "北京") is None
    assert match_seed("四季民福烤鸭店(故宫店)", "北京") is None


def test_branch_store_names_do_not_match():
    for name, city in [
        ("京兆尹(雍和宫店)", "北京"),
        ("蟹叁寳·蟹黄捞饭(苏州拙政园店)", "苏州"),
        ("南京大牌档(中山陵店)", "南京"),
        ("故宫角楼咖啡(故宫店)", "北京"),
        ("故宫餐厅(景运门店)", "北京"),
        ("萬春金福下午茶(故宫店)", "北京"),
        ("平江小院(苏州平江路拙政园店)", "苏州"),
    ]:
        assert match_seed(name, city) is None, name


def test_unparenthesized_hotels_killed_by_non_site_tokens():
    """剥不掉括号的（无括号酒店/餐厅名）由设施词守卫兜住。"""
    for name, city in [
        ("北京雍和宫漫心酒店", "北京"),
        ("北京天安门广场CitiGO欢阁酒店", "北京"),
        ("南京麒麟中山陵景区希尔顿欢朋酒店", "南京"),
        ("北京雍和宫和平里亚朵X酒店", "北京"),
        ("广州塔璇玑地中海自助旋转餐厅", "广州"),
    ]:
        assert match_seed(name, city) is None, name


def test_cross_city_same_keyword_killed_by_city_guard():
    assert match_seed("孜图酒店(南京明故宫店)", "南京") is None
    assert match_seed("徐州汉兵马俑博物馆", "徐州") is None
    assert match_seed("沈阳故宫博物院", "沈阳") is None
    assert match_seed("明清故宫（北京故宫、沈阳故宫）", "沈阳") is None


def test_tail_strip_fuzzy_no_longer_enabled():
    """_same_site 尾剥（风景区→黄山）不再进预约匹配。"""
    assert match_seed("杭州黄山尖", "杭州") is None
    assert match_seed("黄山市徽州区潜口民宅博物馆", "黄山") is None


# --- 正身与变体不设防 ---------------------------------------------------------


def test_exact_seed_names_hit_without_guards():
    """精确名=正身：城市不设防（历史行为保持；test_api_pois 的重庆市
    fixture 行靠这一条不回归）。"""
    assert match_seed("故宫博物院", "北京")[0] == "故宫博物院"
    assert match_seed("故宫", None)[0] == "故宫"
    assert match_seed("故宫博物院", "上海")[0] == "故宫博物院"


def test_true_name_variants_still_hit():
    assert match_seed("西城区恭王府景区", "北京")[0] == "恭王府"
    assert match_seed("城关区布达拉宫景区", "拉萨")[0] == "布达拉宫"
    assert match_seed("黄山区黄山风景区", "黄山")[0] == "黄山风景区"
    assert match_seed("上海博物馆东馆", "上海")[0] == "上海博物馆"
    assert match_seed("苏州博物馆西馆", "苏州")[0] == "苏州博物馆"


def test_unknown_city_keeps_guard_off():
    """城市未知（老调用方/未标注行）不设防——正身/变体照常。"""
    assert match_seed("西城区恭王府景区", None)[0] == "恭王府"
    assert match_seed("西城区恭王府景区", "")[0] == "恭王府"
    assert match_seed("西城区恭王府景区", "未标注")[0] == "恭王府"


def test_longest_seed_wins_qinhan_branch_release():
    hit = match_seed("陕西历史博物馆秦汉馆", "西安")
    assert hit[0] == "陕西历史博物馆秦汉馆"
    assert hit[1]["release"] == "17:30"  # 修复主馆键（17:00）字典序抢先


# --- 09 号表守卫 ---------------------------------------------------------------


def test_csv_branch_and_cross_city_names_absorb_nothing():
    assert match_reservation_csv_row("楼外楼(西湖景区孤山路店)", "杭州") is None
    assert match_reservation_csv_row("三国义府火锅(武侯祠总店)", "成都") is None
    assert match_reservation_csv_row("杭州西湖云上茶宿", "杭州") is None
    assert match_reservation_csv_row("鹤壁古城景区", "鹤壁") is None


def test_csv_exact_rows_still_hit():
    assert match_reservation_csv_row("大足石刻", "重庆") is not None
    assert match_reservation_csv_row("良渚古城遗址", "杭州") is not None


# --- L1 抢票日历 / L2 分类 ------------------------------------------------------


def test_build_reservation_tasks_guards_and_keeps_true_sites():
    from app.services import booking_auto as ba

    tasks = ba.build_reservation_tasks(
        [
            {"name": "四季民福烤鸭店（故宫店）", "city": "北京", "day": 1},
            {"name": "孜图酒店(南京明故宫店)", "city": "南京", "day": 1},
            {"name": "徐州汉兵马俑博物馆", "city": "徐州", "day": 1},
            # 品类守卫：老客户端上报餐/住/接驳卡也不出任务
            {"name": "故宫博物院", "city": "北京", "day": 1, "category": "food"},
            {"name": "恭王府", "city": "北京", "day": 1, "category": "hotel"},
            # 正身照常出任务
            {"name": "故宫博物院", "city": "北京", "day": 2},
            {"name": "西城区恭王府景区", "city": "北京", "day": 2},
        ],
        start_date="2026-11-25",
    )
    names = [t.name for t in tasks]
    assert names == ["故宫博物院", "西城区恭王府景区"]
    # day2=2026-11-26：故宫提前 7 天 → 11-19 开抢；恭王府提前 10 天 → 11-16
    assert tasks[0].release_time == "20:00" and tasks[0].open_date == "2026-11-19"
    assert tasks[1].advance_days == 10 and tasks[1].open_date == "2026-11-16"


def test_check_availability_restaurant_is_not_official_quota():
    import asyncio

    from app.services import booking_auto as ba

    status = asyncio.run(
        ba.check_availability("四季民福烤鸭店（故宫店）", "北京", "2026-11-25")
    )
    assert status.value == "unknown"


# --- 行程卡提示层（plan._reservation_hint）--------------------------------------


def test_hint_duck_restaurant_gets_no_palace_verdict():
    from app.services.agent.plan import _reservation_hint

    # 事故本体：餐卡 cand（food/北京）不出故宫放票提示
    assert (
        _reservation_hint(
            "四季民福烤鸭店（故宫店）", {"category": "food", "city": "北京"}
        )
        is None
    )
    # 老调用方无 cand 信息：括号守卫同样兜住
    assert _reservation_hint("四季民福烤鸭店（故宫店）", {}) is None


def test_hint_true_sites_unchanged():
    from app.services.agent.plan import _reservation_hint

    hint = _reservation_hint("故宫博物院", {})
    assert hint and "需提前 7 天预约" in hint
    hint2 = _reservation_hint("西城区恭王府景区", {"city": "北京"})
    assert hint2 and "10" in hint2
    assert _reservation_hint("大足石刻", {}) is not None  # 09 表精确行照常


def test_hint_qinhan_release_corrected():
    from app.services.agent.plan import _reservation_hint

    hint = _reservation_hint("陕西历史博物馆秦汉馆", {"city": "西安"})
    assert hint and "17:30" in hint


def test_hint_guards_on_cross_city_and_hotels():
    from app.services.agent.plan import _reservation_hint

    assert _reservation_hint("徐州汉兵马俑博物馆", {"city": "徐州"}) is None
    assert _reservation_hint("北京雍和宫漫心酒店", {"city": "北京"}) is None


# --- 详情气泡层（api/pois._seed_meta_for）--------------------------------------


def test_bubble_guards_branch_hotel_cross_city():
    from app.api.pois import _seed_meta_for

    assert _seed_meta_for("四季民福烤鸭店（故宫店）", "北京") is None
    assert _seed_meta_for("北京雍和宫漫心酒店", "北京") is None
    assert _seed_meta_for("沈阳故宫博物院", "沈阳") is None


def test_bubble_true_sites_hit():
    from app.api.pois import _seed_meta_for

    assert _seed_meta_for("故宫博物院", "北京") is not None
    assert _seed_meta_for("西城区恭王府景区", "北京") is not None
