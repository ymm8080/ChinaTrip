# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run G）"""
import csv, json, os, time
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'DESIGN', 'POIS DATASOURCE')
LOCK = os.path.join(ROOT, 'ops', 'ops_fill.lock')
TODAY = '2026-11-06'

FILES = {
    '03': ('03_国家考古遗址公园_65.csv', 1, 4, 6, 7, 8, 'to_verify'),
    '04': ('04_国家级风景名胜区_244.csv', 3, 5, 7, 8, 9, 'to_verify'),
    '15': ('15_国家二级博物馆_七省补缺.csv', 2, 7, 9, 10, 11, 'candidate'),
    '16': ('16_国家三级博物馆_批次补全.csv', 0, 7, 9, 10, 11, 'candidate'),
    '17': ('17_国家二级博物馆_七次评估补缺_9.csv', 0, 7, 9, 10, 11, 'candidate'),
}

UPDATES = {
    '03': [
        ('吉州窑国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经吉安县政府/中国吉州窑博物馆（检索词：吉州窑国家考古遗址公园 官网 吉安）2026-11-06')),
        ('郑韩故城国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经新郑市政府/郑州市文物局（检索词：郑韩故城国家考古遗址公园 官网 新郑）2026-11-06')),
        ('盘龙城国家考古遗址公园', dict(
            web='www.plcsmuseum.com.cn（盘龙城遗址博物院官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('城头山国家考古遗址公园', dict(
            web='www.chcts.net（澧县城头山官网）',
            status='verified', src='检索核验 2026-11-06')),
    ],
    '04': [
        ('太阳岛风景名胜区', dict(
            status='verified', src='复用02已核(哈尔滨市太阳岛景区·核心名匹配+同省黑龙江；02核验时无域名记录) 2026-11-06')),
        ('大沾河风景名胜区', dict(
            status='na',
            src='未找到独立官网；官方信息经黑河市政府/黑龙江省林草局（检索词：大沾河风景名胜区 官网 黑龙江）2026-11-06')),
        ('太湖风景名胜区', dict(
            status='na',
            src='跨苏州无锡两市分段管理无统一官网；分段渠道：苏州太湖度假区政务服务网wzthlydjq.jszwfw.gov.cn、无锡鼋头渚www.ytz.com.cn等（检索词：太湖风景名胜区 管委会 官网 江苏）2026-11-06')),
        ('南京钟山风景名胜区', dict(
            web='zschina.nanjing.gov.cn（中山陵园管理局官网）',
            status='verified', src='复用02已核(南京市钟山风景名胜区-中山陵园·同名全匹配+同省江苏) 2026-11-06')),
        ('云台山风景名胜区', dict(
            web='yts.lyg.gov.cn（连云港市云台山风景名胜区管委会官网）',
            status='verified',
            src='检索核验(江苏连云港云台山；河南焦作云台山yuntaishan.net为同名不同景区勿混) 2026-11-06')),
        ('蜀岗瘦西湖风景名胜区', dict(
            web='wap.shouxihu.net（瘦西湖官方票务）',
            status='verified', src='复用02已核(扬州市瘦西湖风景区·同名匹配+同省江苏) 2026-11-06')),
        ('三山风景名胜区', dict(
            status='verified',
            src='复用02已核(镇江市金山·焦山·北固山风景区·三山即此三者+同省江苏；02核验时无域名记录) 2026-11-06')),
        ('杭州西湖风景名胜区', dict(
            status='verified', src='复用02已核(杭州市杭州西湖风景区+08西湖文化景观·同名匹配+同省浙江) 2026-11-06')),
    ],
    '15': [
        ('元明清天妃宫遗址博物馆', dict(
            web='www.whycbhzx.com（官网·与天津市文化遗产保护中心合署）',
            social='公众号「天津市文化遗产保护中心」（实名预约）',
            status='verified', src='检索核验 2026-11-06')),
        ('隆德博物馆', dict(
            status='na',
            src='未找到独立官网/公众号；信息经隆德县政府longde.gov.cn（检索词：隆德博物馆 官网 公众号 宁夏）2026-11-06')),
    ],
    '16': [
        ('新四军江南指挥部纪念馆', dict(
            status='na',
            src='未找到独立官网；公众号候选名未获佐证；介绍经溧阳市政府liyang.gov.cn（检索词：新四军江南指挥部纪念馆 官网 公众号 溧阳）2026-11-06')),
        ('景宁畲族自治县畲族博物馆', dict(
            status='na',
            src='无独立官网；公众号候选名「中国畲族博物馆」未获独立佐证；信息经景宁县政府jingning.gov.cn（检索词：景宁畲族自治县畲族博物馆 官网 公众号）2026-11-06')),
    ],
    '17': [
        ('四川宋瓷博物馆（遂宁市博物馆）', dict(
            social='公众号「四川宋瓷博物馆」（免费参观预约）',
            status='verified',
            src='检索核验(公众号预约通道明确+遂宁市政府公告佐证；无独立官网) 2026-11-06')),
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
        ta['next'] = '03剩余23/04剩余190/18完成 + 博物馆535candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runG(tier_a): 03 v2/na2; 04 复用5+检索1v/na2(云台山已与焦作消歧、太湖分段管理标na); 博物馆 v2/na3'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
