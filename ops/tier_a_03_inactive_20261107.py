# -*- coding: utf-8 -*-
"""2026-11-07 用户决定:
①03考古遗址公园65行→inactive, 除非special(世遗名录组成+国民级IP共17行保留原状)
②16文件7行复用直升verified撤回inactive(复用结论不作数)"""
import csv, json, os, time
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'DESIGN', 'POIS DATASOURCE')
LOCK = os.path.join(ROOT, 'ops', 'ops_fill.lock')
TODAY = '2026-11-07'

SPECIAL_03 = {
    '周口店国家考古遗址公园', '殷墟国家考古遗址公园', '良渚国家考古遗址公园',
    '集安高句丽国家考古遗址公园', '汉魏洛阳故城国家考古遗址公园', '隋唐洛阳城国家考古遗址公园',
    '汉长安城未央宫国家考古遗址公园', '西夏陵国家考古遗址公园', '大明宫国家考古遗址公园',
    '三星堆国家考古遗址公园', '金沙国家考古遗址公园', '圆明园国家考古遗址公园',
    '秦始皇陵国家考古遗址公园', '二里头国家考古遗址公园', '汉代海昏侯国国家考古遗址公园',
    '御窑厂国家考古遗址公园', '乾陵国家考古遗址公园',
}
REVERT_16 = {
    '新疆喀什地区博物馆', '大庆石油科技馆', '连城县博物馆', '桂林甑皮岩遗址博物馆',
    '澧县城头山古文化遗址博物馆', '桂林市靖江王陵博物馆', '钓鱼城古战场遗址博物馆',
}


def detect_fmt(path):
    with open(path, 'rb') as f:
        raw = f.read(4096)
    return ('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'), ('\r\n' if b'\r\n' in raw else '\n')


def acquire_lock(timeout=90):
    t0 = time.time()
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(LOCK) > 90:
                    os.remove(LOCK)
                    continue
            except OSError:
                pass
            if time.time() - t0 > timeout:
                raise TimeoutError('ops_fill.lock 等待超时 90s')
            time.sleep(1)


def main():
    acquire_lock()
    try:
        # ① 03 文件
        p03 = os.path.join(BASE, '03_国家考古遗址公园_65.csv')
        enc, nl = detect_fmt(p03)
        with open(p03, encoding=enc, newline='') as f:
            rows = list(csv.reader(f))
        n_inact = kept = 0
        for r in rows[1:]:
            if len(r) <= 8:
                continue
            if r[1] in SPECIAL_03:
                kept += 1
                continue
            if r[7] != 'inactive':
                r[7] = 'inactive'
                r[8] = '[inactive' + TODAY + ' 用户决定:非special置inactive;原状态与证据如下] ' + (r[8] or '')
                n_inact += 1
        with open(p03, 'w', encoding=enc, newline='') as f:
            w = csv.writer(f, lineterminator=nl)
            for r in rows:
                w.writerow(r[:14] + [''] * max(0, 14 - len(r)))

        # ② 16 文件撤回 7 行
        p16 = os.path.join(BASE, '16_国家三级博物馆_批次补全.csv')
        enc2, nl2 = detect_fmt(p16)
        with open(p16, encoding=enc2, newline='') as f:
            rows16 = list(csv.reader(f))
        n_rev = 0
        for r in rows16[1:]:
            if len(r) > 11 and r[0] in REVERT_16 and r[10] == 'verified':
                r[10] = 'inactive'
                r[11] = '[inactive' + TODAY + ' 用户决定:复用直升结论不作数;原证据如下] ' + (r[11] or '')
                n_rev += 1
        with open(p16, 'w', encoding=enc2, newline='') as f:
            w = csv.writer(f, lineterminator=nl2)
            for r in rows16:
                w.writerow(r[:17] + [''] * max(0, 17 - len(r)))

        # ③ 进度更新
        pj = os.path.join(ROOT, 'ops', 'official_channel_progress.json')
        prog = json.load(open(pj, encoding='utf-8'))
        ta = prog.setdefault('tier_a', {})
        dm = ta.setdefault('done', {})
        for fname, key, cols in (('03_国家考古遗址公园_65.csv', '03', (7,)),
                                 ('16_国家三级博物馆_批次补全.csv', '16', (10,))):
            pp = os.path.join(BASE, fname)
            e, _ = detect_fmt(pp)
            with open(pp, encoding=e, newline='') as f:
                rr = list(csv.reader(f))
            vc = cols[0]
            c = collections.Counter(r[vc] for r in rr[1:] if len(r) > vc)
            dm[key] = '{n}行 ' + ' '.join('%s=%d' % (k, v) for k, v in sorted(c.items()))
        ta['user_decision'] = (TODAY + ' 用户决定:①03考古遗址公园65行置inactive,除非special——保留17行'
                               '(世遗名录组成9:周口店/殷墟/良渚/集安高句丽/汉魏洛阳故城/隋唐洛阳城/汉长安城未央宫/西夏陵/大明宫'
                               '+国民级IP8:三星堆/金沙/圆明园/秦始皇陵/二里头/海昏侯/御窑厂/乾陵);'
                               '②16文件7行复用直升verified撤回inactive(复用结论不作数)')
        ta['next'] = '04×110行to_verify + 16×26行保留candidate'
        prog['last_run'] = TODAY + ' runT(user): 03非special 48行→inactive(17行special保留);16文件7行复用verified撤回inactive'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('03 inactive set:', n_inact, '| special kept:', kept)
        print('16 reverted:', n_rev)
        for key in ('03', '16'):
            print(key, dm[key])
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
