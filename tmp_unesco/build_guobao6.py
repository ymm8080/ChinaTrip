# -*- coding: utf-8 -*-
"""第六批全国重点文物保护单位（1,080 处）解析 + 审阅包 + 导入档（§3.2 #4，2026-11-03）。

源：gov.cn 国务院公报 国发〔2006〕19号 全文（content_346203.htm），内嵌五列名单
（序号/编号/名称/时代/地址）。粘连行（时代+地址无空格）用「省名定位切地址 +
尾部时代词剥离」解析。校验：序号 1..1080 连续、六类计数 = 220/77/513/63/206/1。

输出：
  DESIGN/POIS DATASOURCE/19_第六批全国重点文物保护单位_1080.csv（审阅包）
  CHINATRIP CODES/data/guobao6.csv（导入档，供 ops/import_guobao6_2026-11-03.py）
"""

from __future__ import annotations

import csv
import html as H
import io
import json
import re
from pathlib import Path

BASE = Path(r'D:\CHINATRIP\tmp_unesco')
OUT_REVIEW = Path(r'D:\CHINATRIP\DESIGN\POIS DATASOURCE\19_第六批全国重点文物保护单位_1080.csv')
OUT_IMPORT = Path(r'D:\CHINATRIP\CHINATRIP CODES\data\guobao6.csv')

PROVS = ['北京市', '天津市', '河北省', '山西省', '内蒙古自治区', '辽宁省', '吉林省',
         '黑龙江省', '上海市', '江苏省', '浙江省', '安徽省', '福建省', '江西省',
         '山东省', '河南省', '湖北省', '湖南省', '广东省', '广西壮族自治区', '海南省',
         '重庆市', '四川省', '贵州省', '云南省', '西藏自治区', '陕西省', '甘肃省',
         '青海省', '宁夏回族自治区', '新疆维吾尔自治区']
PROV_RE = re.compile('(' + '|'.join(sorted(map(re.escape, PROVS), key=len, reverse=True)) + ')')

ERA = ('(新石器至青铜时代|旧石器至新石器时代|新石器时代至商周|新石器时代至战国|'
       '旧石器时代|新石器时代|青铜时代|铁器时代|新石器时代|'
       '夏商周|西周|东周|春秋|战国|西汉|东汉|三国|南北朝|隋唐|五代|北宋|南宋|西夏|'
       '民国|近现代|中华人民共和国|'
       '商周|秦汉|唐宋|元明|明清|[至到][夏商周秦汉晋隋唐宋辽金元明清]|'
       '夏|商|周|秦|汉|晋|隋|唐|宋|辽|金|元|明|清|待定|不详)')
ERA_TAIL = re.compile(r'\s*' + ERA + r'$')

CAT_RE = re.compile(r'^[一二三四五六七八九十]+、(.+?)（(?:共|共计)(\d+)处）$')
ROW_RE = re.compile(r'^(\d+)\s+(Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ|Ⅶ|Ⅷ|Ⅸ|Ⅹ)[－-](\d+)\s+(.+)$')
EXPECT_CATS = {'古遗址': 220, '古墓葬': 77, '古建筑': 513,
               '石窟寺及石刻': 63, '近现代重要史迹及代表性建筑': 206, '其他': 1}


def main() -> int:
    raw = (BASE / 'gb_b6.html').read_text(encoding='utf-8')
    m = re.search(r'<div[^>]*class="[^"]*pages_content[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>', raw)
    body = m.group(1) if m else raw
    body = re.sub(r'<script[\s\S]*?</script>', ' ', body)
    text = H.unescape(re.sub(r'<[^>]+>', '\n', body))
    lines = [re.sub(r'[\u3000\s]+', ' ', l.replace('\xa0', ' ')).strip() for l in text.split('\n')]
    lines = [l for l in lines if l]

    start = next(i for i, l in enumerate(lines) if '共计1080处' in l)
    rows, cat, i = [], None, start + 1
    CODE_RE = re.compile(r'^(Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ|Ⅶ|Ⅷ|Ⅸ|Ⅹ)[－-](\d+)$')
    while i < len(lines):
        l = lines[i]
        i += 1
        mc = CAT_RE.match(l)
        if mc:
            cat = mc.group(1)
            continue
        if l.startswith('与现有全国重点文物保护单位合并'):
            break
        # 竖排格式：序号 / 编号 / 名称 / 时代 / 地址 各占一行
        if l.isdigit() and i < len(lines) and CODE_RE.match(lines[i]):
            seq = int(l)
            code = CODE_RE.match(lines[i]).group(0)
            i += 1
            parts = []
            while i < len(lines) and len(parts) < 3:
                parts.append(lines[i]); i += 1
            name = parts[0] if parts else ''
            address = parts[-1] if len(parts) >= 2 else ''
            rows.append({'seq': seq, 'code': code.replace('－', '-'), 'name': name,
                         'era': '', 'address': address, 'category': cat})
            continue
        mr = ROW_RE.match(l)
        if not mr:
            continue
        seq, roman, num, rest = int(mr.group(1)), mr.group(2), mr.group(3), mr.group(4)
        matches = list(PROV_RE.finditer(rest))
        mp = matches[-1] if matches else None  # 名称可能以省名开头（山西省立第三中学旧址），取最后匹配
        if not mp:
            rows.append({'seq': seq, 'code': f'{roman}-{num}', 'name': rest.strip(),
                         'era': '', 'address': '', 'category': cat})
            continue
        middle, addr = rest[:mp.start()].strip(), rest[mp.start():].strip()
        name = middle
        for _ in range(2):  # 时代可能两段（如 宋至元）
            m2 = ERA_TAIL.search(name)
            if not m2:
                break
            era = m2.group(1)
            name = name[:m2.start()].strip()
            if 'era' not in rows[-1] if rows else True:
                pass
        rows.append({'seq': seq, 'code': f'{roman}-{num}', 'name': name,
                     'era': '', 'address': addr, 'category': cat})

    # 校验
    seqs = {r['seq'] for r in rows}
    gaps = [i for i in range(1, 1081) if i not in seqs]
    from collections import Counter
    got = Counter(r['category'] for r in rows)
    bad = {c: (EXPECT_CATS[c], got.get(c, 0)) for c in EXPECT_CATS if EXPECT_CATS[c] != got.get(c, 0)}
    print(f'parsed={len(rows)} seq_gaps={len(gaps)} {gaps[:10]}')
    print('cat check:', 'OK' if not bad else bad)
    print('sample glued fix:', [r for r in rows if r['seq'] in (29, 33)][:2])

    with io.open(OUT_REVIEW, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['name_zh', 'province', 'address', 'category', 'code', 'seq'])
        w.writeheader()
        for r in rows:
            mp = PROV_RE.match(r['address'] or '')
            w.writerow({'name_zh': r['name'], 'province': mp.group(1) if mp else '',
                        'address': r['address'], 'category': r['category'],
                        'code': r['code'], 'seq': r['seq']})
    with io.open(OUT_IMPORT, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['name_zh', 'province', 'address', 'code', 'category', 'seq'])
        for r in rows:
            mp = PROV_RE.match(r['address'] or '')
            w.writerow([r['name'], mp.group(1) if mp else '', r['address'],
                        r['code'], r['category'], r['seq']])
    print('review pack:', OUT_REVIEW)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
