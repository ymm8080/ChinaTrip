"""NLU 意图检测层（切片 1）——意图检测纯函数从 legacy
app/services/agent/plan.py 与 app/api/plan.py 原样迁入，行为零变化；
新架构（trip_solver 等）自此从本模块 import，不再依赖 legacy。
glm-5.3-flash 调用层在后续切片接入。"""

from __future__ import annotations

import re
from datetime import time

# 街区型体验的名字语素（2026-11-08 主题街区案）：库品类不可靠
# （show 源主题街区行=entertainment），名字兜底认街区身份。
_STREET_DISTRICT_RE = re.compile("主题街区|街区|步行街")


def _cand_is_show(cand: dict) -> bool:
    """演出候选判定（2026-10-29 功能标签批打后认 tags）：04 演艺源 /
    娱乐类 / 宜演出时段之外，标签 show 同样算——amap 源的川剧院等
    （label_pois 名称内核补判）按同一场晚间档参与提案。街区型体验豁免
    （2026-11-08 主题街区案拍板「是 CITYWALK 直接插入」）：名字
    带主题街区/街区/步行街且品类 citywalk 的行走体验不是演出——show
    源血缘/best_visit_time 旧键不再把它推晚间档与演出闸。"""
    if str(cand.get("category") or "") == "citywalk" and _STREET_DISTRICT_RE.search(
        str(cand.get("name") or "")
    ):
        return False
    tags = {str(t).strip().lower() for t in (cand.get("tags") or [])}
    return (
        cand.get("category") == "entertainment"
        or cand.get("best_visit_time") == "show"
        or str(cand.get("source") or "").strip().lower() == "show"
        or "show" in tags
    )


_TEXT_DAY_START_RE = re.compile(
    r"(?:leav\w*|depart(?:ing)?|check\s*-?\s*out|start(?:ing)?)"
    r"[^0-9\n]{0,24}?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?!\d)"
    r"|(\d{1,2})(?::(\d{2}))?\s*(am|pm)?[^0-9\n。；;]{0,8}"
    r"(?:出发|离店|退房|离开酒店)",
    re.IGNORECASE,
)


def _parse_text_day_start(text: str) -> str | None:
    """文字里「第一天几点出发」（2026-11-17「LEAVE HOTEL ON 11AM, PLS
    ARRANGE」案）：leave/depart/出发/退房 + 时刻 → 「HH:MM」。只作 day-1
    起排锚，不建交通腿（行前卡的 arrival_time 是班次语义，别混）。读不
    出或时刻不在 05:00-20:00 → None。"""
    # R9-1：取第一个「有效」匹配而非第一个原始匹配——「11月25日出发」
    # 会先命中中文分支（hour=25 越界），旧版 single-search 直接 None，把
    # 句尾真正的 LEAVE HOTEL ON 11AM 遮掉（live 实锤）。finditer 跳过越
    # 界假命中，口径不变（窗 05:00-20:00 内的首个时刻）。
    for m in _TEXT_DAY_START_RE.finditer(str(text or "")):
        if m.group(1):
            hour, minute, ap = int(m.group(1)), m.group(2), m.group(3)
        else:
            hour, minute, ap = int(m.group(4)), m.group(5), m.group(6)
        if minute is None:
            minute = "00"
        if ap:
            if ap.lower() == "pm" and 1 <= hour <= 11:
                hour += 12
            elif ap.lower() == "am" and hour == 12:
                hour = 0
        if not (5 <= hour <= 20):
            continue
        try:
            return time(hour, int(minute)).strftime("%H:%M")
        except ValueError:
            continue
    return None


_SITE_NAME_JUNK = r"[\s（）()\[\]【】「」·、，,。.\-—_'\"”]"

# venue-type tails that add nothing to identity (「石窟样本景区」==「石窟样本」)
_SITE_TAILS = ("旅游风景区", "风景名胜区", "旅游景区", "风景区", "景区", "旅游区")


def _norm_site_name(name: str) -> str:
    s = re.sub(_SITE_NAME_JUNK, "", name or "")
    stripped = True
    while stripped:
        stripped = False
        for tail in _SITE_TAILS:
            if s.endswith(tail) and len(s) - len(tail) >= 2:
                s = s[: -len(tail)]
                stripped = True
    return s


