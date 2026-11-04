# -*- coding: utf-8 -*-
"""公园清洗第二轮执行（2026-11-03）：对 round2 扫描的 active 行处置——
建议删 41 组普通公园 → status='inactive'（软删，与第一轮同口径）；
场馆子点位 → category='entertainment'（用户 10-31 拍板口径）；
酒店误标行 → category='hotel' 保持 active（用户 10-31 拍板：不隐藏）；
其余服务行（观光车/地铁站/售票）→ status='inactive'。
回滚语句见日志文件。"""

import io
import re
from datetime import datetime

from sqlalchemy import create_engine, text

SRC = r"D:/CHINATRIP/CHINATRIP CODES/ops/parks_cleanup_round2_2026-11-03.md"
LOG = SRC  # 记录追加进同档

s = io.open(SRC, encoding="utf-8").read()


def parse(title, nxt):
    sec = s.split(title)[1]
    if nxt:
        sec = sec.split(nxt)[0]
    out = []
    for ln in sec.splitlines():
        m = re.match(r"- (.*?)｜(.+?)｜", ln)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


ordinary = parse("## 建议删：普通地方性公园", "## 灰区")
venue = parse("## 附B：场馆子点位", None)
noise = parse("## 附A：酒店误标行", "## 附B")
HOTEL_PAT = re.compile(r"酒店|饭店|宾馆|民宿|公寓|客栈|旅馆|招待所|青旅|悦榕庄|美宿")
VENUE_PAT = re.compile(r"剧场|游船|码头|演艺|广场")

eng = create_engine(
    "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip",
    connect_args={"connect_timeout": 3},
)
stats = {
    "ordinary_deactivated": 0,
    "venue_entertainment": 0,
    "hotel_recat": 0,
    "service_deactivated": 0,
    "miss": [],
}
with eng.begin() as c:
    for city, name in ordinary:
        r = c.execute(
            text(
                "update pois set status='inactive', updated_at=NOW() "
                "where category='park' and status='active' "
                "and city=:c and name_zh=:n"
            ),
            {"c": city, "n": name},
        )
        if r.rowcount:
            stats["ordinary_deactivated"] += r.rowcount
        else:
            stats["miss"].append(("ordinary", city, name))
    for city, name in venue:
        r = c.execute(
            text(
                "update pois set category='entertainment', status='active', "
                "updated_at=NOW() where category='park' and city=:c and name_zh=:n"
            ),
            {"c": city, "n": name},
        )
        stats["venue_entertainment"] += r.rowcount
        if not r.rowcount:
            stats["miss"].append(("venue", city, name))
    for city, name in noise:
        if HOTEL_PAT.search(name):
            r = c.execute(
                text(
                    "update pois set category='hotel', status='active', "
                    "updated_at=NOW() where category='park' and city=:c and name_zh=:n"
                ),
                {"c": city, "n": name},
            )
            stats["hotel_recat"] += r.rowcount
            if not r.rowcount:
                stats["miss"].append(("noise-hotel", city, name))
        elif VENUE_PAT.search(name):
            r = c.execute(
                text(
                    "update pois set category='entertainment', status='active', "
                    "updated_at=NOW() where category='park' and city=:c and name_zh=:n"
                ),
                {"c": city, "n": name},
            )
            stats["venue_entertainment"] += r.rowcount
            if not r.rowcount:
                stats["miss"].append(("noise-venue", city, name))
        else:
            r = c.execute(
                text(
                    "update pois set status='inactive', updated_at=NOW() "
                    "where category='park' and status='active' "
                    "and city=:c and name_zh=:n"
                ),
                {"c": city, "n": name},
            )
            stats["service_deactivated"] += r.rowcount
            if not r.rowcount:
                stats["miss"].append(("noise-service", city, name))
    after = dict(
        c.execute(
            text("select status, count(*) from pois where category='park' group by 1")
        ).fetchall()
    )
print(stats)
print("park by status:", after)
with io.open(LOG, "a", encoding="utf-8") as f:
    f.write(f"\n## 执行记录（{datetime.now().isoformat(timespec='seconds')}）\n\n")
    f.write(
        f"> 普通公园软删 {stats['ordinary_deactivated']} 行（41 组 active）；"
        f"场馆→entertainment {stats['venue_entertainment']} 行；"
        f"酒店词→hotel 保持 active {stats['hotel_recat']} 行；"
        f"服务行（观光车等）→inactive {stats['service_deactivated']} 行；"
        f"未命中 {len(stats['miss'])}。\n"
    )
    f.write(
        "> 回滚：软删行 `UPDATE pois SET status='active' WHERE category='park' "
        "AND name_zh IN (本档建议删清单) AND status='inactive'`；"
        "服务行同名恢复；hotel/entertainment 行按附A/附B清单改回 category。\n"
    )
    for kind, city, name in stats["miss"]:
        f.write(f"- MISS {kind}｜{city}｜{name}\n")
print("log appended:", LOG)
