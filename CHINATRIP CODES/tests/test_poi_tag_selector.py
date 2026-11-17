"""poi_tag_selector 用户可选二级标签单测（DESIGN user_tag_two_level_2026-11-10 §一）。

纯单测（不连库）。判例口径：
- 每个一级至少 2 个二级命中判例；
- hotel/food/transport/category=None 服务类排除；
- 多标签封顶 3（类目命中恒保留，其余按设计表序填充）；
- 未命中不猜（返回 (None, [])）；
- unesco/5a + 名字山水语素进 scenic 相关判例——scenic 是行程级桶概念
  不在 25 组里，任何输出标签必须 ∈ GROUP_FAMILY，不发明组外标签。
"""

from app.services.poi_tag_selector import (
    GROUP_FAMILY,
    GROUPS_BY_FAMILY,
    classify_poi,
)


def test_vocab_shape():
    """词表形状：7 一级 × 25 二级，双向映射一致；scenic 不在组内。"""
    assert len(GROUPS_BY_FAMILY) == 7
    assert sum(len(gs) for gs in GROUPS_BY_FAMILY.values()) == 25
    assert len(GROUP_FAMILY) == 25
    assert set(GROUP_FAMILY) == {g for gs in GROUPS_BY_FAMILY.values() for g in gs}
    # scenic 是行程级桶概念（不在 25 组），选择器词表不得混入
    assert "scenic" not in GROUP_FAMILY


# ---- 一级：自然山水（≥2 个二级判例） ----


def test_family_nature():
    fam, groups = classify_poi("nature", [], [], "黄山风景区", "amap", "any")
    assert (fam, groups) == ("自然山水", ["山岳登高"])
    fam, groups = classify_poi("nature", [], [], "太湖风景区", "amap", "any")
    assert (fam, groups) == ("自然山水", ["江河湖泊"])
    fam, groups = classify_poi("nature", [], [], "黄果树瀑布景区", "amap", "any")
    assert (fam, groups) == ("自然山水", ["瀑布溶洞"])
    fam, groups = classify_poi("nature", [], [], "西溪国家湿地公园", "amap", "any")
    assert (fam, groups) == ("自然山水", ["森林湿地"])
    # 自然野趣粗词 + 草原名字佐证 → 草原沙漠（碰撞消解，不落 江河湖泊）
    fam, groups = classify_poi(
        "nature", [], ["自然野趣"], "呼伦贝尔大草原", "amap", "any"
    )
    assert (fam, groups) == ("自然山水", ["草原沙漠"])
    # 自然野趣粗词无草原佐证 → 设计默认 江河湖泊（自然山水细词的归属）
    fam, groups = classify_poi("nature", [], ["自然野趣"], "某山景区", "amap", "any")
    assert fam == "自然山水" and "江河湖泊" in groups and "草原沙漠" not in groups


# ---- 一级：滨海水上（≥2 个二级判例） ----


def test_family_water():
    fam, groups = classify_poi("attraction", [], [], "亚龙湾", "amap", "any")
    assert (fam, groups) == ("滨海水上", ["海滨海岛"])
    # 水上项目粗词：theme_park 佐证 → 漂流冲浪
    fam, groups = classify_poi(
        "theme_park", [], ["水上项目"], "国色天乡陆地乐园", "amap", "any"
    )
    assert fam == "亲子乐园" and groups == ["漂流冲浪", "主题乐园"]
    # 水上项目粗词无佐证 → 默认 游船夜航（乘船游览主导细词）
    fam, groups = classify_poi(
        "attraction", [], ["水上项目"], "夜泊秦淮", "amap", "any"
    )
    assert (fam, groups) == ("滨海水上", ["游船夜航"])


# ---- 一级：历史人文（≥2 个二级判例） ----


def test_family_history():
    assert classify_poi("museum", [], [], "某博物馆", "amap", "any") == (
        "历史人文",
        ["博物馆"],
    )
    assert classify_poi("historic", [], [], "某古城墙", "amap", "any") == (
        "历史人文",
        ["古迹遗址"],
    )
    assert classify_poi("ancient_town", [], [], "周庄", "amap", "any") == (
        "历史人文",
        ["古镇古村"],
    )
    assert classify_poi("temple", [], [], "某寺", "amap", "any") == (
        "历史人文",
        ["寺庙教堂"],
    )
    assert classify_poi("castle", [], [], "某城堡", "amap", "any") == (
        "历史人文",
        ["寺庙教堂"],
    )
    # 纪念场馆：memorial ∧ 名字带 纪念
    assert classify_poi("memorial", [], [], "毛主席纪念堂", "amap", "any") == (
        "历史人文",
        ["纪念场馆"],
    )
    # memorial 无"纪念"字样 → 归 博物馆（设计互斥注）
    assert classify_poi("memorial", [], [], "中共一大会址", "amap", "any") == (
        "历史人文",
        ["博物馆"],
    )
    # 纪念建筑带 国家N级博物馆 标签 → 互斥时归 博物馆
    assert classify_poi(
        "memorial", ["国家一级博物馆"], [], "某纪念馆", "amap", "any"
    ) == ("历史人文", ["博物馆"])
    # 标签路径：非 museum 类目也命中 博物馆
    assert classify_poi(
        "attraction", ["国家二级博物馆"], [], "某陈列馆", "amap", "any"
    ) == (
        "历史人文",
        ["博物馆"],
    )


