# -*- coding: utf-8 -*-
"""第六批全国重点文物保护单位入库（§3.2 #4，2026-11-03）。

数据：tmp_unesco/build_guobao6.py 产出 data/guobao6.csv（1080 行，六类计数已校验）。
流程：①差集「只补不重」——全库同名行（任意 source）跳过；②§4 正闸过滤
（革命/战争类，excluded 落档）；③city=resolve_city(None, address)（同 07 批惯例）；
④seed_upsert source='guobao6'，source_poi_id='guobao6_<code>'（编号全局稳定）。
幂等：重跑 exists 短路。

用法：
    .venv\\Scripts\\python.exe ops\\import_guobao6_2026-11-03.py            # dry-run
    .venv\\Scripts\\python.exe ops\\import_guobao6_2026-11-03.py --apply
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db import get_session_factory  # noqa: E402
from app.models import Poi  # noqa: E402
from app.services.poi_seed import seed_upsert  # noqa: E402
from app.services.product_filter import apply_product_filter, write_excluded_csv  # noqa: E402

CSV_PATH = Path(__file__).resolve().parents[1] / 'data' / 'guobao6.csv'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)

    rows = list(csv.DictReader(CSV_PATH.open(encoding='utf-8-sig', newline='')))
    factory = get_session_factory()
    with factory() as session:
        existing = {r[0].strip() for r in session.execute(text(
            "select name_zh from pois where status='active'"))}
    print(f'csv rows={len(rows)} existing active names={len(existing)}')

    deduped = [r for r in rows if r['name_zh'].strip() not in existing]
    print(f'after 只补不重 diff: {len(deduped)} (skip {len(rows) - len(deduped)})')

    kept, excluded = apply_product_filter(
        [{'name_zh': r['name_zh'], 'address': r['address'], 'code': r['code'],
          'category': r['category'], 'province': r['province']} for r in deduped],
        name_key='name_zh')
    write_excluded_csv(
        str(CSV_PATH.with_name('guobao6_excluded.csv')), excluded,
        fields=('name_zh', 'province', 'address', 'category', 'exclusion_reason'))
    print(f'§4 excluded: {len(excluded)} | to import: {len(kept)}')

    from app.services.poi_city import resolve_city
    # 历史地名映射（2006 公报用旧称，resolve_city 注册表为现名）
    HIST = {'湖北省襄樊市': '襄阳', '甘肃省安西县': '酒泉', '辽宁省北宁市': '锦州',
            '江西省赣县': '赣州', '云南省孟连傣族': '普洱', '江西省星子县': '九江'}
    resolved, miss = [], []
    for r in kept:
        city = resolve_city(None, r['address'])
        if not city:
            for k, v in HIST.items():
                if r['address'].startswith(k):
                    city = v
                    break
        if city:
            resolved.append((r, city))
        else:
            miss.append((r['name_zh'], r['address']))
    print(f'city resolved {len(resolved)}/{len(kept)} | miss {len(miss)}')
    for m in miss[:10]:
        print('   miss:', m)

    if not args.apply:
        print('dry-run only (use --apply)')
        return 0

    stats = {'created': 0, 'exists': 0, 'skipped': 0}
    for r, city in resolved:
        out = seed_upsert(
            factory, Poi,
            source='guobao6',
            source_poi_id=f"guobao6_{r['code']}",
            city=city,
            name_zh=r['name_zh'],
            category='历史遗迹',
            tags=['guobao6'],
            tags_source='datasource_csv',
            origin='cn_sync',
        )
        stats[out] = stats.get(out, 0) + 1
    print('import stats:', stats)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
