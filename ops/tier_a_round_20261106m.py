# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run M）"""
import csv, json, os, time
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'DESIGN', 'POIS DATASOURCE')
LOCK = os.path.join(ROOT, 'ops', 'ops_fill.lock')
TODAY = '2026-11-06'

FILES = {
    '04': ('04_国家级风景名胜区_244.csv', 3, 5, 7, 8, 9, 'to_verify'),
    '15': ('15_国家二级博物馆_七省补缺.csv', 2, 7, 9, 10, 11, 'candidate'),
    '16': ('16_国家三级博物馆_批次补全.csv', 0, 7, 9, 10, 11, 'candidate'),
}

UPDATES = {
    '04': [
        ('玉华洞风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA；信息经将乐县政府jiangle.gov.cn（检索词：玉华洞风景名胜区 官网 将乐 门票）2026-11-06')),
        ('十八重溪风景名胜区', dict(
            status='na',
            src='未找到独立官网；信息经闽侯县政府minhou.gov.cn（检索词：十八重溪风景名胜区 官网 闽侯）2026-11-06')),
        ('青云山风景名胜区', dict(
            status='na',
            src='未找到独立官网；票价经福州市物价局fgw.fuzhou.gov.cn文件（联票98元/三日）（检索词：青云山风景名胜区 官网 永泰 门票）2026-11-06')),
        ('佛子山风景名胜区', dict(
            status='na',
            src='未找到独立官网；信息经政和县政府/南平市文旅（检索词：佛子山风景名胜区 官网 政和）2026-11-06')),
        ('宝山风景名胜区', dict(
            web='www.baoshandasheng.com（顺昌宝山旅游景区官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('福安白云山风景名胜区', dict(
            status='na',
            src='未找到独立官网（0593-6891335）；与广州/洛阳白云山为不同景区（检索词：福安白云山风景名胜区 官网 门票）2026-11-06')),
        ('灵通山风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA；信息经平和县文旅（检索词：灵通山风景名胜区 官网 平和 门票）2026-11-06')),
        ('湄洲岛风景名胜区', dict(
            web='www.ptzmld.com（湄洲岛轮渡官网·在线购船票+门票）',
            status='verified', src='复用02已核(莆田市湄洲岛妈祖文化旅游区·同名匹配+同省福建) 2026-11-06')),
    ],
    '15': [
        ('西藏牦牛博物馆', dict(
            social='公众号「西藏牦牛博物馆」（实名预约；与西藏博物馆tibetmuseum.com.cn为不同场馆）',
            status='verified',
            src='检索核验(公众号为官方预约渠道，名称功能明确；无独立官网) 2026-11-06')),
        ('毕节市博物馆', dict(
            web='www.bjmuseum.net（毕节市博物馆官网）',
            social='公众号「毕节市博物馆」+数字虚拟博物馆',
            status='verified', src='检索核验(经毕节市政府门户bijie.gov.cn点名) 2026-11-06')),
        ('贵州三线建设博物馆（六盘水市博物馆）', dict(
            status='na',
            src='无独立官网；信息经钟山区/六盘水市政府gzlps.gov.cn；勿与都匀三线建设博物馆混淆（检索词：贵州三线建设博物馆 六盘水 官网 公众号）2026-11-06')),
    ],
    '16': [
        ('新干县博物馆', dict(
            web='www.xinganbwg.cn（新干县博物馆官网·青铜文化主题）',
            status='verified', src='检索核验 2026-11-06')),
        ('东平县博物馆', dict(
            status='na',
            src='无独立官网/线上预约系统（免费直接参观）；信息经东平县文旅（检索词：东平县博物馆 官网 公众号 预约）2026-11-06')),
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
        ta['next'] = '03/17/18完成/04剩余142/01预填 + 博物馆506candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runM(tier_a): 04 复用1(湄洲岛)+检索1v(宝山)/na6(福建中小段普遍无官网); 博物馆 v3/na2'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
