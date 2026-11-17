# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run O）"""
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
        ('龟峰风景名胜区', dict(
            status='verified',
            src='复用02已核(上饶市龟峰景区·同名匹配+同省江西；弋阳龟峰与湖北麻城龟峰山为不同景区) 2026-11-06')),
        ('高岭-瑶里风景名胜区', dict(
            status='na',
            src='未找到独立官网；官方信息经景德镇市政府jdz.gov.cn/浮梁县政府fuliang.gov.cn（检索词：高岭瑶里风景名胜区 官网 景德镇 门票）2026-11-06')),
        ('武功山风景名胜区', dict(
            web='www.wugongshan.cn（萍乡武功山官网·含购票专页）',
            status='verified',
            src='复用02已核(萍乡市武功山景区·5A段覆盖+同省江西；山体跨萍乡/宜春/吉安) 2026-11-06')),
        ('云居山-柘林湖风景名胜区', dict(
            web='www.lushanlvyou.com（庐山旅游官网·柘林湖即庐山西海景区）',
            status='verified', src='复用02已核(九江市庐山西海景区·同水体匹配+同省江西) 2026-11-06')),
        ('灵山风景名胜区', dict(
            web='www.jxsrlingshan.com（上饶灵山风景名胜区管委会官网·赣ICP备05000726号-1，含预定门票）',
            status='verified', src='检索核验(定向搜索确认域名) 2026-11-06')),
        ('神农源风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA；信息经万年县文旅（检索词：神农源风景名胜区 官网 万年 门票）2026-11-06')),
        ('大茅山风景名胜区', dict(
            status='na',
            src='未找到独立官网（0793-7818128）；信息经德兴市文旅（检索词：大茅山风景名胜区 官网 德兴）2026-11-06')),
        ('瑞金风景名胜区', dict(
            status='na',
            src='未找到独立官网（共和国摇篮景区5A亦无独立站）；信息经瑞金市文广新旅局（检索词：瑞金风景名胜区 官网 共和国摇篮）2026-11-06')),
    ],
    '16': [
        ('淄博市陶瓷博物馆', dict(
            social='公众号+支付宝小程序「淄博陶瓷琉璃博物馆预约门票」（实名预约系统117.50.187.4:61085）',
            status='verified',
            src='检索核验(现名淄博陶瓷琉璃博物馆；官方预约渠道经馆方声明确认) 2026-11-06')),
        ('濮阳市博物馆', dict(
            status='na',
            src='无独立官网；官方微信公众号存在（发布活动/预约）但认证名未在检索结果中点名；信息经濮阳市政府puyang.gov.cn（检索词：濮阳市博物馆 官网 公众号）2026-11-06')),
        ('周口华威民俗文化博物苑', dict(
            web='www.huaweibowuyuan.com（周口华威民俗文化博物苑官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('济源市博物馆', dict(
            web='www.jysmuseum.cn（济源市博物馆官网·含全景参观）',
            social='公众号「济源市博物馆」（实名预约）',
            status='verified', src='检索核验 2026-11-06')),
        ('新安县博物馆', dict(
            web='www.xaxbwg.cn（新安县博物馆官网）',
            status='verified', src='检索核验 2026-11-06')),
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
        ta['next'] = '03/15/17/18完成/04剩余126/01预填 + 博物馆495candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runO(tier_a): 04 复用3(龟峰/武功山/西海)+检索1v(灵山jxsrlingshan.com定向确认)/na4; 博物馆 v4/na1'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
