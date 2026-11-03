# -*- coding: utf-8 -*-
"""CMA 定级批次名单 PDF 解析（第三/四批，pypdf 文本层）。

第四批（9002_5/9002_6，2020）：带省头「省（N 家）」的表格式，行内表头需按
「段尾悬空序号」规则归属；第三批（9091_3/9091_5，2017）：每行「seq 名 省」扁平式。
输出 tmp_unesco/batch_rows.json，并按省头计数/序号连续性校验。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

PROVS = ['北京市', '天津市', '河北省', '山西省', '内蒙古自治区', '辽宁省', '吉林省',
         '黑龙江省', '上海市', '江苏省', '浙江省', '安徽省', '福建省', '江西省',
         '山东省', '河南省', '湖北省', '湖南省', '广东省', '广西壮族自治区', '海南省',
         '重庆市', '四川省', '贵州省', '云南省', '西藏自治区', '陕西省', '甘肃省',
         '青海省', '宁夏回族自治区', '新疆维吾尔自治区', '新疆生产建设兵团']
PROV_ALT = '|'.join(sorted(map(re.escape, PROVS), key=len, reverse=True))
HDR = re.compile(r'(' + PROV_ALT + r')\s*（\s*(\d+)\s*家\s*）')

BASE = Path(r'D:\CHINATRIP\tmp_unesco')


def read_pages(path: Path) -> str:
    r = PdfReader(str(path))
    return '\n'.join((p.extract_text() or '') for p in r.pages)


def parse_with_headers(path: Path):
    text = read_pages(path).replace('\u00a0', ' ')
    parts, expected = [], {}
    pos = 0
    for m in HDR.finditer(text):
        inline = m.start() > 0 and text[m.start() - 1] not in '\n\r'
        parts.append([text[pos:m.start()], None, [], inline, False])
        parts.append([None, m.group(1), [], False, False])
        expected[m.group(1)] = expected.get(m.group(1), 0) + int(m.group(2))
        pos = m.end()
    parts.append([text[pos:], None, [], False, False])
    prov, pending_seq = None, None
    for part in parts:
        seg, newprov = part[0], part[1]
        if newprov:
            prov = newprov
            continue
        for ln in seg.split('\n'):
            s = ln.strip()
            if not s or s.startswith('附件') or ('序号' in s and '省份' in s):
                continue
            m = re.match(r'^(\d+)\s*(.*)$', s)
            if m:
                seq, rest = int(m.group(1)), m.group(2).strip()
                if rest:
                    part[2].append([seq, rest, prov])
                    pending_seq = None
                else:
                    pending_seq = seq
            else:
                part[2].append([pending_seq, s, prov])
                pending_seq = None
        part[4] = pending_seq is not None
    for idx, part in enumerate(parts):
        if part[2] and part[3] and not part[4]:
            part[2][-1][2] = parts[idx + 1][1]
    return [r for p in parts for r in p[2]], expected


def parse_flat(path: Path):
    text = read_pages(path)
    rows = []
    for ln in text.split('\n'):
        s = ln.strip()
        if not s or (s.startswith('第') and '批' in s):
            continue
        m = re.match(r'^(\d+)\s+(.+?)\s+(' + PROV_ALT + r')$', s)
        if m:
            rows.append([int(m.group(1)), m.group(2).strip(), m.group(3)])
    return rows, {}


def report(path: Path, label: str, mode: str):
    rows, exp = parse_with_headers(path) if mode == 'hdr' else parse_flat(path)
    got = Counter(r[2] for r in rows if r[2])
    bad = {p: (exp[p], got.get(p, 0)) for p in exp if exp[p] != got.get(p, 0)}
    seqs = {r[0] for r in rows if r[0]}
    gaps = [i for i in range(1, max(seqs) + 1) if i not in seqs] if seqs else []
    print('== %s: parsed=%d expected=%s bad=%s gaps=%s'
          % (label, len(rows), sum(exp.values()) or '-', bad or 'none', gaps[:8]))
    return rows


if __name__ == '__main__':
    out = {
        'b4_m3': report(BASE / 'cma_pdfs' / '9002_6.pdf', '第四批三级', 'hdr'),
        'b4_m2': report(BASE / 'cma_pdfs' / '9002_5.pdf', '第四批二级', 'hdr'),
        'b3_m3': report(BASE / 'cma_pdfs' / '9091_5.pdf', '第三批三级', 'flat'),
        'b3_m2': report(BASE / 'cma_pdfs' / '9091_3.pdf', '第三批二级', 'flat'),
    }
    json.dump(out, open(BASE / 'batch_rows.json', 'w', encoding='utf-8'),
              ensure_ascii=False)
    for k, rows in out.items():
        print(k, 'n=%d' % len(rows), 'first:', rows[:2], 'last:', rows[-1:])
