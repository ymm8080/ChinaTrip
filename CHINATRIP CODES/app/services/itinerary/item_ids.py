# -*- coding: utf-8 -*-
"""条目 id 唯一性自愈（2026-11-13 「Day6 磁器口 换点 422 no_match」事故）。

规划 agent 的条目序号 ``_item_seq`` 是**进程级**计数：进程重启归零，而会话
（SQLite 持久化 / 行程库载入）带回来的既有 id 仍是 v1…v30。此后新增条目会
撞上旧 id，同一份计划出现两条 ``item_id=v1``——换点/删除/钉/移动都按 id 首
命中定位，点第六天的卡会命中第三天的同号条目，再拿错城去 POI 库精确匹配，
就是用户看到的 ``422 no_match``（重庆「洪崖洞」在成都库里当然查不到）。

本模块在会话读入与响应出站两个口子做去重自愈：保留首个占用者，后来者改配
同前缀的未占用新号，返回改号留痕（调用方只记日志）。
"""

from __future__ import annotations

import re

_TRAILING_NUM = re.compile(r"^(.*?)(\d+)$")


def _split_item_id(item_id: str) -> tuple[str, int]:
    """``v12`` → (``v``, 12)；不带尾号的原样作前缀、序号 0。"""
    m = _TRAILING_NUM.match(item_id or "")
    if not m:
        return (item_id or "v"), 0
    return (m.group(1) or "v"), int(m.group(2))


def ensure_unique_item_ids(plan: object) -> list[str]:
    """把计划内重复的条目 id 改配成唯一号，返回 ``旧→新`` 留痕列表。

    幂等：没有重号时零改动、零分配。首个占用者保持原 id 不动（前端已渲染的
    卡片指向它不会漂移），后来者改号。
    """
    days = getattr(plan, "days", None) or []
    items = [it for d in days for it in (getattr(d, "items", None) or [])]
    ids = [str(getattr(it, "item_id", "") or "") for it in items]
    if len(set(ids)) == len(ids):
        return []

    used = set(ids)
    next_no: dict[str, int] = {}
    for iid in ids:
        pref, num = _split_item_id(iid)
        if num > next_no.get(pref, 0):
            next_no[pref] = num

    seen: set[str] = set()
    notes: list[str] = []
    for it, iid in zip(items, ids):
        if iid and iid not in seen:
            seen.add(iid)
            continue
        pref, _ = _split_item_id(iid)
        n = next_no.get(pref, 0)
        cand = f"{pref}{n + 1}"
        while cand in used:
            n += 1
            cand = f"{pref}{n + 1}"
        next_no[pref] = n + 1
        try:
            it.item_id = cand
        except Exception:  # noqa: BLE001 - 只读模型/非条目对象：跳过不炸
            continue
        seen.add(cand)
        used.add(cand)
        name = str(getattr(it, "name", "") or "")
        notes.append(f"{iid or '(空)'}→{cand}" + (f"（{name}）" if name else ""))
    return notes
