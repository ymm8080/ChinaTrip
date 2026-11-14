"""POI 用户可选二级标签推导（DESIGN user_tag_two_level_2026-11-10 §一）。

用户选择器的两级标签：7 个一级（family）× 25 个二级（group）受控词表。
映射规则唯一来源即本文件——每条规则直译设计 §一"推导"列，输入只消费
库内现有字段：category / tags / review_tags（粗词）/ name_zh / source /
best_visit_time。

review 粗词碰撞消解（粗化是有损合并：§五把 36 个细词归并成 12 个粗词，
§一规则当年按细词书写，同一粗词可能对应多个二级标签）。消解只用设计
自带的证据路径（名字/类目/bvt），不发明新证据、不发明组外标签：
  - 拍照打卡（=地标观景+夜游观景）→ 默认 地标观景；夜市夜景 仅当
    best_visit_time=evening（设计本就给了 bvt 独立路径，两桶可并存）。
  - 自然野趣（=自然山水+草原采风+沙漠戈壁）→ 名字带 草原|沙漠|戈壁 →
    草原沙漠，否则 江河湖泊（设计默认：自然山水 → 江河湖泊）。
  - 水上项目（=海滨玩水+乘船游览+漂流+冲浪+游艇帆船+亲水乐园 等）→
    theme_park 或名字带 漂流|冲浪|亲水|水上乐园 → 漂流冲浪；名字已按
    设计名字路径命中 海滨海岛/江河湖泊 时不重复落位；无佐证默认
    游船夜航（乘船游览为桶内主导细词，活动归活动桶）。
  - 怀旧历史（=历史建筑+古镇古村+影视基地）→ 名字带 古镇|古村 或
    ancient_town → 古镇古村，否则 古迹遗址（设计默认：历史建筑）。
  - 温泉滑雪（=泡温泉+滑雪/冰雪乐园 等）→ 名字带 温泉 → 温泉疗养；
    名字带 雪 → 冰雪运动；两者名字都无（细词不可分）→ 两桶都命中。
  - 文化体验（=文化体验+度假村+巴士观光+缆车索道）→ 名字带 度假 →
    温泉疗养，否则 茶室禅意（设计默认：同名细词 → 茶室禅意）。
  - 适合带娃（=亲子同乐+儿童乐园+遛娃宝藏地）→ 科技探索（设计明文
    "遛娃为弱信号兜底"，粗化后按直译全量消费）。

命中顺序 = 设计 §一 表顺序（级联产出保序去重），一个 POI 可命中多个
二级、封顶 3 个。封顶与 user_family 取舍规则：category 直接命中的标签
（博物馆/城市公园/主题乐园等类目型规则，类目是库内最强单字段信号）恒
保留，其余命中按表序填充至 3 个，输出仍按设计表序排列；user_family 取
user_groups 中首个类目命中标签所属族，无类目命中时取首个命中标签所属
族（避免「长隆海洋王国」这类名字带海的主题乐园因表序靠前的名字命中被
截断/误归族）。
hotel/food/transport/category=None 的服务类行恒返回 (None, [])（设计 §一
末注：选择器按 category 排除）。未命中不猜：返回 (None, [])，回填任务
留空（只填空语义）。

用法（回填）：app/jobs/backfill_poi_user_tags.py
用法（干跑）：PYTHONPATH=. python -m app.services.poi_tag_selector
"""

from __future__ import annotations

# 一级 → 二级（顺序即设计 §一 表顺序；/pois/tags 选择器树按此渲染）
GROUPS_BY_FAMILY: dict[str, list[str]] = {
    "自然山水": ["山岳登高", "江河湖泊", "瀑布溶洞", "草原沙漠", "森林湿地"],
    "滨海水上": ["海滨海岛", "漂流冲浪", "游船夜航"],
    "历史人文": ["博物馆", "古迹遗址", "古镇古村", "寺庙教堂", "纪念场馆"],
    "园林街区": ["园林花园", "城市公园", "街区漫步", "地标观景"],
    "亲子乐园": ["主题乐园", "动物水族", "科技探索"],
    "演艺夜游": ["演出秀", "夜市夜景"],
    "休闲度假": ["温泉疗养", "冰雪运动", "茶室禅意"],
}

# 二级 → 一级（回填 user_family / 查询侧归属用；25 组全覆盖）
GROUP_FAMILY: dict[str, str] = {
    g: fam for fam, groups in GROUPS_BY_FAMILY.items() for g in groups
}

