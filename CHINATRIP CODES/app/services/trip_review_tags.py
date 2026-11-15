"""trip.com 评论正文 → 餐厅点评标签 规则抽取（DESIGN tag_implementation_decisions_2026-11-12 §D4）。

可行性实证（2026-11-12）：外部结构化点评标签通道全不存在（携程国内美食
JS 壳 / trip.com /restaurants 404 / 点评美团反爬墙 / baidu·amap 无字段），
唯一活口 = trip.com moments POI 页（SSR 1MB）的评论正文——场景词在正文
里（「建議有重要約會或者紀念日來」「人均400+坐擁外灘夜景」）。

决策：关键词规则抽取，**不用 LLM**（零配额依赖、确定性可测）。
同一标签须在 ≥2 条独立评论正文命中（防单条噪声/标题党）；繁简英三语
关键词共用一张表；命中按票数降序，票数同则按词表序（稳定输出）。

词表（DESIGN §五 外部可采 7 词）映射见 _RULES；未见过的标签不发明。
"""

from __future__ import annotations

import re

# (标签, 关键词)；繁简混排同列——trip.com 港台用户正文常见繁体
_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "约会氛围",
        ("约会", "約會", "纪念日", "紀念日", "求婚", "romantic", "date night", "anniversary"),
    ),
    (
        "江景夜景位",
        ("江景", "夜景", "河景", "外滩", "外灘", "海景", "窗边", "窗邊", "灯光秀", "燈光秀", "river view", "night view", "skyline"),
    ),
    (
        "老字号",
        ("老字号", "老字號", "百年老店", "老店", "创始于", "創始於", "time-honored"),
    ),
    (
        "深夜营业",
        ("深夜", "宵夜", "宵夜檔", "凌晨", "夜宵", "营业到", "營業到", "通宵", "late night", "after midnight"),
    ),
    (
        "本地人常去",
        ("本地人", "当地人", "當地人", "街坊", "回头客", "回頭客", "where locals", "locals eat"),
    ),
    (
        "商务宴请",
        ("商务", "商務", "宴请", "宴請", "包间", "包間", "包厢", "包廂", "business dinner", "business meal", "private room"),
    ),
    (
        "家庭聚餐",
        ("家庭", "带娃", "帶娃", "带孩子", "帶孩子", "亲子", "親子", "多人", "聚会", "聚會", "family", "kids", "group dinner"),
    ),
]

_MIN_HITS = 2  # 同标签须 ≥2 条独立正文命中

# trip.com moments 页正文常见载体：JSON 字符串数组里的 "content":"…"
# （type 0 文本节点）；从 SSR HTML 直接抽，不做 DOM 解析
_CONTENT_RE = re.compile(r'"content":"((?:[^"\\]|\\.)*)"')

_UNESCAPES = (
    ("\\n", "\n"),
    ("\\t", " "),
    ('\\"', '"'),
    ("\\/", "/"),
)

_UNICODE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _unescape(s: str) -> str:
    for k, v in _UNESCAPES:
        s = s.replace(k, v)
    # JSON \uXXXX → 字符（繁简正文两种形态都出现）
    return _UNICODE_RE.sub(lambda m: chr(int(m.group(1), 16)), s)


def extract_prose(html: str) -> list[str]:
    """从 trip.com POI 页 HTML 抽评论正文片段（content JSON 节点）。

    过短（<8 字符）与纯 URL 片段丢弃；返回原顺序去重列表。
    """
    out: list[str] = []
    seen: set[str] = set()
    for m in _CONTENT_RE.finditer(html or ""):
        text = _unescape(m.group(1)).strip()
        if len(text) < 8:
            continue
        if text.lower().startswith(("http://", "https://")):
            continue
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def extract_review_tags(prose: list[str] | None, *, min_hits: int = _MIN_HITS) -> list[str]:
    """评论正文列表 → 点评标签（≥min_hits 条独立正文命中同一标签才算）。

    命中计数按「出现过该关键词的正文条数」（同一正文重复命中只计一次）；
    输出按票数降序、同票按词表序；无关正文直接忽略，全不达标返回 []。
    """
    texts = [t for t in (prose or []) if isinstance(t, str) and t]
    if not texts:
        return []
    scored: list[tuple[int, int, str]] = []  # (票数, 词表序, 标签)
    lowered = [t.lower() for t in texts]
    for idx, (tag, keywords) in enumerate(_RULES):
        kws = [k.lower() for k in keywords]
        # 并集语义：一条正文含该标签任一关键词即算命中该正文
        hits = sum(1 for t in lowered if any(k in t for k in kws))
        if hits >= min_hits:
            scored.append((hits, idx, tag))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [tag for _, _, tag in scored]
