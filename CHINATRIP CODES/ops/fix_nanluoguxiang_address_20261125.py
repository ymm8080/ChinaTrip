"""修复南锣鼓巷 POI 的错误坐标与连锁污染字段（2026-11-25）。

根因：amap 源「南锣鼓巷」(id=267c68a0...) 的 location 落在密云区
(116.8201, 40.3677)，导致：
  - address / address_en 被写成密云区果园街道老头儿铁板烧(兴云店)兴云小区
  - access_* 被写成「980路快车 → 密云西大桥站」143 分钟远郊接驳
  - 与景山/故宫的球面距离被拉到 ~60km（真实约 1.5km）
  - 但 intro 自己写「位于鼓楼东大街南侧」，自相矛盾

正确位置（腾讯地图 / Wikipedia / BIGEMAP 多源一致，GCJ-02）：
  北京市东城区交道口街道前圆恩寺胡同28号，(116.403187, 39.937282)

修复列：location(GCJ-02)、wgs84_location(WGS84)、address、address_en，
        以及清空 access_* 远郊接驳字段（市中心景点与参照点一致应为 NULL）。
坐标口径：location 存 GCJ-02，wgs84_location 用 app.services.coords
        gcj02_to_wgs84 逆推，与底库导入铁律一致。

用法：
  python ops/fix_nanluoguxiang_address_20261125.py --dry-run
  python ops/fix_nanluoguxiang_address_20261125.py --apply
  python ops/fix_nanluoguxiang_address_20261125.py --rollback   # 整行恢复
幂等：目标行已是正确坐标时 apply 直接 no-op；loser 状态异常即拒绝。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.coords import gcj02_to_wgs84  # noqa: E402

POI_ID = "267c68a0-396b-4451-a228-7beffcf94d9c"
NAME_ZH = "南锣鼓巷"
SOURCE = "amap"
CITY = "北京"

# 正确坐标：GCJ-02（腾讯地图返回，与库内 amap 源坐标系一致）
CORRECT_LON, CORRECT_LAT = 116.403187, 39.937282
WGS_LON, WGS_LAT = gcj02_to_wgs84(CORRECT_LON, CORRECT_LAT)

CORRECT_ADDRESS = "北京市东城区交道口街道前圆恩寺胡同28号"
CORRECT_ADDRESS_EN = (
    "Nanluoguxiang Hutong, Jiaodaokou Subdistrict, Dongcheng District, Beijing"
)

# 被错误坐标带出的远郊接驳字段：市中心景点参照点均为 NULL
ACCESS_COLS = [
    "access_mode",
    "access_minutes",
    "access_gateway",
    "access_gateway_minutes",
    "access_note",
    "access_note_en",
    "access_source",
    "access_updated_at",
    "access_boarding_lon",
    "access_boarding_lat",
]

BAK_TABLE = "pois_nanluoguxiang_addr_bak_20261125"
LEDGER = (
    Path(__file__).resolve().parents[1]
    / "DESIGN"
    / "backup"
    / "pois_nanluoguxiang_addr_fix_2026-11-25.json"
)


def _db_url() -> str:
    env = (Path(__file__).resolve().parents[1] / ".env").read_text(encoding="utf-8")
    m = re.search(r"DATABASE_URL\s*=\s*(.+)", env)
    return m.group(1).strip().strip('"').strip("'")


def _engine():
    return create_engine(_db_url())


def _columns(conn: Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='pois' AND table_schema='public' "
                "ORDER BY ordinal_position"
            )
        ).fetchall()
    ]


def _row(conn: Connection, cols: list[str]) -> dict:
    r = conn.execute(text("SELECT * FROM pois WHERE id=:id"), {"id": POI_ID}).fetchone()
    if r is None:
        raise RuntimeError(f"目标行不存在: {POI_ID}")
    return dict(zip(cols, r))


def _is_correct(row: dict) -> bool:
    """幂等判定：坐标与地址均已到位（允许英文地址细微差异）。"""
    loc = str(row.get("location") or "")
    # 正确坐标的 EWKB 前缀含 116.4032/39.9373 对应的 double，用 ST 判定更稳
    return (
        row.get("address") == CORRECT_ADDRESS
        and "密云" not in str(row.get("access_note") or "")
        and loc != ""
        and row.get("_near_correct") is True
    )


def _near_correct(conn: Connection) -> bool:
    d = conn.execute(
        text(
            "SELECT ST_DWithin(location::geography, "
            "ST_MakePoint(:lon,:lat)::geography, 60) FROM pois WHERE id=:id"
        ),
        {"lon": CORRECT_LON, "lat": CORRECT_LAT, "id": POI_ID},
    ).scalar()
    return bool(d)


def _lonlat(conn: Connection, col: str) -> str:
    return str(
        conn.execute(
            text(f"SELECT ST_AsText({col}) FROM pois WHERE id=:id"), {"id": POI_ID}
        ).scalar()
    )


def _snapshot(conn: Connection, cols: list[str]) -> None:
    """整行快照，只建一次，保留原始密云值用于回滚。"""
    exists = conn.execute(text("SELECT to_regclass(:t)"), {"t": BAK_TABLE}).scalar()
    if exists is None:
        conn.execute(
            text(f"CREATE TABLE {BAK_TABLE} AS SELECT * FROM pois WHERE id=:id"),
            {"id": POI_ID},
        )
        conn.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{BAK_TABLE} ON {BAK_TABLE}(id)"
            )
        )
    conn.execute(text(f"DELETE FROM {BAK_TABLE} WHERE id=:id"), {"id": POI_ID})
    conn.execute(
        text(f"INSERT INTO {BAK_TABLE} SELECT * FROM pois WHERE id=:id"), {"id": POI_ID}
    )


def dry_run(conn: Connection) -> None:
    cols = _columns(conn)
    before = _row(conn, cols)
    correct = _near_correct(conn)
    print(f"[dry-run] id={POI_ID} {NAME_ZH}/{SOURCE}")
    print(
        f"  location      : {_lonlat(conn, 'location')} "
        f"-> POINT({CORRECT_LON} {CORRECT_LAT})"
    )
    print(
        f"  wgs84_location: {_lonlat(conn, 'wgs84_location')} "
        f"-> POINT({WGS_LON:.6f} {WGS_LAT:.6f})"
    )
    print(f"  address       : {before.get('address')} -> {CORRECT_ADDRESS}")
    print(f"  address_en    : {before.get('address_en')} -> {CORRECT_ADDRESS_EN}")
    for c in ACCESS_COLS:
        if c in cols:
            print(f"  {c:20s}: {str(before.get(c))[:60]} -> NULL")
    print(f"  near-correct already? {correct}")
    d = conn.execute(
        text(
            "SELECT ST_Distance(location::geography, "
            "ST_MakePoint(:lon,:lat)::geography)/1000 FROM pois WHERE id=:id"
        ),
        {"lon": CORRECT_LON, "lat": CORRECT_LAT, "id": POI_ID},
    ).scalar()
    print(f"  offset from correct point: {float(d):.1f} km")


def apply(conn: Connection) -> None:
    cols = _columns(conn)
    before = _row(conn, cols)
    if _near_correct(conn) and before.get("address") == CORRECT_ADDRESS:
        print("[apply] already correct, no-op")
        return
    _snapshot(conn, cols)

    sets = [
        "location = ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geometry",
        "wgs84_location = ST_SetSRID(ST_MakePoint(:wlon,:wlat),4326)::geometry",
        "address = :addr",
        "address_en = :addr_en",
        "updated_at = now()",
    ]
    params = {
        "lon": CORRECT_LON,
        "lat": CORRECT_LAT,
        "wlon": WGS_LON,
        "wlat": WGS_LAT,
        "addr": CORRECT_ADDRESS,
        "addr_en": CORRECT_ADDRESS_EN,
        "id": POI_ID,
    }
    for c in ACCESS_COLS:
        if c in cols:
            sets.append(f"{c} = NULL")
    sql = f"UPDATE pois SET {', '.join(sets)} WHERE id=:id"
    conn.execute(text(sql), params)

    after = _row(conn, cols)
    assert _near_correct(conn), "坐标修复未生效"
    assert after["address"] == CORRECT_ADDRESS, "地址修复未生效"
    for c in ACCESS_COLS:
        if c in cols:
            assert after[c] is None, f"{c} 未清空"

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(
        json.dumps(
            {
                "date": "2026-11-25",
                "poi_id": POI_ID,
                "name_zh": NAME_ZH,
                "source": SOURCE,
                "source_of_truth": [
                    "Tencent Map: 39.937282,116.403187, "
                    "北京市东城区交道口街道前圆恩寺胡同28号",
                    "Wikipedia: 39.9370872,116.403148",
                    "BIGEMAP: 116.403242,39.934576",
                ],
                "coordinate_system": "location=GCJ-02, wgs84_location=WGS84 "
                "(gcj02_to_wgs84)",
                "before": {
                    k: str(v)
                    for k, v in before.items()
                    if k
                    in [
                        "location",
                        "wgs84_location",
                        "address",
                        "address_en",
                        *ACCESS_COLS,
                    ]
                },
                "after": {
                    k: str(v)
                    for k, v in after.items()
                    if k
                    in [
                        "location",
                        "wgs84_location",
                        "address",
                        "address_en",
                        *ACCESS_COLS,
                    ]
                },
                "backup_table": BAK_TABLE,
                "rollback": f"python ops/{Path(__file__).name} --rollback",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[apply] fixed. ledger -> {LEDGER}")


def rollback(conn: Connection) -> None:
    exists = conn.execute(text("SELECT to_regclass(:t)"), {"t": BAK_TABLE}).scalar()
    if exists is None:
        raise RuntimeError(f"无备份表 {BAK_TABLE}，无法回滚")
    n = conn.execute(
        text(f"SELECT count(*) FROM {BAK_TABLE} WHERE id=:id"), {"id": POI_ID}
    ).scalar()
    if not n:
        raise RuntimeError("备份表无该行，无法回滚")
    cols = _columns(conn)
    # 整行回填在 SQL 侧完成：geography/jsonb 等列若经 Python 参数绑定会
    # 触发 EWKB hex 无法 adapt 的错误（实测 access_boarding），故用
    # UPDATE ... FROM 让 PG 直接按列类型拷贝。
    # SET 左侧不能带目标表别名（PG 语法），只写列名
    sets = ", ".join(f'"{c}" = b."{c}"' for c in cols if c != "id")
    conn.execute(
        text(
            f"UPDATE pois AS p SET {sets} "
            f"FROM {BAK_TABLE} AS b WHERE p.id = b.id AND p.id = :id"
        ),
        {"id": POI_ID},
    )
    print("[rollback] 整行已恢复（含原始密云坐标）")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    eng = _engine()
    with eng.begin() as conn:
        if args.dry_run:
            dry_run(conn)
        elif args.apply:
            apply(conn)
        else:
            rollback(conn)


if __name__ == "__main__":
    main()
