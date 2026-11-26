"""POI 名字工具（2026-11-16 朱家角案）：通用地名尾缀归一。

「朱家角古镇」「朱家角镇」「朱家角景区」是同一个地方的不同写法——底库里往
往是三条独立行（ctrip 骨架 / histown 镇 / 4a 景区），规划层同站判定只按字符
包含，两侧都削掉尾缀才认得出。本模块只做这一件事，供心愿接属性
(``wish_seed``)、补建 (``poi_ingest``) 与行程去重 (``plan._town_dup``) 共用。
"""

from __future__ import annotations

import re

#: 名字尾缀（顺序有意义：长的先削，「古镇」先于「镇」）。
PLACE_SUFFIXES = (
    "古镇",
    "古城",
    "水乡",
    "景区",
    "风景区",
    "旅游区",
    "游览区",
    "老街",
    "古街",
)


#: 英文名字尾缀（2026-11-16「ZHUJIAJIAO 认不出」案）：底库英文名是全称
#: 「Zhujiajiao Ancient Town」，用户只写专名「Zhujiajiao」——与中文侧
#: 「朱家角古镇 → 朱家角」同一个道理，只是按词削。**只收「聚落」类尾缀**
#: （镇/村/城）：园林（Garden）、博物馆（Museum）、老街（Old Street）、景区
#: （Scenic Area）一概不削——「Shanghai Old Street」削完只剩城市词
#: Shanghai，任何写 Shanghai 的句子都会把老街拉进必去（2026-11-16 实测）。
PLACE_SUFFIXES_EN = (
    "ancient town",
    "water town",
    "old town",
    "ancient village",
    "water village",
    "ancient city",
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def place_core_en(name: str | None) -> str:
    """英文地名内核（Zhujiajiao Ancient Town → Zhujiajiao）。

    只削词尾通用尾缀，削完至少留 2 个字符；括号补充说明先去掉。
    """
    s = re.sub(r"[（(][^）)]*[）)]", "", str(name or "")).strip()
    s = re.sub(r"\s+", " ", s).strip()
    changed = True
    while changed:
        changed = False
        low = s.lower()
        for suffix in PLACE_SUFFIXES_EN:
            if not low.endswith(suffix):
                continue
            head = s[: -len(suffix)].strip(" ,-–—")
            if not head or not re.search(r"[0-9a-z]", head):
                continue
            if len(head) < 2:
                continue
            s = head
            changed = True
            break
    return s


def place_core(name: str | None) -> str:
    """名字去掉通用尾缀的「地名内核」（朱家角古镇 → 朱家角）。

    只削尾缀，且削完至少留 2 个字；括号补充说明先去掉
    （「朱家角古镇（青浦）」→ 朱家角）。英文名走 :func:`place_core_en`
    （「Zhujiajiao Ancient Town」→ Zhujiajiao），中文侧照旧按字削。
    """
    s = re.sub(r"[（(][^）)]*[）)]", "", str(name or "")).strip()
    if not _CJK_RE.search(s):
        return place_core_en(s)
    s = re.sub(r"\s+", "", s)
    changed = True
    while changed:
        changed = False
        for suffix in PLACE_SUFFIXES:
            if s.endswith(suffix) and len(s) - len(suffix) >= 2:
                s = s[: -len(suffix)]
                changed = True
                break
    if s.endswith("镇") and len(s) - 1 >= 2:
        s = s[:-1]
    return s


# --- 餐槽展示后缀清洗（R28 止污）------------------------------------------

#: 尾部餐槽标注：全角/半角括号包裹的早餐/午餐/晚饭/晚餐/夜宵/下午茶及
#: 英文；忽略大小写。真店名以「（午餐）」结尾的现实概率约等于零，而
#: 槽位标注结尾是展示链惯例（LLM 编辑链产物，来源不可拦），误伤面趋零。
_SLOT_SUFFIX_RE = re.compile(
    r"\s*[（(]\s*"
    r"(?:早餐|早饭|午餐|午饭|中饭|晚饭|晚餐|夜宵|下午茶|"
    r"breakfast|lunch|dinner|supper|afternoon\s+tea|tea)"
    r"\s*[)）]\s*$",
    re.IGNORECASE,
)


def clean_meal_slot_suffix(name: object) -> str:
    """剥掉 POI 展示名尾部的餐槽标注，返回干净名（R28 止污）。

    历史事故链：展示名「虹鱒鱼一条街农家菜（午餐）」被 ``plan._enrich_hours``
    / ``_hours_db_pass`` 原样当 POI 真名 upsert 进库 → 图商检索/换点/详情
    链全用污名 → 检索必失败（WAF/配额白烧）、TA 目录「无过阈候选」、
    污染名永久固化在 pois.name_zh。类级修法：数据入口统一清洗——读库
    查询词、图商检索关键词、写库 upsert、引擎候选名（live ``_candidate``）
    与 legacy 候选名（``candidate_from_poi_dict``）共用本函数，库行脏不
    脏都不外露后缀；LLM 下次再拼，入口再剥，名字永不固化。

    None/空白 → ""；无尾部标注 → 原样 strip；连续标注循环剥净（防御）。
    """
    text = str(name or "").strip()
    if not text:
        return ""
    while True:
        stripped = _SLOT_SUFFIX_RE.sub("", text).strip()
        if stripped == text or not stripped:
            break
        text = stripped
    return text


# --- 拉丁专名容错匹配（2026-11-17 ZHUJIAZUI 案）--------------------------
# 用户打「ZHUJIAZUI」（朱家嘴的拼音，实指朱家角）时底库没有任何行逐字命中：
# 整词/内核两档都是精确匹配，永远不中，只有 LLM 通道能救——而 LLM 把与这
# 个词拼写更近的「陆家嘴 Lujiazui」（编辑距离 2）当成了正确答案（实案：
# 确认卡出现陆家嘴、朱家角古镇反而不见）。这里加第三档「共享词头锚定的容
# 错匹配」：文本词与专名内核共享前缀 ≥6 且整体编辑距离 ≤4 才算命中
# （zhujiazui↔zhujiajiao：共享 zhujia、距离 4 → 中；
#  zhujiazui↔lujiazui：共享前缀 0 → 永不中）。
# 另配 near 口径（距离 ≤3、不管词头）给规划层判定「同一拼错词的 LLM 竞品
# 映射」用，不做命中。
_TYPO_MIN_TOKEN = 6
_TYPO_MIN_PREFIX = 6
_TYPO_MAX_DISTANCE = 4
_TYPO_NEAR_DISTANCE = 3


def _latin_edit_distance(a: str, b: str) -> int:
    """两条小写拉丁串的 Levenshtein 距离（短串，O(len*len) 足够）。"""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _typo_token_ok(value: str) -> bool:
    return len(value) >= _TYPO_MIN_TOKEN and value.isascii() and value.isalpha()


def latin_typo_prefix(token: str, name_token: str) -> int | None:
    """文本词 ≈ 库名专名内核（容错）：共享前缀 ≥6 且整体距离 ≤4 → 返回
    共享前缀长度（当命中分），否则 None。参数不区分大小写。"""
    t = (token or "").strip().lower()
    n = (name_token or "").strip().lower()
    if not _typo_token_ok(t) or not _typo_token_ok(n):
        return None
    shared = 0
    for x, y in zip(t, n):
        if x != y:
            break
        shared += 1
    if shared < _TYPO_MIN_PREFIX:
        return None
    if _latin_edit_distance(t, n) > _TYPO_MAX_DISTANCE:
        return None
    return shared


def latin_typo_near(token: str, name_token: str) -> int | None:
    """文本词与专名内核编辑距离 ≤3（不管词头）→ 返回距离，否则 None。
    只给「同一拼错词的另一个映射」判定用，不做命中。"""
    t = (token or "").strip().lower()
    n = (name_token or "").strip().lower()
    if not _typo_token_ok(t) or not _typo_token_ok(n):
        return None
    dist = _latin_edit_distance(t, n)
    return dist if dist <= _TYPO_NEAR_DISTANCE else None
