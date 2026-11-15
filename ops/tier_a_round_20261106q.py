# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run Q）"""
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
        ('鸡公山风景名胜区', dict(
            web='www.kikungshan.com（鸡公山官网）',
            status='verified', src='复用02已核(信阳市鸡公山景区·同名匹配+同省河南) 2026-11-06')),
        ('洛阳龙门风景名胜区', dict(
            web='www.lmsk.cn（龙门石窟官网）',
            status='verified',
            src='复用02/08已核(洛阳市龙门石窟景区+世遗龙门石窟·双证同域+同省河南) 2026-11-06')),
        ('嵩山风景名胜区', dict(
            web='www.shaolin.org.cn（少林寺官网）',
            status='verified',
            src='复用02已核(郑州市嵩山少林景区·少林寺段覆盖+同省河南；中岳嵩山含嵩阳/中岳庙等段) 2026-11-06')),
        ('王屋山-云台山风景名胜区', dict(
            web='www.yuntaishan.net（焦作云台山旅游发展有限公司官网）',
            status='verified',
            src='复用02已核(焦作市云台山-神农山-青天河风景区·云台山段覆盖+同省河南；王屋山段经济源属地渠道) 2026-11-06')),
        ('石人山风景名胜区', dict(
            web='www.tianruily.com（天瑞旅游·尧山中原大佛官网）',
            status='verified',
            src='复用02已核(平顶山市尧山-中原大佛景区·石人山即尧山今名+同省河南) 2026-11-06')),
        ('林虑山风景名胜区', dict(
            web='www.thdxg.net（太行大峡谷官网·林州，林虑山段核心景区）',
            status='verified',
            src='复用runC已核证据(太行大峡谷风景名胜区河北行消歧时确认河南林州侧官网thdxg.net；林虑山即林州太行大峡谷所在) 2026-11-06')),
        ('青天河风景名胜区', dict(
            web='www.yuntaishan.net（焦作云台山旅游发展有限公司官网）',
            status='verified', src='复用02已核(焦作市云台山-神农山-青天河风景区·青天河段覆盖+同省河南) 2026-11-06')),
        ('桐柏山-淮源风景名胜区', dict(
            web='tongbaishan.weijingtong.net（桐柏山景区官方票务·微景通平台，微信扫码购票）',
            status='verified',
            src='检索核验(无独立域名官网；官方票务系统经检索确认为景区官网票务入口) 2026-11-06')),
    ],
    '16': [
        ('京山县博物馆', dict(
            status='na',
            src='无独立官网；公众号候选名未确认（免费，公众号预约）；信息经京山市/荆门文旅渠道（检索词：京山县博物馆 官网 公众号）2026-11-06')),
        ('天门市博物馆', dict(
            social='小程序「游湖北」（省级官方预约平台·天门市政府网口径）',
            status='verified',
            src='检索核验(预约渠道经天门市政府网tianmen.gov.cn公告佐证；无独立官网) 2026-11-06')),
        ('罗田县博物馆', dict(
            status='na',
            src='无独立官网/公众号（2025-06新馆启用·栗香文化小镇）；信息经罗田县政府/黄冈智慧文旅hgswly.cn（检索词：罗田县博物馆 官网 公众号）2026-11-06')),
        ('麻城市革命博物馆', dict(
            status='na',
            src='无独立官网；公众号候选名未确认（0713-2912827）；信息经湖北日报网/黄冈智慧文旅（检索词：麻城市革命博物馆 官网 公众号）2026-11-06')),
        ('慈利县博物馆', dict(
            status='na',
            src='无独立官网/公众号确认（2023-06重新开馆）；信息经慈利县政府cili.gov.cn（检索词：慈利县博物馆 官网 公众号）2026-11-06')),
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
        ta['next'] = '03/15/17/18完成/04剩余110/01预填 + 博物馆485candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runQ(tier_a): 04 河南8连verified(复用6+林虑山跨轮复用+桐柏山官方票务); 博物馆 v1/na4'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