def _norm_pref_text(text: str) -> str:
    """偏好文本规整：剥「偏好：」前缀与首尾标点，转小写（en 词形对齐）。"""
    s = (text or "").strip()
    s = re.sub(r"^(偏好|preference)[:：\s]*", "", s, flags=re.IGNORECASE)
    return s.strip(" \t，。,.、!！?？;；~～-").lower()


# 偏好→品类映射（拍板③）：(偏好触发词, 库内 category 值, 名字兜底 token)。
# category 为主（库内已分类 museum/nature/park/…），名字 token 只兜底
# 跨源未分类行——宁缺勿滥，防单字误配（「海」误吃城市名博物馆这类）。
PREFERENCE_CATEGORY_SPECS: tuple[
    tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        ("博物馆人文", "博物馆", "人文", "历史", "museum", "history"),
        ("museum", "historic", "temple", "art"),
        (
            "博物馆",
            "纪念馆",
            "美术馆",
            "艺术馆",
            "科技馆",
            "展览馆",
            "故居",
            "遗址",
            "文庙",
            "书院",
            "教堂",
        ),
    ),
    (
        ("自然风光", "自然", "山水", "风景", "nature", "scenic", "户外"),
        ("nature", "park", "viewpoint"),
        (
            "风景名胜",
            "森林公园",
            "湿地公园",
            "地质公园",
            "国家公园",
            "草原",
            "瀑布",
            "峡谷",
            "雪山",
            "竹海",
            "花海",
        ),
    ),
    (
        ("美食街区", "美食", "小吃", "吃货", "夜市", "food"),
        ("citywalk",),
        ("夜市", "美食", "小吃", "步行街", "美食街", "食品街"),
    ),
    (
        ("亲子休闲", "亲子", "孩子", "小孩", "带娃", "family", "kids"),
        ("theme_park", "zoo"),
        (
            "动物园",
            "海洋馆",
            "海底世界",
            "水族馆",
            "乐园",
            "欢乐谷",
            "迪士尼",
            "熊猫",
            "植物园",
            "科技馆",
        ),
    ),
    (
        ("古镇", "古城", "水乡"),
        ("ancient_town",),
        ("古镇", "古城", "水乡", "古街"),
    ),
    (
        ("喝茶", "泡茶", "品茶", "茶馆", "咖啡", "奶茶", "tea", "coffee"),
        # 茶体验档（2026-11-07 拍板：茶体验正主归此档）：类别精确
        # 通道；token 带下划线不会子串误伤英文名（裸 "tea"⊂"steak/steam"）
        ("tea_experience",),
        ("茶馆", "茶楼", "咖啡", "奶茶"),
    ),
    # 娱乐/夜生活组（2026-11-05 SHOW/ENTERTAINMENT 事故）：偏好只作
    # 选点排序信号；库内 entertainment 行=演出池同源。
    (
        ("娱乐", "entertainment", "夜生活", "nightlife"),
        ("entertainment",),
        ("娱乐", "演艺", "夜生活"),
    ),
)


def _preference_tokens(text: str) -> tuple[tuple[str, ...], bool]:
    """偏好文本 → (品类命中 token 并集, 是否演出偏好)。多品类并存
    （「喜欢博物馆和美食」→ 博物馆类+美食类同时优先）。"""
    low = _norm_pref_text(text)
    if not low:
        return (), False
    toks: list[str] = []
    for triggers, cats, name_toks in PREFERENCE_CATEGORY_SPECS:
        if any(t in low for t in triggers):
            toks.extend(cats)
            toks.extend(name_toks)
    show_pref = any(
        t in low for t in ("看演出", "演出", "看秀", "show", "娱乐", "entertainment")
    )
    if show_pref:
        toks.extend(("演出", "剧场", "剧院", "戏院", "相声"))
    return tuple(dict.fromkeys(toks)), show_pref


def _pref_category_hit(
    cand: dict, tokens: tuple[str, ...], show_pref: bool = False
) -> bool:
    """候选是否偏好同类（拍板③）：category 精确命中 / 名字或 tags 包含
    token / 演出偏好走 _cand_is_show 结构判定。"""
    if show_pref and _cand_is_show(cand):
        return True
    if not tokens:
        return False
    name = _norm_site_name(str(cand.get("name") or "")).lower()
    category = str(cand.get("category") or "").strip().lower()
    tags = " ".join(str(t) for t in (cand.get("tags") or [])).lower()
    return any(t in name or t == category or t in tags for t in tokens)