# 设计 §一 全表序（封顶截断后仍按此序输出 user_groups）
_TABLE_ORDER: dict[str, int] = {
    tag: i
    for i, tag in enumerate(
        g for groups in GROUPS_BY_FAMILY.values() for g in groups
    )
}

# 混入 pois 表的服务类行（DESIGN §一末注）：不进任何用户标签
_EXCLUDED_CATEGORIES = frozenset({"hotel", "food", "transport"})

# 名字语素（设计"名字带 X"列的直译；_FOREST/_GRASS 等多字词用整词）
_SEA = "海岛湾礁"  # 海滨海岛
_RIVER = "江河湖库"  # 江河湖泊
_MOUNTAIN = "山峰岭"  # 山岳登高（限 category=nature）
_CAVE = "瀑洞溶"  # 瀑布溶洞
_FOREST = ("森林", "湿地", "地质公园")  # 森林湿地
_GRASS = ("草原", "沙漠", "戈壁")  # 草原沙漠（自然野趣消解的名字佐证）
_DRIFT = ("漂流", "冲浪", "亲水", "水上乐园")  # 漂流冲浪（水上项目消解佐证）
_STREET = ("街区", "步行街")  # 街区漫步
_ANCIENT = ("古镇", "古村")  # 古镇古村（怀旧历史消解的名字佐证）
_RESORT = "度假"  # 温泉疗养（文化体验消解佐证）
_SPRING = "温泉"  # 温泉疗养（温泉滑雪消解佐证）
_SNOW = "雪"  # 冰雪运动（温泉滑雪消解佐证）
_MEMORIAL = "纪念"  # 纪念场馆

_MAX_GROUPS = 3  # 封顶：一个 POI 最多 3 个二级标签


