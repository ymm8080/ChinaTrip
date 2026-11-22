"""人工定值：把某个 POI 的 rating 写成指定值，并打 rating_source='manual'。

用法（先 dry-run 再落库）：
    python ops/set_poi_rating.py 北京 慕田峪长城 4.9 --dry-run
    python ops/set_poi_rating.py 北京 慕田峪长城 4.9 --note "用户拍板"

为什么必须落 rating_source：本仓回源链的写入口径是
app/jobs/enrich_ctrip_detail（`Poi.rating is None` 才写、或 rating_source
=='amap' 才覆盖）与 app/jobs/refresh_pois（图商回值才写）。打 manual 后
两条链都不再动这行评分——人工定值优先于回源，且可审计。
"""

from __future__ import annotations

import argparse
import sys

import psycopg2

DSN = dict(host="localhost", dbname="chinatrip", user="chinatrip", password="chinatrip")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("name", help="精确名（name_zh）；不存在时报错不猜")
    ap.add_argument("rating", type=float)
    ap.add_argument("--source", default="manual", help="溯源标记，默认 manual")
    ap.add_argument("--note", default="", help="变更说明（写日志用）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not 0 <= args.rating <= 5:
        print(f"rating 越界：{args.rating}", file=sys.stderr)
        return 2

    conn = psycopg2.connect(**DSN)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source, name_zh, rating, rating_source, ta_rating
                FROM pois
                WHERE city = %s AND name_zh = %s AND status = 'active'
                ORDER BY source
                """,
                (args.city, args.name),
            )
            rows = cur.fetchall()
            if not rows:
                print(f"未找到 active 行：{args.city} / {args.name}", file=sys.stderr)
                return 1

            print(f"命中 {len(rows)} 行：")
            for rid, src, nm, rating, rsrc, ta in rows:
                print(
                    f"  {str(rid)[:8]} source={src:<12} {nm} "
                    f"rating={rating} (source={rsrc}) ta_rating={ta}"
                )

            if args.dry_run:
                print(
                    f"\n[dry-run] 将把以上 {len(rows)} 行 rating -> {args.rating}，"
                    f"rating_source -> {args.source}。未落库。"
                )
                return 0

            cur.execute(
                """
                UPDATE pois
                SET rating = %s, rating_source = %s, updated_at = NOW()
                WHERE city = %s AND name_zh = %s AND status = 'active'
                """,
                (args.rating, args.source, args.city, args.name),
            )
            print(f"\n已更新 {cur.rowcount} 行。")

        with conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT source, name_zh, rating, rating_source
                FROM pois
                WHERE city = %s AND name_zh = %s AND status = 'active'
                ORDER BY source
                """,
                (args.city, args.name),
            )
            print("落库后：")
            for src, nm, rating, rsrc in cur.fetchall():
                print(f"  source={src:<12} {nm} rating={rating} source={rsrc}")
        if args.note:
            print(f"\n说明：{args.note}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
