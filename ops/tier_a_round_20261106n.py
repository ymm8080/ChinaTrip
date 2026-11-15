# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run N）"""
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
        ('九龙漈风景名胜区', dict(
            status='na',
            src='未找到独立官网（鲤鱼溪·九龙漈旅游区）；预订经OTA；信息经周宁县文旅（检索词：九龙漈风景名胜区 官网 周宁 门票）2026-11-06')),
        ('庐山风景名胜区', dict(
            web='www.lushanlvyou.com（庐山旅游官网）',
            status='verified',
            src='复用02/08已核(九江市庐山风景名胜区+世遗庐山国家公园·三证同域+同省江西) 2026-11-06')),
        ('井冈山风景名胜区', dict(
            web='jgstour.com（井冈山旅游网·含订票入口）',
            status='verified', src='复用02已核(吉安市井冈山风景旅游区·同名匹配+同省江西) 2026-11-06')),
        ('三清山风景名胜区', dict(
            web='www.sqsfjq.com（三清山官网·含预约购票专页）',
            status='verified',
            src='复用02/08已核(上饶市三清山风景名胜区+世遗三清山国家公园·双证同域+同省江西) 2026-11-06')),
        ('龙虎山风景名胜区', dict(
            web='longhushan.com.cn（龙虎山唯一官方信息平台·可购票）',
            status='verified', src='复用02已核(鹰潭市龙虎山风景名胜区·同名匹配+同省江西) 2026-11-06')),
        ('仙女湖风景名胜区', dict(
            status='na',
            src='未找到独立官网；公众号候选名「仙女湖旅游」未确认；预订经OTA（检索词：仙女湖风景名胜区 官网 新余 门票）2026-11-06')),
        ('三百山风景名胜区', dict(
            web='www.sbsjq.com（三百山官网）',
            status='verified', src='复用02已核(赣州市三百山景区·同名匹配+同省江西) 2026-11-06')),
        ('梅岭-滕王阁风景名胜区', dict(
            web='www.cntwg.com（滕王阁官网·含购票平台/buy.html）',
            status='verified',
            src='复用02已核(南昌市滕王阁旅游区·滕王阁段覆盖+同省江西；梅岭段经南昌湾里属地渠道) 2026-11-06')),
    ],
    '15': [
        ('黔东南州民族博物馆', dict(
            web='www.qdnzmb.com（黔东南州民族博物馆官网）',
            social='公众号「黔东南州民族博物馆」（服务-线上预约）',
            status='verified', src='检索核验 2026-11-06')),
        ('遵义市博物馆（贵州酒文化博物馆）', dict(
            web='www.zysbwg.cn（遵义市博物馆官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('青海柳湾彩陶博物馆', dict(
            status='na',
            src='无独立官网（0972-8615520）；信息经乐都区/海东市文旅（检索词：青海柳湾彩陶博物馆 官网 公众号 乐都）2026-11-06')),
        ('青海省自然资源博物馆', dict(
            web='www.qhdzzl.org.cn（青海省自然资源博物馆官网·含数字博物馆）',
            social='公众号「青海省自然资源博物馆」（参观预约）',
            status='verified', src='检索核验 2026-11-06')),
        ('西宁市湟中区博物馆', dict(
            status='na',
            src='无独立官网/公众号；信息经湟中区政府huangzhong.gov.cn（检索词：西宁市湟中区博物馆 官网 公众号）2026-11-06')),
    ],
    '16': [
        ('滕州市汉画像石馆', dict(
            web='www.tzhhxsg.com（滕州市汉画像石馆官网·含参观预约）',
            social='公众号「滕州市汉画像石馆」（实名预约）',
            status='verified', src='检索核验(国家一级博物馆) 2026-11-06')),
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
        ta['next'] = '03/17/18完成/04剩余134/01预填 + 博物馆500candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runN(tier_a): 04 复用6(江西段富矿:庐山/井冈山/三清山/龙虎山/三百山/滕王阁)+na2; 博物馆 v4/na2'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