def classify_poi(
    category: object,
    tags: object,
    review_tags: object,
    name: object,
    source: object,
    best_visit_time: object,
) -> tuple[str | None, list[str]]:
    """POI → (user_family, [user_groups...])；服务类行/未命中 (None, [])。

    输入全部可空、可为 JSONB 原始值。review_tags 接受粗词（落库现状）
    也接受历史细词（经 review_tag_coarse.coarse_tag 归一后消费）。tags
    支持 unesco_* 前缀（古迹遗址）与精确词（unesco_karst→瀑布溶洞、
    国家N级博物馆、histvillage、中国历史文化名镇、citywalk、show、
    landmark）。user_family 取 user_groups 中首个类目命中标签所属族，
    无类目命中时取首个命中标签所属族（见模块 docstring 取舍规则）。
    """
    from app.services.review_tag_coarse import coarse_tag

    cat = str(category or "").strip().lower() or None
    if cat is None or cat in _EXCLUDED_CATEGORIES:
        return None, []

    tg = {str(t or "").strip() for t in (tags or []) if str(t or "").strip()}
    rv = {
        c
        for c in (coarse_tag(str(t or "").strip()) for t in (review_tags or []))
        if c
    }
    nm = str(name or "").strip()
    src = str(source or "").strip().lower()
    bvt = str(best_visit_time or "").strip().lower()

    # --- 佐证证据（供碰撞消解；只来自设计自带的路径） ---
    has_sea = any(m in nm for m in _SEA)
    has_river = any(m in nm for m in _RIVER)
    has_grass = any(m in nm for m in _GRASS)
    has_memorial_name = cat == "memorial" and _MEMORIAL in nm
    has_museum_tag = bool(tg & {"国家一级博物馆", "国家二级博物馆", "国家三级博物馆"})
    has_water_review = "水上项目" in rv

    hits: list[str] = []
    cat_hits: list[str] = []  # category 直接命中的标签（封顶恒保留、定族优先）

    def _hit(tag: str, by_cat: bool = False) -> None:
        if tag not in hits:  # 保序去重
            hits.append(tag)
        if by_cat and tag not in cat_hits:
            cat_hits.append(tag)

    # ---- §1 自然山水 ----
    # 山岳登高：review 登山徒步 ∨ (nature ∧ 名字带 山|峰|岭)
    mountain_by_cat = cat == "nature" and any(m in nm for m in _MOUNTAIN)
    if "登山徒步" in rv or mountain_by_cat:
        _hit("山岳登高", by_cat=mountain_by_cat)
    # 江河湖泊：名字带 江|河|湖|库 ∨ 自然野趣粗词（名字佐证落 草原沙漠 时不落此）
    grass_takeover = "自然野趣" in rv and has_grass
    if has_river or ("自然野趣" in rv and not grass_takeover):
        _hit("江河湖泊")
    # 瀑布溶洞：名字带 瀑|洞|溶 ∨ tags=unesco_karst
    if any(m in nm for m in _CAVE) or "unesco_karst" in tg:
        _hit("瀑布溶洞")
    # 草原沙漠：自然野趣粗词 ∧ 名字佐证（碰撞消解）
    if grass_takeover:
        _hit("草原沙漠")
    # 森林湿地：名字带 森林|湿地|地质公园
    if any(m in nm for m in _FOREST):
        _hit("森林湿地")

    # ---- §2 滨海水上 ----
    # 海滨海岛：名字带 海|岛|湾|礁（设计名字路径，独立于 review）
    if has_sea:
        _hit("海滨海岛")
    # 水上项目粗词碰撞消解（见模块 docstring）
    if has_water_review:
        if cat == "theme_park" or any(m in nm for m in _DRIFT):
            _hit("漂流冲浪")
        elif not has_sea and not has_river:
            _hit("游船夜航")

    # ---- §3 历史人文 ----
    # 博物馆：museum/gallery ∨ memorial(名字无"纪念") ∨ tags 国家N级博物馆
    museum_by_cat = cat in ("museum", "gallery") or (
        cat == "memorial" and not has_memorial_name
    )
    if museum_by_cat or has_museum_tag:
        _hit("博物馆", by_cat=museum_by_cat)
    # 古迹遗址：historic/ruins ∨ tags unesco* ∨ 怀旧历史粗词（无古镇佐证时）
    historic_by_cat = cat in ("historic", "ruins")
    if historic_by_cat or any(t.startswith("unesco") for t in tg):
        _hit("古迹遗址", by_cat=historic_by_cat)
    # 古镇古村：ancient_town ∨ tags histvillage/中国历史文化名镇
    ancient_by_cat = cat == "ancient_town"
    if ancient_by_cat or bool(tg & {"histvillage", "中国历史文化名镇"}):
        _hit("古镇古村", by_cat=ancient_by_cat)
    # 怀旧历史粗词碰撞消解（设计：历史建筑→古迹遗址、古镇古村→古镇古村）
    if "怀旧历史" in rv:
        if any(m in nm for m in _ANCIENT) or cat == "ancient_town":
            _hit("古镇古村")
        else:
            _hit("古迹遗址")
    # 寺庙教堂：temple/church/castle
    if cat in ("temple", "church", "castle"):
        _hit("寺庙教堂", by_cat=True)
    # 纪念场馆：memorial ∧ 名字带 纪念（设计注：与博物馆组互斥时归
    # 博物馆——带国家N级博物馆标签的纪念建筑只归 博物馆）
    if has_memorial_name and not has_museum_tag:
        _hit("纪念场馆", by_cat=True)

    # ---- §4 园林街区 ----
    # 园林花园：garden ∨ review 赏花看园
    if cat == "garden" or "赏花看园" in rv:
        _hit("园林花园", by_cat=cat == "garden")
    # 城市公园：park
    if cat == "park":
        _hit("城市公园", by_cat=True)
    # 街区漫步：citywalk ∨ source=street ∨ tags citywalk ∨ review 城市漫步
    # ∨ 名字带 街区|步行街
    if (
        cat == "citywalk"
        or src == "street"
        or "citywalk" in tg
        or "城市漫步" in rv
        or any(m in nm for m in _STREET)
    ):
        _hit("街区漫步", by_cat=cat == "citywalk")
    # 地标观景：viewpoint ∨ tags landmark ∨ review 拍照打卡（粗词消解：
    # 拍照打卡默认落此；夜市夜景 走 bvt 独立路径）
    if cat == "viewpoint" or "landmark" in tg or "拍照打卡" in rv:
        _hit("地标观景", by_cat=cat == "viewpoint")

    # ---- §5 亲子乐园 ----
    # 主题乐园：theme_park
    if cat == "theme_park":
        _hit("主题乐园", by_cat=True)
    # 动物水族：zoo ∨ review 亲近动物
    if cat == "zoo" or "亲近动物" in rv:
        _hit("动物水族", by_cat=cat == "zoo")
    # 科技探索：review 科技探索 ∨ 适合带娃（设计"遛娃为弱信号兜底"）
    if "科技探索" in rv or "适合带娃" in rv:
        _hit("科技探索")

    # ---- §6 演艺夜游 ----
    # 演出秀：entertainment ∨ tags show ∨ best_visit_time=show
    if cat == "entertainment" or "show" in tg or bvt == "show":
        _hit("演出秀", by_cat=cat == "entertainment")
    # 夜市夜景：bvt=evening（设计独立路径；review 夜游观景 粗化并入
    # 拍照打卡，已在 地标观景 消解；bvt=evening 时两桶可并存）
    if bvt == "evening":
        _hit("夜市夜景")

    # ---- §7 休闲度假 ----
    # 温泉疗养 / 冰雪运动：温泉滑雪粗词（泡温泉 vs 滑雪 细词不可分），
    # 名字佐证：带 温泉 → 温泉疗养、带 雪 → 冰雪运动；都无 → 两桶都命中
    if "温泉滑雪" in rv:
        spring_name = _SPRING in nm
        snow_name = _SNOW in nm
        if spring_name or not snow_name:
            _hit("温泉疗养")
        if snow_name or not spring_name:
            _hit("冰雪运动")
    # 温泉疗养 / 茶室禅意：文化体验粗词（文化体验 vs 度假村 细词不可分），
    # 名字带 度假 → 温泉疗养，否则 茶室禅意（同名细词的设计默认）
    if "文化体验" in rv:
        if _RESORT in nm:
            _hit("温泉疗养")
        else:
            _hit("茶室禅意")
    # 茶室禅意：tea_experience
    if cat == "tea_experience":
        _hit("茶室禅意", by_cat=True)

    if not hits:
        return None, []
    # 封顶取舍：类目命中恒保留，其余按设计表序填充至 3；输出按表序排列
    reserved = [t for t in hits if t in cat_hits]
    filler = [t for t in hits if t not in cat_hits]
    picked = reserved + filler[: max(0, _MAX_GROUPS - len(reserved))]
    groups = sorted(picked[:_MAX_GROUPS], key=lambda t: _TABLE_ORDER[t])
    # 定族：输出组里首个类目命中标签；无类目命中时首个命中标签
    primary = next((t for t in groups if t in cat_hits), groups[0])
    return GROUP_FAMILY[primary], groups