# ---- 一级：园林街区（≥2 个二级判例） ----


def test_family_garden_street():
    assert classify_poi("garden", [], [], "某植物园", "amap", "any") == (
        "园林街区",
        ["园林花园"],
    )
    assert classify_poi("park", [], [], "某公园", "amap", "any") == (
        "园林街区",
        ["城市公园"],
    )
    assert classify_poi("attraction", [], [], "南京路步行街", "amap", "any") == (
        "园林街区",
        ["街区漫步"],
    )
    assert classify_poi("other", [], [], "某街巷", "street", "any") == (
        "园林街区",
        ["街区漫步"],
    )
    assert classify_poi("viewpoint", [], [], "某观景台", "amap", "any") == (
        "园林街区",
        ["地标观景"],
    )
    assert classify_poi("attraction", ["landmark"], [], "某塔", "amap", "any") == (
        "园林街区",
        ["地标观景"],
    )


# ---- 一级：亲子乐园（≥2 个二级判例） ----


def test_family_kids():
    assert classify_poi("theme_park", [], [], "某乐园", "amap", "any") == (
        "亲子乐园",
        ["主题乐园"],
    )
    assert classify_poi("zoo", [], [], "动物园", "amap", "any") == (
        "亲子乐园",
        ["动物水族"],
    )
    assert classify_poi("park", [], ["亲近动物"], "某公园", "amap", "any") == (
        "园林街区",
        ["城市公园", "动物水族"],
    )
    assert classify_poi("attraction", [], ["科技探索"], "某科技馆", "amap", "any") == (
        "亲子乐园",
        ["科技探索"],
    )
    # 适合带娃 → 科技探索（设计"遛娃为弱信号兜底"，粗化后直译消费）
    assert classify_poi("attraction", [], ["适合带娃"], "某乐园", "amap", "any") == (
        "亲子乐园",
        ["科技探索"],
    )


# ---- 一级：演艺夜游（≥2 个二级判例） ----


def test_family_show_night():
    assert classify_poi("entertainment", [], [], "某剧场", "amap", "any") == (
        "演艺夜游",
        ["演出秀"],
    )
    assert classify_poi("attraction", ["show"], [], "某秀场", "amap", "any") == (
        "演艺夜游",
        ["演出秀"],
    )
    assert classify_poi("attraction", [], [], "某地", "amap", "show") == (
        "演艺夜游",
        ["演出秀"],
    )
    assert classify_poi("attraction", [], [], "某夜市", "amap", "evening") == (
        "演艺夜游",
        ["夜市夜景"],
    )
    # 拍照打卡默认落 地标观景；bvt=evening 时 夜市夜景 并存（bvt 独立路径）
    assert classify_poi("attraction", [], ["拍照打卡"], "某塔", "amap", "any") == (
        "园林街区",
        ["地标观景"],
    )
    assert classify_poi("attraction", [], ["拍照打卡"], "某塔", "amap", "evening") == (
        "园林街区",
        ["地标观景", "夜市夜景"],
    )


# ---- 一级：休闲度假（≥2 个二级判例） ----


def test_family_leisure():
    # 温泉滑雪粗词：名字佐证分开落位（判例名避开 山/湾 等其他语素）
    assert classify_poi("nature", [], ["温泉滑雪"], "某温泉旅游区", "amap", "any") == (
        "休闲度假",
        ["温泉疗养"],
    )
    assert classify_poi("nature", [], ["温泉滑雪"], "某滑雪场", "amap", "any") == (
        "休闲度假",
        ["冰雪运动"],
    )
    # 名字无佐证（泡温泉/滑雪细词不可分）→ 两桶都命中
    assert classify_poi("nature", [], ["温泉滑雪"], "某嬉水乐园", "amap", "any") == (
        "休闲度假",
        ["温泉疗养", "冰雪运动"],
    )
    assert classify_poi("tea_experience", [], [], "某茶馆", "amap", "any") == (
        "休闲度假",
        ["茶室禅意"],
    )
    # 文化体验粗词：名字带 度假 → 温泉疗养，否则 茶室禅意
    assert classify_poi("attraction", [], ["文化体验"], "某书院", "amap", "any") == (
        "休闲度假",
        ["茶室禅意"],
    )
    assert classify_poi(
        "theme_park", [], ["文化体验"], "开元森泊度假乐园", "amap", "any"
    ) == ("亲子乐园", ["主题乐园", "温泉疗养"])


# ---- 服务类排除 ----


def test_service_categories_excluded():
    """hotel/food/transport/category=None 恒 (None, [])，信号再强也不进标签。"""
    for cat in ("hotel", "food", "transport", None):
        assert classify_poi(
            cat, ["5a"], ["水上项目"], "海景大酒店", "amap", "evening"
        ) == (
            None,
            [],
        )
        assert classify_poi(
            cat, ["unesco"], ["怀旧历史"], "古镇民宿", "histvillage", "any"
        ) == (
            None,
            [],
        )


