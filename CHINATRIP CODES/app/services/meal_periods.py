"""meal_periods 餐段推导（DESIGN user_tag_two_level_2026-11-10 §三）。

restaurants.meal_periods（JSONB 数组）由 opening_hours + cuisine_group
推导，六枚举：early_tea / breakfast / lunch / afternoon_tea / dinner /
late_night。纯函数零副作用、可离线单测；解析不了的 opening_hours 一律
返回 []（不猜），下游 _allowed_slots_for 对空/缺失走原营业时间推断，
行为不变。

解析口径（先采样库内回源真实格式再定，amap「周一至周日 10:00-22:00」、
baidu「09:00-17:00」、ctrip「全年全天开放/今天08:00-18:00开放」、跨零点
「17:00-02:00」、全天「00:00-24:00」、多段「10:00-14:00,17:00-21:00」、
噪音尾巴「节假日以官方通知为准/最晚进入16:30」等；见 tests）：
  * 去括号注释 → 全半角归一 → 去星期/日期前缀（周一至周日、每天、
    今天…）→ 按逗号/分号/顿号/斜杠分段 → 每段必须是「HH:MM-HH:MM」
    窗口 + 噪音尾巴；认不得的残留文字（餐秀文案/场次说明）→ 整串
    解析失败返回 []，绝不从散文里猜窗口；
  * 24:00 收口合法；close ≤ open 视为跨零点（+24h 归一）；
  * 「全年全天开放/24小时」→ (00:00, 24:00)。

规则（§三，多段窗口任一段命中即算；「覆盖」取营业窗口与餐段核心窗
有正长交集的口径——「11:30-14:30」这类典型午市店必须算 lunch，闭包
口径会把它们漏光；设计表里 late_night 自带的「∩02:00」同为交集语义）：
  breakfast      开门 ≤09:00
  lunch          与 11:00–14:00 有交集
  dinner         与 17:00–21:00 有交集
  late_night     关门 ≥24:00 或 覆盖 02:00
  early_tea      开门 <10:30 ∧ cuisine_group='粤式茶点'
  afternoon_tea  与 14:00–17:00 有交集 ∧ cuisine_group∈{咖啡烘焙,茶馆茶楼}

cuisine_group 取值即 app/services/cuisine_taxonomy.py 的二级组名
（原值精确比对，None/未映射组不参与茶点两枚举）。

用法（回填）：app/jobs/backfill_meal_periods.py
用法（干跑）：PYTHONPATH=. python -m app.services.meal_periods
"""

from __future__ import annotations

import re

#: 餐段枚举（输出顺序即此序）
MEAL_PERIODS: tuple[str, ...] = (
    "early_tea",
    "breakfast",
    "lunch",
    "afternoon_tea",
    "dinner",
    "late_night",
)

# ---- 规则阈值（分钟数，自 00:00 起） ----
_BREAKFAST_OPEN_MAX = 9 * 60  # breakfast：开门 ≤09:00（含）
_EARLY_TEA_OPEN_MAX = 10 * 60 + 30  # early_tea：开门 <10:30（不含）
_LUNCH_WINDOW = (11 * 60, 14 * 60)  # lunch 覆盖 11:00–14:00
_AFTERNOON_WINDOW = (14 * 60, 17 * 60)  # afternoon_tea 覆盖 14:00–17:00
_DINNER_WINDOW = (17 * 60, 21 * 60)  # dinner 覆盖 17:00–21:00
_MIDNIGHT = 24 * 60  # late_night：关门 ≥24:00
_LATE_MARK = 2 * 60  # late_night：窗口覆盖 02:00

EARLY_TEA_CUISINE_GROUPS = frozenset({"粤式茶点"})
AFTERNOON_TEA_CUISINE_GROUPS = frozenset({"咖啡烘焙", "茶馆茶楼"})

# ---- 解析 ----
#: 括号注释（（汉文化主题演艺…）/（16:30停止入园））——整块剥掉
_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")
#: 时间窗「HH:MM-HH:MM」（分隔符 -/～/至/–；全半角先归一）
_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})[-～–至](\d{1,2}):(\d{2})")
#: 残留散文里的孤立时刻（最晚进入16:30 / 约19:30）——噪音判定时剥掉
_BARE_TIME_RE = re.compile(r"\d{1,2}:\d{2}")
#: 星期/日期前缀（每周一至周五、周二-周日、每天、今天、节假日…）
_DAY_TOKEN_RE = re.compile(
    r"(?:每?周[一二三四五六日天]|星期[一二三四五六日天]|每天|每日|今天|当日|"
    r"全天|全年|节假日|周末|工作日)(?:至|到|-)?"
)
#: 噪音尾巴词表：残留文字不含时刻且含任一词 → 可剥（不为则解析失败）
_NOISE_PHRASES = (
    "为准",
    "公示",
    "官方",
    "现场",
    "当日",
    "当天",
    "具体",
    "通知",
    "公告",
    "调整",
    "开放",
    "营业",
    "关闭",
    "闭园",
    "闭馆",
    "休息",
    "停止",
    "最晚",
    "状态",
    "情况",
    "换票",
)
#: 全半角归一：冒号/连字符/分隔符统一，空白全剥
_FW_TRANS = str.maketrans(
    {
        "：": ":",
        "～": "-",
        "–": "-",
        "—": "-",
        "－": "-",
        "，": ",",
        "、": ",",
        "；": ";",
        "／": "/",
        "。": ";",
    }
)
_SEG_SPLIT_RE = re.compile(r"[,;/|]")
_SEP_CHARS = ",;/|-"


def _normalize(raw: str) -> str:
    """全半角归一 + 去空白。"""
    return "".join(raw.translate(_FW_TRANS).split())


