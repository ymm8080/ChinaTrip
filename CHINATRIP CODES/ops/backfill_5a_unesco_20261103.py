# -*- coding: utf-8 -*-
# ruff: noqa: E501 — 名录数据表带长中文审计原因（对账出处/拍板依据），不折行
"""backfill_5a_unesco_20261103.py — 5A/UNESCO 档位回建一次性作业（幂等可重跑）.

背景（2026-11-03）：活库 source='5a' 323 行 / source='unesco' 86 行大多
tags 为空或只有子族标（unesco_karst 等），档位没打上；另有名录级缺口
（5A 官方名录 359 行对账差 ~22 条）与 unesco 行名头错位/繁简不一。
本作业五段：
  段1  名录行自打标：source='5a' active 并入 "5a"、source='unesco'
       active 并入 "unesco"（NULL-aware；tags 原来为空的行才置
       tags_source='mct'，非空不动 tags_source）
  段2  5A 缺口回建：2a 无行→seed_upsert 建 5a 骨架（坐标不填，高德
       暂停留待恢复）；2b 有行无档→给指定在册行补 "5a"；2c 降档未修
       →给既有 4a/scenic 行补 "5a"（source 列不动）
  段3  unesco 名头归一：3a 繁体→08 CSV 官方简体（原繁体名入
       name_aliases，tags_source 不动）；3b 名头错位更名；3c 苏州园林
       组件挂 "unesco"；3d duplicate 拍板行保持不动 + 西递/宏村组件补 "5a"
  段4  验证统计 + 变更清单 JSON

写侧纪律：骨架行只走 app.services.poi_seed.seed_upsert（带同馆去重闸
+classify），绝不裸 INSERT；tags_source 写前先过
app.services.source_tier.tags_source_wins（mct=3 高权威）；全程无
DELETE，无 status 置位（退役不归本作业）。

用法（在 `CHINATRIP CODES` 下；.env 仅此目录生效）：
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python.exe ops\\backfill_5a_unesco_20261103.py            # dry-run
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python.exe ops\\backfill_5a_unesco_20261103.py --apply   # 写库
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text  # noqa: E402

from app.db import get_engine, get_session_factory  # noqa: E402
from app.models import Poi  # noqa: E402
from app.services.poi_seed import seed_upsert  # noqa: E402
from app.services.source_tier import order_source_tags, tags_source_wins  # noqa: E402

CHANGES_PATH = (
    Path(__file__).resolve().parent / "backfill_5a_unesco_20261103_changes.json"
)

#: 段2a 建骨架清单（官方名取自 02_5A级旅游景区_358.csv 对名；city=DB 口径
#: 地级市短名；坐标不填——高德全站暂停中，留待恢复后回源补）。
#: core = 预检核心词：若 active 5a 行名中已含该词则视为已就位，跳过建行。
CREATE_5A: list[dict] = [
    {"core": "周恩来", "name": "淮安市周恩来故里景区", "city": "淮安"},
    {"core": "邓小平", "name": "广安市邓小平故里旅游区", "city": "广安"},
    {"core": "朱德", "name": "南充市朱德故里景区", "city": "南充"},
    {"core": "孙中山", "name": "中山市孙中山故里旅游区", "city": "中山"},
    {"core": "革命纪念地", "name": "延安市延安革命纪念地景区", "city": "延安"},
    {"core": "万峰林", "name": "黔西南州万峰林景区", "city": "黔西南"},
    {"core": "托木尔", "name": "阿克苏地区天山托木尔景区", "city": "阿克苏"},
    {"core": "百色起义", "name": "百色市百色起义纪念园景区", "city": "百色"},
]

#: 段2a 预检发现「已有 5a 行」的三条（名录在册但非官方全名）——不建行，
#: 段1 已给它们并 "5a" 标；此处只核验在册并记入变更清单。
CREATE_5A_SKIP_EXIST: list[dict] = [
    {
        "name": "广州长隆",
        "expect_pid": "5a_211",
        "reason": "5a_211 番禺区长隆旅游度假区 在册（同馆旧名），段1 已并标",
    },
    {
        "name": "五大连池",
        "expect_pid": "5a_057",
        "reason": "5a_057 五大连池景区 在册，段1 已并标",
    },
    {
        "name": "镇江金山·焦山·北固山",
        "expect_pid": "5a_079",
        "reason": "5a_079 三山风景名胜区 在册（金山·焦山·北固山 2012 旧名），段1 已并标；官方新名是否改名留拍板",
    },
]

#: 段2b 有行无档：指定在册行补 "5a"（不建骨架行，避免同馆闸吸收高热渠道行）。
TAG_5A_EXISTING: list[dict] = [
    {
        "core": "故宫",
        "source": "museum1",
        "spid": "m1_885978e4c8a2",
        "city": "北京",
        "why": "故宫博物院（museum1 主行）",
    },
    {
        "core": "东方明珠",
        "source": "amap",
        "spid": "ct_上海_1",
        "city": "上海",
        "why": "东方明珠（amap 主行）",
    },
    {
        "core": "喀什古城",
        "source": "street",
        "spid": "st_cf80df9bbf9b",
        "city": "喀什",
        "why": "喀什古城（street 行 st_cf80df9bbf9b）",
    },
    {
        "core": "奥林匹克公园",
        "source": "amap",
        "spid": "ct_北京_12",
        "city": "北京",
        "why": "北京奥林匹克公园（baidu/amap 主行中取 amap——回填铁律序 amap 在列、baidu 不在）",
    },
]

#: 段2b 预检改判：千岛湖不是「有行无档」——5a_096 淳安县千岛湖风景区
#: 就是 source='5a' 主行，段1 覆盖，此处只核验。
TAG_5A_REDIRECT_5A_096 = {"core": "千岛湖", "expect_pid": "5a_096"}

#: 段2c 降档未修：既有 4a/scenic 行补 "5a"（source 列不动）。
TAG_5A_DOWNGRADED: list[dict] = [
    {
        "core": "老牛湾",
        "source": "4a",
        "spid": "4a_0335",
        "city": "呼和浩特",
        "why": "老牛湾黄河大峡谷旅游区——5A 名录 2024 条目为呼和浩特市老牛湾黄河大峡谷旅游区（4a_1360 偏关县/忻州是山西侧另一名录行，不打）",
    },
    {
        "core": "扎龙",
        "source": "4a",
        "spid": "4a_4665",
        "city": "齐齐哈尔",
        "why": "扎龙生态旅游区——名录全名齐齐哈尔市扎龙生态旅游区",
    },
    {
        "core": "宝泉",
        "source": "4a",
        "spid": "4a_2711",
        "city": "新乡",
        "why": "新乡市宝泉旅游度假区——名录全名新乡市宝泉旅游区",
    },
    {
        "core": "六盘山",
        "source": "4a",
        "spid": "4a_0968",
        "city": "固原",
        "why": "六盘山国家森林公园——名录全名固原市六盘山红军长征旅游区",
    },
    {
        "core": "东湖",
        "source": "scenic",
        "spid": "scenic_0131",
        "city": "武汉",
        "why": "武汉东湖风景名胜区——名录全名武汉市东湖生态旅游风景区",
    },
]

#: 段3a 繁体→08 CSV 官方简体（unesco 行）。old_expected 为预检须命中的
#: 现名（对不上即跳过不硬改）。alias_extra = 除旧名外要一并入别名的写法。
RENAME_UNESCO: list[dict] = [
    {"spid": "unesco_Q308805", "old": "雲岡石窟", "new": "云冈石窟"},
    {"spid": "unesco_Q15660376", "old": "杭州西湖文化景觀", "new": "杭州西湖文化景观"},
    {"spid": "unesco_Q1286650", "old": "中國丹霞", "new": "中国丹霞"},
    {"spid": "unesco_Q2601433", "old": "澳門歷史城區", "new": "澳门历史城区"},
    {
        "spid": "unesco_Q15904183",
        "old": "良渚遺址",
        "new": "良渚古城遗址",
        "alias_extra": ["良渚遗址"],
    },
    {
        "spid": "unesco_Q4920250",
        "old": "北京及瀋陽的明清皇家宮殿",
        "new": "明清故宫（北京故宫、沈阳故宫）",
        "alias_extra": ["北京及沈阳的明清皇家宫殿"],
    },
]

#: 段3b 名头错位更名。
RENAME_MISPLACED: list[dict] = [
    {
        "spid": "unesco_Q4047",
        "old": "庐山第四纪冰川国家地质公园",
        "new": "庐山国家公园",
    },
    {"spid": "unesco_Q499552", "old": "周口店遗址", "new": "周口店北京人遗址"},
]

#: 段3a 预检判「CSV 对不上」的繁体行——只报告不硬改（澳门系组件 +
#: 高句丽组件角抵塚均为名录内部组件，08 CSV 只有整城/整名录条目）。
TRAD_REPORT_ONLY: list[str] = [
    "unesco_Q1106554 聖母聖誕主教座堂",
    "unesco_Q2149114 媽閣廟",
    "unesco_Q2200748 三街會館",
    "unesco_Q3181816 民政總署大樓",
    "unesco_Q3182054 伯多祿五世劇院",
    "unesco_Q3271236 聖老楞佐堂",
    "unesco_Q3313058 東望洋燈塔",
    "unesco_Q3320500 何東圖書館",
    "unesco_Q3504601 基督教墳場",
    "unesco_Q4130614 玫瑰聖母堂",
    "unesco_Q4310094 仁慈堂大樓",
    "unesco_Q4570262 東方基金會會址",
    "unesco_Q4579079 聖若瑟修院及聖堂",
    "unesco_Q4587786 聖奧斯定教堂",
    "unesco_Q46074 馬禮遜教堂",
    "unesco_Q6730067 聖母雪地殿教堂",
    "unesco_Q6730196 聖安多尼教堂 (澳門)",
    "unesco_Q837935 議事亭前地",
    "unesco_Q838085 大炮台",
    "unesco_Q137838681 角抵塚（高句丽组件墓）",
]

#: 段3c 苏州园林组件挂 "unesco"：(source, source_poi_id, 核验名核心词)。
#: 拙政园（unesco_Q1076650）已有 "unesco" 不重复；虎丘用别名行
#: amap 虎丘山风景名胜区（aliases 含「虎丘」，官方名录拙政园－留园－
#: 虎丘即含虎丘）。
SUZHOU_COMPONENTS: list[dict] = [
    {"source": "amap", "spid": "ct_苏州_6", "core": "留园"},
    {"source": "amap", "spid": "ct_苏州_12", "core": "网师园"},
    {"source": "amap", "spid": "ct_苏州_4", "core": "狮子林"},
    {"source": "amap", "spid": "ct_苏州_13", "core": "沧浪亭"},
    {"source": "amap", "spid": "ct_苏州_71", "core": "环秀山庄"},
    {"source": "amap", "spid": "ct_苏州_36", "core": "艺圃"},
    {"source": "amap", "spid": "ct_苏州_17", "core": "耦园"},
    {"source": "amap", "spid": "ct_苏州_68", "core": "退思园"},
    {"source": "amap", "spid": "ct_苏州_5", "core": "虎丘山风景名胜区"},
]

CHANGES: dict = {
    "run_at": datetime.now().isoformat(timespec="seconds"),
    "applied": False,
    "section1_selftag": [],
    "section2": {
        "2a_created": [],
        "2a_skip_exist": [],
        "2b_tagged": [],
        "2b_redirect": [],
        "2c_tagged": [],
    },
    "section3": {
        "3a_renamed": [],
        "3b_renamed": [],
        "3a_report_only": TRAD_REPORT_ONLY,
        "3c_tagged": [],
        "3c_already": [],
        "3d_kept_duplicate": [],
        "3d_tagged": [],
    },
    "verification": {},
}


def snap(row: Poi) -> dict:
    """行写前快照（进变更清单用）。"""
    return {
        "pid": f"{row.source}_{row.source_poi_id}",
        "name_zh": row.name_zh,
        "city": row.city,
        "status": row.status,
        "tags": list(row.tags or []),
        "tags_source": row.tags_source,
    }


def merge_grade_tag(
    session, row: Poi, tag: str, *, bump_source_always: bool, why: str, apply: bool
) -> dict | None:
    """给行并入档位标（读改写整个 list，不 SQL 拼串）。

    tags_source 规则：段1（bump_source_always=False）只在 tags 原来为空
    时置 mct；段2/3（True）按 tags_source_wins 放行即置 mct。
    返回变更记录（无变化返回 None，保幂等）；apply=False 只出计划不动行。
    """
    before = snap(row)
    old_tags = list(row.tags or [])
    if tag in old_tags:
        return None
    new_tags = order_source_tags(sorted(set(old_tags + [tag])))
    after_src = None
    if bump_source_always:
        if tags_source_wins("mct", row.tags_source) and row.tags_source != "mct":
            after_src = {"from": row.tags_source, "to": "mct"}
    elif not old_tags:
        if tags_source_wins("mct", row.tags_source) and row.tags_source != "mct":
            after_src = {"from": row.tags_source, "to": "mct"}
    after = {
        **before,
        "tags": new_tags,
        "tags_source": "mct" if after_src else before["tags_source"],
    }
    if apply:
        row.tags = new_tags
        if after_src:
            row.tags_source = "mct"
        session.commit()
    print(
        f"  [tag+{tag}{'(计划)' if not apply else ''}] {before['pid']} {before['name_zh']}: {before['tags']} -> {new_tags}"
        + (f" tags_source {after_src['from']}->mct" if after_src else "")
    )
    rec = {
        "why": why,
        "before": before,
        "after": after,
        "tags_source_change": after_src,
    }
    if not apply:
        rec["planned"] = True
    return rec


def get_row(session, source: str, spid: str) -> Poi | None:
    return session.query(Poi).filter_by(source=source, source_poi_id=spid).one_or_none()


def show_precheck(rows: list[Poi], title: str) -> None:
    print(f"  预检 {title}: {len(rows)} 行")
    for r in rows:
        print(
            f"    {r.source}_{r.source_poi_id} | {r.name_zh} | {r.city} | {r.status} | {r.tags}"
        )


# ---------------------------------------------------------------- 段1


def section1(session, apply: bool) -> None:
    print("== 段1 名录行自打标 ==")
    for source, tag in (("5a", "5a"), ("unesco", "unesco")):
        rows = (
            session.query(Poi)
            .filter(Poi.source == source, Poi.status == "active")
            .all()
        )
        targets = [r for r in rows if not (r.tags or []) or tag not in r.tags]
        show_precheck(targets, f"source='{source}' active 缺 \"{tag}\" 标")
        n = 0
        for row in targets:
            rec = merge_grade_tag(
                session,
                row,
                tag,
                bump_source_always=False,
                why=f"段1 source='{source}' 自打标",
                apply=apply,
            )
            if rec:
                CHANGES["section1_selftag"].append(rec)
                n += 1
        print(f"  段1 {source}: 实改 {n} 行")


# ---------------------------------------------------------------- 段2


def next_5a_id(session) -> int:
    rows = session.query(Poi.source_poi_id).filter(Poi.source == "5a").all()
    mx = 0
    for (spid,) in rows:
        suffix = (spid or "").rsplit("_", 1)[
            -1
        ]  # '5a_341' -> '341'（前缀 5a_ 带 5，不能全串取数字）
        if suffix.isdigit():
            mx = max(mx, int(suffix))
    return mx


def section2(session, fac, apply: bool) -> None:
    print("== 段2 5A 缺口回建 ==")
    cur_max = next_5a_id(session)
    print(f"  当前 source='5a' 最大编号: 5a_{cur_max:03d}")

    # ---- 2a 建骨架
    for i, item in enumerate(CREATE_5A):
        core, name, city = item["core"], item["name"], item["city"]
        twins = session.query(Poi).filter(Poi.name_zh.like(f"%{core}%")).all()
        show_precheck(twins, f"2a[{name}] 核心词「{core}」孪生生态")
        clash = [
            r
            for r in twins
            if r.source == "5a" and r.status == "active" and core in (r.name_zh or "")
        ]
        if clash:
            print(
                f"  2a 跳过 {name}: active 5a 行已在册 {clash[0].source}_{clash[0].source_poi_id}"
            )
            CHANGES["section2"]["2a_skip_exist"].append(
                {
                    "name": name,
                    "reason": "active 5a 行已在册",
                    "pid": clash[0].source + "_" + clash[0].source_poi_id,
                }
            )
            continue
        n = cur_max + 1 + i
        spid = f"5a_{n:03d}"
        print(
            f"  2a {'计划' if not apply else '建'}骨架 {spid} {name} @{city}（tags=['5a'], tags_source='mct', 坐标不填——高德暂停留待恢复）"
        )
        if not apply:
            CHANGES["section2"]["2a_created"].append(
                {
                    "spid": spid,
                    "name": name,
                    "city": city,
                    "outcome": "planned",
                    "planned": True,
                }
            )
            continue
        outcome = seed_upsert(
            fac,
            Poi,
            source="5a",
            source_poi_id=spid,
            city=city,
            name_zh=name,
            tags=["5a"],
            tags_source="mct",
            origin="cn_sync",
        )
        row = get_row(session, "5a", spid)
        rec = {
            "spid": spid,
            "name": name,
            "city": city,
            "outcome": outcome,
            "status": row.status if row else None,
            "absorbed_retired": None,
            "note": "坐标未填（高德全站暂停中，恢复后回源补）",
        }
        if row is None or row.status != "active":
            rec["error"] = f"建行后核验失败 status={row.status if row else 'MISSING'}"
        print(f"  2a 结果 {spid}: {outcome} status={rec['status']}")
        CHANGES["section2"]["2a_created"].append(rec)

    # ---- 2a 已在册三条核验（不改）
    for item in CREATE_5A_SKIP_EXIST:
        spid = item["expect_pid"]
        row = get_row(session, "5a", spid)
        ok = row is not None
        rec = {
            "name": item["name"],
            "expect_pid": spid,
            "found": ok,
            "reason": item["reason"],
            "row": snap(row) if ok else None,
        }
        print(
            f"  2a 在册核验 {item['name']}: {'OK ' + (snap(row)['name_zh'] or '') if ok else '未找到 ' + spid}"
        )
        CHANGES["section2"]["2a_skip_exist"].append(rec)

    # ---- 2b 有行无档补标
    for item in TAG_5A_EXISTING:
        row = get_row(session, item["source"], item["spid"])
        if row is None:
            print(f"  2b 跳过 {item['why']}: 行不存在 {item['source']}_{item['spid']}")
            CHANGES["section2"]["2b_tagged"].append(
                {"why": item["why"], "error": "行不存在", "spid": item["spid"]}
            )
            continue
        s = snap(row)
        name_ok = item["core"] in (s["name_zh"] or "") or (
            item["source"] == "street"
            and item["core"] in str(getattr(row, "name_aliases", None) or "")
        )
        city_ok = (s["city"] or "") == item["city"]
        if s["status"] != "active" or not name_ok or not city_ok:
            print(
                f"  2b 跳过 {item['why']}: 预检不符 status={s['status']} name={s['name_zh']} city={s['city']}"
            )
            CHANGES["section2"]["2b_tagged"].append(
                {"why": item["why"], "error": "预检不符", "before": s}
            )
            continue
        rec = merge_grade_tag(
            session,
            row,
            "5a",
            bump_source_always=True,
            why=f"段2b {item['why']}",
            apply=apply,
        )
        if rec:
            CHANGES["section2"]["2b_tagged"].append(rec)
        else:
            print(f"  2b 已有标（幂等跳过）{item['why']}")
            CHANGES["section2"]["2b_tagged"].append(
                {"why": item["why"], "already": True, "before": s}
            )

    # ---- 2b 千岛湖改判核验（5a_096 主行，段1 覆盖）
    row = get_row(session, "5a", "5a_096")
    ok = row is not None and row.status == "active"
    rec = {
        "core": TAG_5A_REDIRECT_5A_096["core"],
        "expect_pid": "5a_096",
        "found": ok,
        "reason": "千岛湖非「有行无档」——5a_096 淳安县千岛湖风景区即 source='5a' 主行，段1 已并入 \"5a\"",
        "row": snap(row) if ok else None,
    }
    print(
        f"  2b 改判核验 千岛湖: 5a_096 {'OK ' + (snap(row)['name_zh'] or '') if ok else '未找到'}"
    )
    CHANGES["section2"]["2b_redirect"].append(rec)

    # ---- 2c 降档未修补标
    for item in TAG_5A_DOWNGRADED:
        row = get_row(session, item["source"], item["spid"])
        if row is None:
            print(f"  2c 跳过 {item['why']}: 行不存在 {item['source']}_{item['spid']}")
            CHANGES["section2"]["2c_tagged"].append(
                {"why": item["why"], "error": "行不存在", "spid": item["spid"]}
            )
            continue
        s = snap(row)
        name_ok = item["core"] in (s["name_zh"] or "")
        city_ok = (s["city"] or "") == item["city"]
        if s["status"] != "active" or not name_ok or not city_ok:
            print(
                f"  2c 跳过 {item['why']}: 预检不符 status={s['status']} name={s['name_zh']} city={s['city']}"
            )
            CHANGES["section2"]["2c_tagged"].append(
                {"why": item["why"], "error": "预检不符", "before": s}
            )
            continue
        rec = merge_grade_tag(
            session,
            row,
            "5a",
            bump_source_always=True,
            why=f"段2c {item['why']}",
            apply=apply,
        )
        if rec:
            CHANGES["section2"]["2c_tagged"].append(rec)
        else:
            print(f"  2c 已有标（幂等跳过）{item['why']}")
            CHANGES["section2"]["2c_tagged"].append(
                {"why": item["why"], "already": True, "before": s}
            )


# ---------------------------------------------------------------- 段3


def rename_unesco(session, item: dict, kind: str, apply: bool) -> None:
    spid, old, new = item["spid"], item["old"], item["new"]
    row = get_row(session, "unesco", spid)
    if row is None:
        print(f"  {kind} 跳过 {spid}: 行不存在")
        CHANGES["section3"][f"{kind}_renamed"].append(
            {"spid": spid, "error": "行不存在"}
        )
        return
    before = snap(row)
    if before["name_zh"] == new:
        print(f"  {kind} 已是官方名（幂等跳过）{spid} {new}")
        CHANGES["section3"][f"{kind}_renamed"].append(
            {"spid": spid, "already": True, "name_zh": new}
        )
        return
    if before["name_zh"] != old:
        print(
            f"  {kind} 跳过 {spid}: 现名「{before['name_zh']}」与预期「{old}」不符，不硬改"
        )
        CHANGES["section3"][f"{kind}_renamed"].append(
            {"spid": spid, "error": "现名与预期不符", "before": before}
        )
        return
    aliases = list(row.name_aliases or [])
    for a in [old] + list(item.get("alias_extra", [])):
        if a not in aliases:
            aliases.append(a)
    aliases = [a for a in aliases if a != new]  # 别名不与现名重复
    after = {**before, "name_zh": new, "tags_source": before["tags_source"]}
    if apply:
        row.name_zh = new
        row.name_aliases = aliases or None
        session.commit()
        after = snap(row)
    print(
        f"  {kind} {'计划' if not apply else ''}{spid}: {old} -> {new}（旧名入别名，tags_source 不动={before['tags_source']}）"
    )
    rec = {"spid": spid, "before": before, "after": after, "aliases_after": aliases}
    if not apply:
        rec["planned"] = True
    CHANGES["section3"][f"{kind}_renamed"].append(rec)


def section3(session, apply: bool) -> None:
    print("== 段3 unesco 名头归一 ==")
    for item in RENAME_UNESCO:
        rename_unesco(session, item, "3a", apply)
    for item in RENAME_MISPLACED:
        rename_unesco(session, item, "3b", apply)

    print("  3a 报告不改（CSV 对不上的繁体组件行）:")
    for s in TRAD_REPORT_ONLY:
        print(f"    {s}")

    # ---- 3c 苏州组件挂标
    for item in SUZHOU_COMPONENTS:
        row = get_row(session, item["source"], item["spid"])
        if row is None:
            print(f"  3c 跳过 {item['spid']}: 行不存在")
            CHANGES["section3"]["3c_tagged"].append(
                {"spid": item["spid"], "error": "行不存在"}
            )
            continue
        s = snap(row)
        aliases = str(getattr(row, "name_aliases", None) or "")
        name_ok = item["core"] in (s["name_zh"] or "") or item["core"] in aliases
        if s["status"] != "active" or s["city"] != "苏州" or not name_ok:
            print(
                f"  3c 跳过 {item['spid']}: 预检不符 status={s['status']} city={s['city']} name={s['name_zh']}"
            )
            CHANGES["section3"]["3c_tagged"].append(
                {"spid": item["spid"], "error": "预检不符", "before": s}
            )
            continue
        rec = merge_grade_tag(
            session,
            row,
            "unesco",
            bump_source_always=True,
            why=f"段3c 苏州园林组件「{s['name_zh']}」",
            apply=apply,
        )
        if rec:
            CHANGES["section3"]["3c_tagged"].append(rec)
        else:
            print(f"  3c 已有标（幂等跳过）{s['name_zh']}")
            CHANGES["section3"]["3c_already"].append(s)

    # 拙政园已有标核验
    zz = get_row(session, "unesco", "unesco_Q1076650")
    if zz is not None and "unesco" in (zz.tags or []):
        print('  3c 拙政园 unesco_Q1076650 已有 "unesco" 标，跳过')
        CHANGES["section3"]["3c_already"].append(snap(zz))

    # ---- 3d duplicate 拍板行保持不动
    for spid in ("5a_067", "5a_117"):
        row = get_row(session, "5a", spid)
        if row is None:
            print(f"  3d {spid}: 未找到（异常，记录）")
            CHANGES["section3"]["3d_kept_duplicate"].append(
                {"spid": spid, "error": "未找到"}
            )
            continue
        s = snap(row)
        if s["status"] == "duplicate":
            print(
                f"  3d {spid} {s['name_zh']}: status='duplicate' 按拍板保持不动（组件行代表，不复活）"
            )
            CHANGES["section3"]["3d_kept_duplicate"].append(
                {"spid": spid, "kept": True, "row": s}
            )
        else:
            print(
                f"  3d {spid} {s['name_zh']}: status={s['status']}（非 duplicate，记录不硬改）"
            )
            CHANGES["section3"]["3d_kept_duplicate"].append(
                {"spid": spid, "kept": False, "row": s}
            )

    # ---- 3d 西递/宏村 active 组件行补 "5a"
    for spid, core in (("histvillage_0197", "西递"), ("histvillage_0198", "宏村")):
        row = get_row(session, "histvillage", spid)
        if row is None:
            print(f"  3d 跳过 {spid}: 行不存在（留拍板）")
            CHANGES["section3"]["3d_tagged"].append(
                {"spid": spid, "error": "行不存在——留拍板"}
            )
            continue
        s = snap(row)
        if s["status"] != "active" or core not in (s["name_zh"] or ""):
            print(
                f"  3d 跳过 {spid}: 预检不符 status={s['status']} name={s['name_zh']}（留拍板）"
            )
            CHANGES["section3"]["3d_tagged"].append(
                {"spid": spid, "error": "预检不符——留拍板", "before": s}
            )
            continue
        rec = merge_grade_tag(
            session,
            row,
            "5a",
            bump_source_always=True,
            why=f"段3d 西递/宏村组件「{s['name_zh']}」（5a_117 保持 duplicate）",
            apply=apply,
        )
        if rec:
            CHANGES["section3"]["3d_tagged"].append(rec)
        else:
            print(f"  3d 已有标（幂等跳过）{s['name_zh']}")
            CHANGES["section3"]["3d_tagged"].append(
                {"spid": spid, "already": True, "before": s}
            )


# ---------------------------------------------------------------- 段4


def section4(engine) -> None:
    print("== 段4 验证 ==")
    checks: dict = {}
    with engine.connect() as conn:
        q5a = text(
            "SELECT count(*) FROM pois WHERE source='5a' AND status='active' "
            "AND coalesce(tags::text,'') NOT LIKE '%\"5a\"%'"
        )
        qun = text(
            "SELECT count(*) FROM pois WHERE source='unesco' AND status='active' "
            "AND coalesce(tags::text,'') NOT LIKE '%\"unesco\"%'"
        )
        checks["5a_active_missing_tag"] = conn.execute(q5a).scalar()
        checks["unesco_active_missing_tag"] = conn.execute(qun).scalar()
        print(
            f"  source='5a' active 缺 \"5a\" 标: {checks['5a_active_missing_tag']}（应为 0）"
        )
        print(
            f"  source='unesco' active 缺 \"unesco\" 标: {checks['unesco_active_missing_tag']}（应为 0）"
        )

        pids_2a = [
            (r["spid"], r["name"])
            for r in CHANGES["section2"]["2a_created"]
            if "spid" in r
        ]
        bad = []
        for spid, name in pids_2a:
            row = conn.execute(
                text(
                    "SELECT status, name_zh FROM pois WHERE source='5a' AND source_poi_id=:p"
                ),
                {"p": spid},
            ).one_or_none()
            ok = row is not None and row[0] == "active" and row[1] == name
            if not ok:
                bad.append(
                    {"spid": spid, "found": None if row is None else [row[0], row[1]]}
                )
        checks["section2a_all_active"] = not bad
        print(
            f"  段2a 建行核验: {len(pids_2a)} 行全部 active+官方名 -> {'OK' if not bad else bad}"
        )

        tagged = []  # (pid, 期望档)
        for key in ("2b_tagged", "2c_tagged"):
            for r in CHANGES["section2"][key]:
                if "after" in r:
                    tagged.append((r["after"]["pid"], "5a"))
        for r in CHANGES["section3"]["3c_tagged"]:
            if "after" in r:
                tagged.append((r["after"]["pid"], "unesco"))
        for r in CHANGES["section3"]["3d_tagged"]:
            if "after" in r:
                tagged.append((r["after"]["pid"], "5a"))
        bad2 = []
        for pid, want in tagged:
            source, spid = pid.split(
                "_", 1
            )  # pid 形如 amap_ct_上海_1：source=首段，spid=其余
            row = conn.execute(
                text(
                    "SELECT tags::text FROM pois WHERE source=:s AND source_poi_id=:p"
                ),
                {"s": source, "p": spid},
            ).one_or_none()
            ok = row is not None and f'"{want}"' in (row[0] or "")
            if not ok:
                bad2.append(
                    {"pid": pid, "want": want, "tags": None if row is None else row[0]}
                )
        checks["section23_tagged_ok"] = not bad2
        print(
            f"  段2/3 补标核验: {len(tagged)} 行 tags 含目标档 -> {'OK' if not bad2 else bad2}"
        )

        renamed = []
        for key in ("3a_renamed", "3b_renamed"):
            for r in CHANGES["section3"][key]:
                if "after" in r:
                    renamed.append(r["after"])
        bad3 = []
        for a in renamed:
            # after.pid 形如 unesco_unesco_Q308805：spid=去掉首段后的剩余
            spid = a["pid"].split("_", 1)[1]
            row = conn.execute(
                text(
                    "SELECT name_zh, name_aliases::text FROM pois WHERE source='unesco' AND source_poi_id=:p"
                ),
                {"p": spid},
            ).one_or_none()
            ok = (
                row is not None
                and row[0] == a["name_zh"]
                and a["name_zh"] not in (row[1] or "")
            )
            if not ok:
                bad3.append(
                    {"spid": spid, "found": None if row is None else [row[0], row[1]]}
                )
        checks["section3_renamed_ok"] = not bad3
        print(
            f"  段3 更名核验: {len(renamed)} 行新名就位+别名带旧名 -> {'OK' if not bad3 else bad3}"
        )

    CHANGES["verification"] = checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库；缺省只打印")
    apply_flag = ap.parse_args().apply
    CHANGES["applied"] = apply_flag

    fac = get_session_factory()
    engine = get_engine()

    with fac() as session:
        section1(session, apply_flag)
        section2(session, fac, apply_flag)
        section3(session, apply_flag)

    if apply_flag:
        section4(engine)
    else:
        CHANGES["verification"] = {"skipped": "dry-run"}

    CHANGES["run_at"] = datetime.now().isoformat(timespec="seconds")
    with open(CHANGES_PATH, "w", encoding="utf-8") as f:
        json.dump(CHANGES, f, ensure_ascii=False, indent=2)
    print(f"变更清单已写 {CHANGES_PATH}（applied={apply_flag}）")
    if not apply_flag:
        print("dry-run only — 复跑加 --apply 写库")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
