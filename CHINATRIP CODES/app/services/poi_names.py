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


def place_core(name: str | None) -> str:
    """名字去掉通用尾缀的「地名内核」（朱家角古镇 → 朱家角）。

    只削尾缀，且削完至少留 2 个字；括号补充说明先去掉
    （「朱家角古镇（青浦）」→ 朱家角）。
    """
    s = re.sub(r"[（(][^）)]*[）)]", "", str(name or "")).strip()
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