# ---- 封顶与类目保留 ----


def test_cap_three_by_table_order():
    """4 个命中封顶 3：按设计表序截断（街区漫步 §4.3 先于 地标观景 §4.4）。"""
    fam, groups = classify_poi(
        "ancient_town",
        ["unesco", "histvillage"],
        ["拍照打卡", "城市漫步"],
        "某古镇景区",
        "street",
        "any",
    )
    assert groups == ["古迹遗址", "古镇古村", "街区漫步"]
    assert fam == "历史人文"  # 类目命中（古镇古村）定族


def test_cap_reserves_category_driven_tag():
    """类目命中恒保留：名字带海的主题乐园不丢 主题乐园，族仍归 亲子乐园。"""
    fam, groups = classify_poi(
        "theme_park", [], ["拍照打卡", "适合带娃"], "海洋王国", "amap", "any"
    )
    assert len(groups) == 3
    assert "主题乐园" in groups
    assert groups == ["海滨海岛", "地标观景", "主题乐园"]  # 输出按设计表序
    assert fam == "亲子乐园"


# ---- 未命中不猜 ----


def test_no_guess_on_miss():
    assert classify_poi("attraction", ["4a"], [], "某广场", "amap", "any") == (None, [])
    assert classify_poi("art", [], [], "某美术馆", "amap", "any") == (None, [])
    assert classify_poi("other", [], [], "村口大树", "amap", "any") == (None, [])
    assert classify_poi(None, None, None, None, None, None) == (None, [])


# ---- unesco / 5a + 名字山水语素（scenic 相关判例，无组外标签） ----


def test_unesco_and_5a_scenic_names():
    # unesco 前缀 → 古迹遗址（不发明 scenic 组外标签）
    assert classify_poi("historic", ["unesco"], [], "明清皇宫", "unesco", "any") == (
        "历史人文",
        ["古迹遗址"],
    )
    # unesco_karst 双命中：瀑布溶洞（精确词）+ 古迹遗址（前缀）；nature+山名 → 山岳登高
    fam, groups = classify_poi(
        "nature", ["unesco_karst"], [], "桂林山水", "unesco", "any"
    )
    assert groups == ["山岳登高", "瀑布溶洞", "古迹遗址"]  # 恰好 3 个封顶
    assert fam == "自然山水"  # 类目命中（山岳登高）定族
    # 5a 名单骨架行：名字山水语素进 scenic 相关组
    fam, groups = classify_poi("nature", ["5a"], [], "天门山国家森林公园", "5a", "any")
    assert groups == ["山岳登高", "森林湿地"]
    assert fam == "自然山水"
    assert "scenic" not in groups


def test_outputs_always_in_vocab():
    """任何输出标签必须 ∈ GROUP_FAMILY（不发明组外标签），族与组自洽。"""
    cases = [
        ("nature", ["5a"], ["水上项目"], "海岛峡湾漂流记", "5a", "show"),
        (
            "ancient_town",
            ["unesco", "histvillage"],
            ["怀旧历史"],
            "平遥古镇",
            "5a",
            "evening",
        ),
        (
            "theme_park",
            ["show"],
            ["适合带娃", "亲近动物"],
            "海世界乐园",
            "amap",
            "evening",
        ),
        ("memorial", ["国家三级博物馆"], ["拍照打卡"], "某纪念塔", "amap", "any"),
        ("park", ["citywalk"], ["自然野趣"], "滨湖湿地街区间", "street", "evening"),
        ("zoo", [], ["温泉滑雪"], "雪山动物谷", "amap", "any"),
    ]
    for c in cases:
        fam, groups = classify_poi(*c)
        assert all(g in GROUP_FAMILY for g in groups), c
        assert len(groups) <= 3
        if groups:
            assert fam in {GROUP_FAMILY[g] for g in groups}, c


# ---- 历史细词兼容（粗化前的原词经 review_tag_coarse 归一后消费） ----


def test_legacy_fine_review_words():
    assert classify_poi("attraction", [], ["登高爬山"], "某步道", "amap", "any") == (
        "自然山水",
        ["山岳登高"],
    )
    assert classify_poi("nature", [], ["历史建筑"], "某老街", "amap", "any") == (
        "历史人文",
        ["古迹遗址"],
    )
    assert classify_poi("nature", [], ["古镇古村"], "周庄古镇", "amap", "any") == (
        "历史人文",  # nature 无类目命中 → 取首个命中标签（古镇古村）所属族
        ["古镇古村"],
    )
    assert classify_poi("nature", [], ["泡温泉"], "某温泉谷", "amap", "any") == (
        "休闲度假",
        ["温泉疗养"],
    )
    assert classify_poi("nature", [], ["户外滑雪"], "某滑雪场", "amap", "any") == (
        "休闲度假",
        ["冰雪运动"],
    )
    assert classify_poi("nature", [], ["度假村"], "某度假村", "amap", "any") == (
        "休闲度假",
        ["温泉疗养"],
    )
