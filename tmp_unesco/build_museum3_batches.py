# -*- coding: utf-8 -*-
"""museum3 三级博物馆补全（§路线图 P3）：定级第三批 86 + 第四批 225 +
第七次运行评估（2022-2024）三级 414，按名去重后出审阅包+导入档。

去重：括号前主名归一（剥括号）；主名相同视为同馆，保留定级批次行（batch 更权威），
七次评估行仅在主名未出现时收录。括号内容入 alias_zh。
city=省短名（museum2 既有约定）。
输出：
  DESIGN/POIS DATASOURCE/16_国家三级博物馆_批次补全.csv（审阅包）
  CHINATRIP CODES/data/museum3_batches.csv（导入档）
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

BASE = Path(r'D:\CHINATRIP\tmp_unesco')
OUT_REVIEW = Path(r'D:\CHINATRIP\DESIGN\POIS DATASOURCE\16_国家三级博物馆_批次补全.csv')
OUT_IMPORT = Path(r'D:\CHINATRIP\CHINATRIP CODES\data\museum3_batches.csv')

CMA = 'https://www.chinamuseum.org.cn/cma/detailss.html?id=19&contentId='
SRC = {'第三批': CMA + '9091', '第四批': CMA + '9002',
       '第七次运行评估(2022-2024)': CMA + '14558'}

PROV_SHORT = {
    '北京市': '北京', '天津市': '天津', '河北省': '河北', '山西省': '山西',
    '内蒙古自治区': '内蒙古', '辽宁省': '辽宁', '吉林省': '吉林', '黑龙江省': '黑龙江',
    '上海市': '上海', '江苏省': '江苏', '浙江省': '浙江', '安徽省': '安徽',
    '福建省': '福建', '江西省': '江西', '山东省': '山东', '河南省': '河南',
    '湖北省': '湖北', '湖南省': '湖南', '广东省': '广东', '广西壮族自治区': '广西',
    '海南省': '海南', '重庆市': '重庆', '四川省': '四川', '贵州省': '贵州',
    '云南省': '云南', '西藏自治区': '西藏', '陕西省': '陕西', '甘肃省': '甘肃',
    '青海省': '青海', '宁夏回族自治区': '宁夏', '新疆维吾尔自治区': '新疆',
    '新疆生产建设兵团': '新疆',
}
PAREN = re.compile(r'^(.*?)\s*[（(]([^（）()]+)[)）]\s*$')


def main_key(name: str) -> str:
    m = PAREN.match(name)
    return (m.group(1) if m else name).strip()


def main() -> int:
    batches = json.load(open(BASE / 'batch_rows.json', encoding='utf-8'))
    eval7 = json.load(open(BASE / 'eval7_rows.json', encoding='utf-8'))

    # 跨级升级排除：三级批次行若同名出现在更高等级名单（四批一级/二批二级/七次二级），不导入
    higher = set()
    for lst in ('b4_m1', 'b3_m2', 'b4_m2'):
        for row in batches.get(lst, []):
            higher.add(main_key(row[1]))
    for row in eval7['m2']:
        higher.add(main_key(row[1]))
    print('higher-grade names:', len(higher))

    pool = []
    for row in batches['b3_m3']:
        pool.append((row[1], row[2], '第三批'))
    for row in batches['b4_m3']:
        pool.append((row[1], row[2], '第四批'))
    for row in eval7['m3']:
        pool.append((row[1], row[2], '第七次运行评估(2022-2024)'))

    seen, rows = set(), []
    for name, prov, batch in pool:
        key = main_key(name)
        if key in seen or key in higher:
            continue
        seen.add(key)
        alias = ''
        m = PAREN.match(name)
        if m and m.group(2) not in ('博物馆', '展览馆', '陈列馆'):
            alias = m.group(2)
        rows.append({'name_zh': name, 'province': prov,
                     'city': PROV_SHORT.get(prov, prov), 'grade': '国家三级博物馆',
                     'batch': batch, 'alias_zh': alias, 'source_url': SRC.get(batch, '')})

    with io.open(OUT_REVIEW, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with io.open(OUT_IMPORT, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['name_zh', 'province', 'city', 'grade', 'batch', 'alias_zh', 'source_url'])
        for r in rows:
            w.writerow([r['name_zh'], r['province'], r['city'], r['grade'],
                        r['batch'], r['alias_zh'], r['source_url']])

    from collections import Counter
    print('review pack:', OUT_REVIEW, 'rows:', len(rows))
    print('by batch:', Counter(r['batch'] for r in rows))
    print('by province:', Counter(r['city'] for r in rows).most_common(8))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
