# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run P）"""
import csv, json, os, time
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'DESIGN', 'POIS DATASOURCE')
LOCK = os.path.join(ROOT, 'ops', 'ops_fill.lock')
TODAY = '2026-11-06'

FILES = {
    '04': ('04_国家级风景名胜区_244.csv', 3, 5, 7, 8, 9, 'to_verify'),
    '16': ('16_国家三级博物馆_批次补全.csv', 0, 7, 9, 10, 11, 'candidate'),
}

UPDATES = {
    '04': [
        ('小武当风景名胜区', dict(
            status='na',
            src='现名南武当山景区，未找到独立官网；官方信息经赣州市政府ganzhou.gov.cn；与湖北武当山wudangshan.com为不同景区（检索词：小武当山风景名胜区 官网 龙南 门票）2026-11-06')),
        ('杨岐山风景名胜区', dict(
            web='www.jxyqs.com（杨岐山官网）',
            status='verified', src='检索核验(含孽龙洞；另有中文域名官网) 2026-11-06')),
        ('汉仙岩风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA（官网挂牌价见百科）；信息经会昌县文旅（检索词：汉仙岩风景名胜区 官网 会昌 门票）2026-11-06')),
        ('青岛崂山风景名胜区', dict(
            web='qdlaoshan.cn（崂山微官网）',
            status='verified', src='复用02已核(青岛市崂山景区·同名匹配+同省山东) 2026-11-06')),
        ('胶东半岛海滨风景名胜区', dict(
            web='plg.com.cn（蓬莱阁官网·含智游蓬莱商城）',
            status='verified',
            src='复用02已核(烟台市蓬莱阁-三仙山-八仙过海旅游区·蓬莱阁段覆盖+同省山东；海滨段经烟台/威海属地渠道) 2026-11-06')),
        ('博山风景名胜区', dict(
            status='na',
            src='组群式风景区（原山/鲁山/樵岭前等）分段售票无统一官网；信息经淄博市文旅（检索词：博山风景名胜区 官网 淄博 门票）2026-11-06')),
        ('青州风景名胜区', dict(
            social='公众号「青州云门山景区」（实名预约购票·核心段云门山/驼山）',
            status='verified',
            src='检索核验(青州风景名胜区核心段官方公众号预约购票；与青州古城5A为不同主体) 2026-11-06')),
        ('千佛山风景名胜区', dict(
            web='www.jngygp.cn（济南市公园景区门票官网·公园发展服务中心主办，千佛山官方购票）',
            status='verified', src='检索核验 2026-11-06')),
    ],
    '16': [
        ('方城县博物馆', dict(
            status='na',
            src='未找到独立官网/公众号；信息经方城县文广旅局（检索词：方城县博物馆 官网 公众号）2026-11-06')),
        ('新县许世友将军纪念馆', dict(
            status='na',
            src='未找到独立官网/公众号（许世友将军故里景区组成部分）；信息经新县政府xinxi.gov.cn（检索词：新县许世友将军纪念馆 官网 公众号）2026-11-06')),
        ('淮滨县淮河博物馆', dict(
            status='na',
            src='无独立官网；公众号名未确认（0376-7796670）；信息经河南省文旅部门hnswszy.org.cn（检索词：淮滨县淮河博物馆 官网 公众号）2026-11-06')),
        ('洛阳隋唐大运河博物馆', dict(
            social='公众号「隋唐大运河文化博物馆」（官方指定散客预约·提前3天实名；兼约万里茶道博物馆）',
            status='verified',
            src='检索核验(现名隋唐大运河文化博物馆；馆方声明未授权第三方售票) 2026-11-06')),
        ('浠水县博物馆', dict(
            status='na',
            src='无独立官网；公众号存在迹象但认证名未确认（依托浠水文庙古建筑群，0713-4232721）（检索词：浠水县博物馆 官网 公众号）2026-11-06')),
    ],
}


def detect_fmt(path):
    with open(path, 'rb') as f:
        raw = f.read(4096)
    return ('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'), ('\r\n' if b'\r\n' in raw else '\n')


def apply_group(key):
    fname, nc, wc, sc, vc, rc, guard = FILES[key]
    path = os.path.join(BASE, fname)
    enc, nl = detect_fmt(path)
    with open(path, encoding=enc, newline='') as f:
        rows = list(csv.reader(f))
    ncols = len(rows[0])
    applied, skipped = [], []
    for name, upd in UPDATES[key]:
        hit = False
        for r in rows[1:]:
            if len(r) > max(nc, vc, rc) and r[nc] == name:
                hit = True
                if r[vc] != guard:
                    skipped.append((name, 'status=' + r[vc]))
                    break
                if 'web' in upd:
                    r[wc] = upd['web']
                if 'social' in upd:
                    r[sc] = upd['social']
                r[vc] = upd['status']
                r[rc] = upd['src']
                applied.append((name, upd['status']))
                break
        if not hit:
            skipped.append((name, 'ROW NOT FOUND'))
    with open(path, 'w', encoding=enc, newline='') as f:
        w = csv.writer(f, lineterminator=nl)
        for r in rows:
            w.writerow(r[:ncols] + [''] * max(0, ncols - len(r)))
    return applied, skipped


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
        report = {}
        for key in UPDATES:
            applied, skipped = apply_group(key)
            report[key] = dict(applied=applied, skipped=skipped)
        pj = os.path.join(ROOT, 'ops', 'official_channel_progress.json')
        prog = json.load(open(pj, encoding='utf-8'))
        ta = prog.setdefault('tier_a', {})
        done_map = ta.setdefault('done', {})
        for key in FILES:
            fname, nc, wc, sc, vc, rc, _ = FILES[key]
            path = os.path.join(BASE, fname)
            enc, _ = detect_fmt(path)
            with open(path, encoding=enc, newline='') as f:
                rows = list(csv.reader(f))
            c = collections.Counter(r[vc] for r in rows[1:] if len(r) > vc)
            done_map[key] = '{n}行(v={v}/na={na}/to={to}/cand={cd})'.format(
                n=len(rows) - 1, v=c.get('verified', 0), na=c.get('na', 0),
                to=c.get('to_verify', 0), cd=c.get('candidate', 0))
        ta['next'] = '03/15/17/18完成/04剩余118/01预填 + 博物馆490candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runP(tier_a): 04 复用2(崂山/蓬莱阁)+检索3v(杨岐山/青州公众号/千佛山jngygp.cn)/na3; 博物馆 v1/na4'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