def parse_opening_windows(opening_hours: object) -> list[tuple[int, int]]:
    """opening_hours 串 → 归一窗口列表 [(开, 关)]（跨零点 close 已 +24h）。

    解析不了（含散文残留、格式残缺、空串/None）返回 []，不猜。
    多段窗口（午市+晚市）按段独立解析；任何一段带认不得的文字则整串
    失败——宁可 [] 也不把餐秀场次的散文字段当营业时间。
    """
    s = _normalize(str(opening_hours or ""))
    if not s:
        return []
    s = _PAREN_RE.sub("", s)
    if not s:
        return []
    # 无显式窗口的全天/24小时表述（「全年全天开放」「24小时营业」，
    # 「周一 全天关闭」不中——关闭不是开放）
    if not _RANGE_RE.search(s) and re.search(r"全天开放|全天营业|24小时", s):
        return [(0, _MIDNIGHT)]
    s = _DAY_TOKEN_RE.sub("", s)
    windows: list[tuple[int, int]] = []
    for seg in _SEG_SPLIT_RE.split(s):
        if not seg:
            continue
        matches = list(_RANGE_RE.finditer(seg))
        residue = _RANGE_RE.sub("", seg)
        if not matches:
            # 无窗口段：纯噪音尾巴（节假日以官方通知为准/周一 全天关闭）
            # 可剥；否则整串失败
            if not _is_noise(residue):
                return []
            continue
        # 有窗口段：剥掉残留（噪音+孤立时刻+分隔符）后必须干净
        residue = _BARE_TIME_RE.sub("", residue)
        residue = "".join(ch for ch in residue if ch not in _SEP_CHARS)
        if residue and not _is_noise(residue):
            return []
        for m in matches:
            oh, om, ch, cm = (int(g) for g in m.groups())
            if om > 59 or cm > 59 or oh > 23 or ch > 24:
                return []
            if ch == 24 and cm != 0:
                return []
            open_min, close_min = oh * 60 + om, ch * 60 + cm
            if open_min == close_min:  # 零长窗口（「10:00-10:00」）不猜
                return []
            if close_min < open_min:  # 跨零点（17:00-02:00）
                close_min += _MIDNIGHT
            windows.append((open_min, close_min))
    return windows


def _is_noise(residue: str) -> bool:
    """残留文字是否为可剥噪音：无孤立时刻且含任一噪音词。"""
    residue = _BARE_TIME_RE.sub("", residue)
    if not residue:
        return True
    if re.search(r"[\d:]", residue):
        return False
    return any(p in residue for p in _NOISE_PHRASES)


def _overlaps(w: tuple[int, int], lo: int, hi: int) -> bool:
    """窗口与 [lo,hi) 餐段核心窗有正长交集。"""
    return w[0] < hi and w[1] > lo


def infer_meal_periods(opening_hours: object, cuisine_group: object) -> list[str]:
    """营业时间 + 二级菜系组 → 餐段枚举列表（MEAL_PERIODS 序）。

    解析不了 opening_hours 返回 []（不猜）；cuisine_group 缺失/未映射
    时不产出 early_tea / afternoon_tea（两者带菜系闸）。
    """
    windows = parse_opening_windows(opening_hours)
    if not windows:
        return []
    group = str(cuisine_group or "").strip()
    out: list[str] = []
    if group in EARLY_TEA_CUISINE_GROUPS and any(
        w[0] < _EARLY_TEA_OPEN_MAX for w in windows
    ):
        out.append("early_tea")
    if any(w[0] <= _BREAKFAST_OPEN_MAX for w in windows):
        out.append("breakfast")
    if any(_overlaps(w, *_LUNCH_WINDOW) for w in windows):
        out.append("lunch")
    if group in AFTERNOON_TEA_CUISINE_GROUPS and any(
        _overlaps(w, *_AFTERNOON_WINDOW) for w in windows
    ):
        out.append("afternoon_tea")
    if any(_overlaps(w, *_DINNER_WINDOW) for w in windows):
        out.append("dinner")
    if any(
        w[1] >= _MIDNIGHT or (w[0] <= _LATE_MARK and w[1] >= _LATE_MARK)
        for w in windows
    ):
        out.append("late_night")
    return out


def _dry_run() -> None:  # pragma: no cover — ops 工具入口
    """打印全库推导分布与解析不了样本（只读，不写库）。"""
    from pathlib import Path

    from sqlalchemy import create_engine, text

    env = Path(__file__).resolve().parents[2] / ".env"
    m = re.search(r"DATABASE_URL\s*=\s*(.+)", env.read_text(encoding="utf-8"))
    eng = create_engine(m.group(1).strip() if m else "")
    with eng.connect() as c:
        rows = c.execute(
            text("SELECT opening_hours, cuisine_group FROM restaurants")
        ).all()
    total = len(rows)
    with_hours = sum(1 for oh, _ in rows if oh)
    counts = {p: 0 for p in MEAL_PERIODS}
    unparsable: list[tuple[str, int]] = []
    for oh, grp in rows:
        if not oh:
            continue
        periods = infer_meal_periods(oh, grp)
        if not periods:
            unparsable.append((str(oh), 1))
            continue
        for p in periods:
            counts[p] += 1
    print(f"rows={total} with_opening_hours={with_hours} "
          f"unparsable={len(unparsable)}")
    for p in MEAL_PERIODS:
        print(f"  {p}: {counts[p]}")
    if unparsable:
        print("unparsable samples:")
        for oh, _ in unparsable[:20]:
            print(f"  {oh!r}")


if __name__ == "__main__":
    _dry_run()