# R8b（2026-11-18 用户拍板「裸偏好也触发全量引擎重排」）：点名/心愿/
# 结构变更标记词——命中即不算纯偏好语句，照旧走原道（单点心愿已被
# try_fast_wish 上游拦截，这里再兜一层语义分界）。
_PREFERENCE_INTENT_MARKERS: tuple[str, ...] = (
    "必去",
    "要去",
    "想去",
    "必须",
    "务必",
    "打卡",
    "加上",
    "加个",
    "加一个",
    "添",
    "去掉",
    "删除",
    "取消",
    "改成",
    "换",
    "重新规划",
    "重新安排",
    # R8b-CI 收口（2026-11-19）：心愿/编辑动词补齐——「我想看/想喝/想逛/
    # 想吃/想玩」是活动类心愿语句（愿 lane 原道，如 想喝茶/想逛夜市/
    # 我想看点博物馆人文）；「插入」是编辑动词（quota-dead 等编辑披露
    # 必须照旧：插入陕西历史博物馆）；英文 want 同口径（I want to
    # watch…）。注意「想看」刻意不在列——想看演出是裸偏好（重排）。
    "我想",
    "想喝",
    "想逛",
    "想吃",
    "想玩",
    "插入",
    "want",
)


def _bare_preference_statement(text: str) -> bool:
    """纯品类偏好语句判定（R8b）：偏好 token 命中且无任何点名/心愿/
    结构变更标记——整句就是品类/风格倾向（「我喜欢博物馆」「多排几家
    博物馆」）。点名/心愿/改结构语句各走原道；风格词（慢慢逛/暴走）
    不在品类名录，天然不触发。"""
    s = (text or "").strip()
    if not s:
        return False
    if any(m in s for m in _PREFERENCE_INTENT_MARKERS):
        return False
    toks, show = _preference_tokens(s)
    return bool(toks or show)


def _restart_route_only(text: str, cities: list) -> bool:
    """换局句是否纯路线声明（二期消息轮换引擎守卫，2026-11-18）。

    剥掉城市名、天数（数字/汉字数词）、常见路线词与标点后无残渣 →
    引擎可承接；有残渣（可能点名地点，如「必去西湖」）→ legacy 确认
    轮管线（读点→点选→排期，F-03 缝不吞点）。保守方向：拿不准留给
    legacy（_brief_is_route_declaration 是短句读点护栏，口径过窄，
    不适配换局句）。"""
    import re as _re

    probe = _re.sub(r"\s+", "", text or "")
    if not probe:
        return True
    for city in cities or []:
        base = _re.sub(r"\s+", "", city or "").removesuffix("市")
        if base:
            probe = probe.replace(base + "市", "").replace(base, "")
    probe = _re.sub(r"[0-9０-９一二两三四五六七八九十半]+", "", probe)
    probe = _re.sub(
        r"[天日早晚去玩行程安排规划新重开改成换到出发回从，。！？、,.!?;:：\'\"]+",
        "",
        probe,
    )
    return not probe


