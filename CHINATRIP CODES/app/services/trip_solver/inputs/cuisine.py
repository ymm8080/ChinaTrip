# -*- coding: utf-8 -*-
"""R12-D 菜系键（2026-11-19 用户拍板「选餐点：餐卡离景点近，并且尽量不
要同样的菜肴——两家烤鸭店同日不合适」）：纯函数、零依赖——从池行的
name+intro 关键词推菜系键，供候选携带与目标层做同菜系不重样罚项。

口径保守：识别不出 → None（不参与不重样约束）。关键词按菜系名+招牌菜
双通道（「提督·TIDU」名字不含烤鸭、intro 明写「新派烤鸭/提督烤鸭」——
intro 是烤鸭类目的关键信号）。
"""

from __future__ import annotations

from typing import Any, Optional

_CUISINE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("烤鸭", ("烤鸭", "烧鹅烤鸭")),
    ("火锅", ("火锅", "涮肉", "涮锅", "串串", "打边炉")),
    ("川菜", ("川菜", "麻辣", "水煮鱼", "冒菜", "钵钵鸡", "麻婆")),
    ("粤菜", ("粤菜", "早茶", "烧腊", "肠粉", "乳鸽", "避风塘")),
    ("江浙菜", ("江浙", "本帮", "杭帮", "淮扬", "苏帮", "西湖醋鱼")),
    ("湘菜", ("湘菜", "剁椒", "小炒黄牛")),
    ("西北菜", ("西北菜", "羊肉泡馍", "肉夹馍", "油泼面")),
    ("日料", ("日料", "寿司", "刺身", "居酒屋", "omakase", "怀石")),
    ("西餐", ("西餐", "牛排", "意大利", "法餐", "bistro", "steak")),
    ("烧烤", ("烧烤", "烤肉", "串烧")),
    ("素食", ("素食", "素斋")),
    ("咖啡茶饮", ("咖啡", "茶馆", "下午茶")),
)


def cuisine_key(row: dict[str, Any]) -> Optional[str]:
    """池行 → 菜系键（None=识别不出）。只对 food 品类行调用。"""
    if (row.get("category") or "") != "food":
        return None
    text = "%s %s" % (row.get("name") or "", row.get("intro") or "")
    for key, marks in _CUISINE_KEYWORDS:
        if any(m in text for m in marks):
            return key
    return None
