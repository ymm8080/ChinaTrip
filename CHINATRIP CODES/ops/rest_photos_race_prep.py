"""One-shot prep for the 00:00 amap pool race (2026-11-14).

Cooldown is source-blind: the free-source grind (Commons/og) stamped every
active photo-less restaurant row today, which would block the fresh amap
pool from ever reaching the rows that matter. For race night only, clear
photos_fetched_at on active photo-less rows whose name_zh contains CJK
chars — the only rows amap v5 place/around can name-match. English/pinyin
rows are left stamped (around cannot match them; saving pool calls).

Idempotent, bounded, prints the cleared row count for the ledger.
"""

import psycopg

DB = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"


def main() -> int:
    conn = psycopg.connect(DB)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE restaurants
        SET photos_fetched_at = NULL
        WHERE status = 'active'
          AND photos IS NULL
          AND name_zh IS NOT NULL
          AND name_zh <> ''
          AND name_zh ~ '[一-龥]'
          AND photos_fetched_at IS NOT NULL
        """
    )
    print("race prep cleared cooldown stamps:", cur.rowcount)
    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