def _restart_named_musts(text: str, store=None, cities=None) -> list[str]:
    """换局句里的点名地点短语（二期 2026-11-18 拍板「点名长句也换引擎」）。

    只认强意图点名词（必去/要去/必须去/一定要去/务必去/打卡）后到句读
    为止的短语，按「和/与/跟/及/还有/以及/、」拆开；「想去」是心愿软
    语义（R8 偏好/心愿链），引擎 musts=硬覆盖，语义不对等——留 legacy。
    短语不做底库校验：绑定交给快照绑定链（精确名→文本匹配→骨架兜底，
    缝不吞点、B-01）；底库没有的点（如楼外楼）由骨架候选诚实承载，
    或文本匹配合并到短语内最近已知点。负向语境（不必去/别必去）不读；
    琐碎短语（「然后回酒店休息」类）按黑名单丢弃。空返回=没有可承接
    点名 → 调用方落回 legacy 管线。
    """
    import re as _re

    def _known(name: str) -> bool:
        # R8-S4：整名精确命中底库（如「福和慧」含「和」）——整名
        # 直进 musts，绝不按连接词裂开（裂词案：福和慧→福+慧
        # 两张骨架卡）。库外名称仍走裂词（现状）。
        if store is None or not name:
            return False
        try:
            for c in cities or []:
                if store.candidate_by_name(c, name):
                    return True
        except Exception:
            return False
        return False

    def _clean_phrase(p: str) -> str:
        """R13l：动词尾巴剥除 + 纯吃意图不出硬必去——e2e 实锤
        「必去吃烤鸭」→骨架幽灵卡「吃烤鸭」定时观光卡；「故宫看看」
        必去名带动词尾巴靠模糊绑定侥幸。吃/喝/尝意图留偏好软通道
        （R8 荐餐链承担「想吃烤鸭」→烤鸭店推荐）；剥动词后恰是
        真身则用真身（品尝楼外楼→楼外楼）。
        """
        while True:
            _stripped_one = False
            for _tail in ("看看", "玩玩", "逛逛", "转转", "一下"):
                if p.endswith(_tail) and len(p) - len(_tail) >= 2:
                    p = p[: -len(_tail)]
                    _stripped_one = True
            if not _stripped_one:
                break
        for _lead in ("品尝", "吃", "喝", "尝", "品"):
            if p.startswith(_lead) and len(p) - len(_lead) >= 2:
                _food_core = p[len(_lead) :]
                if _known(_food_core):
                    p = _food_core
                else:
                    p = ""  # 纯吃意图：不进硬必去，留偏好软通道
                break
        return p

    marker_re = _re.compile(r"一定要去|必须去|务必去|必到|必去|要去|打卡")
    junk_re = _re.compile(
        r"然后|接着|之后|另外|要少|别太|太多|较少|安排|规划|节奏|时间"
    )
    probe = text or ""
    out: list[str] = []
    seen: set[str] = set()
    for m in marker_re.finditer(probe):
        # 负向语境：「不必去/别必去/无必去」不是点名
        if probe[max(0, m.start() - 1) : m.start()] in ("不", "别", "无"):
            continue
        # 短语 = 标记后到句读为止（：和 、不算句读——「必去：A、B」是名单）
        seg = probe[m.end() : m.end() + 48]
        cut = len(seg)
        for i, ch in enumerate(seg):
            if ch in "。！？；;，,.!?" or ch.isspace():
                cut = i
                break
        whole = _clean_phrase(
            seg[:cut].strip(" ：:、，,；;。.！!？?\"'「」【】（）()·\t")
        )
        # R13l（2026-11-20 深挖续）：动词尾巴剥除 + 纯吃意图不出硬必去。
        # e2e 实锤：「必去吃烤鸭」→骨架幽灵卡「吃烤鸭」定时观光卡
        # （16:13-17:43，与正确推荐的烤鸭店晚餐卡并列）；「一定要去
        # 故宫看看」→必去名带「看看」靠模糊绑定侥幸。吃/喝/尝意图留
        # 偏好软通道（R8 荐餐链承担「想吃烤鸭」→烤鸭店推荐）；剥动词
        # 后恰是真身则用真身（品尝楼外楼→楼外楼）。
        if not whole:
            continue
        if _known(whole):
            if len(whole) <= 16 and not junk_re.search(whole):
                if whole not in seen:
                    seen.add(whole)
                    out.append(whole)
                    if len(out) >= 8:  # 同 agent.MAX_BRIEF_SITES 口径
                        return out
            continue
        for part in _re.split(r"还有|以及|[和与跟及、]", seg[:cut]):
            p = _clean_phrase(part.strip(" ：:、，,；;。.！!？?\"'「」【】（）()·\t"))
            if len(p) < 2 or p in seen:
                # R8-S4：单字碎片不是地名（福/慧案）——丢弃，宁空
                # 返 legacy 读点确认轮，不出垃圾卡
                continue
            if len(p) > 16 or junk_re.search(p):
                continue
            seen.add(p)
            out.append(p)
            if len(out) >= 8:  # 同 agent.MAX_BRIEF_SITES 口径
                return out
    return out