def _dry_run() -> None:  # pragma: no cover — ops 工具入口
    """打印全库映射分布与未命中清单（只读，不写库）。

    照 cuisine_taxonomy._dry_run 骨架：.env DATABASE_URL 直连，逐行跑
    classify_poi，输出 各二级标签计数 / 一级分布 / 未命中样本。
    """
    import re
    from collections import Counter
    from pathlib import Path

    from sqlalchemy import create_engine, text

    env = Path(__file__).resolve().parents[2] / ".env"
    m = re.search(r"DATABASE_URL\s*=\s*(.+)", env.read_text(encoding="utf-8"))
    eng = create_engine(m.group(1).strip() if m else "")
    with eng.connect() as c:
        rows = c.execute(
            text(
                "SELECT category, tags, review_tags, name_zh, source, "
                "best_visit_time FROM pois"
            )
        ).all()

    fam_counter: Counter[str] = Counter()
    grp_counter: Counter[str] = Counter()
    n_tags_dist: Counter[int] = Counter()
    excluded = 0
    unmatched = 0
    unmatched_samples: list[str] = []
    for cat, tags, rv, name, source, bvt in rows:
        fam, groups = classify_poi(cat, tags, rv, name, source, bvt)
        c0 = str(cat or "").strip().lower()
        if fam is None:
            if c0 in _EXCLUDED_CATEGORIES or not c0:
                excluded += 1
            else:
                unmatched += 1
                if len(unmatched_samples) < 30:
                    unmatched_samples.append(f"{name}({c0 or 'None'})")
            continue
        n_tags_dist[len(groups)] += 1
        fam_counter[fam] += 1
        for g in groups:
            grp_counter[g] += 1

    total = len(rows)
    tagged = sum(fam_counter.values())
    print(f"total={total} tagged={tagged} excluded={excluded} "
          f"unmatched={unmatched} tags_per_poi={dict(sorted(n_tags_dist.items()))}")
    print("--- 按一级（行数，一行可属多二级故同一行只计一次） ---")
    for fam, groups in GROUPS_BY_FAMILY.items():
        print(f"  {fam}\t{fam_counter.get(fam, 0)}")
        for g in groups:
            print(f"    {g}\t{grp_counter.get(g, 0)}")
    print("--- 未命中样本（≤30） ---")
    for s in unmatched_samples:
        print("  MISS", s)


if __name__ == "__main__":
    _dry_run()
