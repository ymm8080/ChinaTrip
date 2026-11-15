# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run D）"""
import csv, json, os, time
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'DESIGN', 'POIS DATASOURCE')
LOCK = os.path.join(ROOT, 'ops', 'ops_fill.lock')
TODAY = '2026-11-06'

FILES = {
    '03': ('03_国家考古遗址公园_65.csv', 1, 4, 6, 7, 8, 'to_verify'),
    '04': ('04_国家级风景名胜区_244.csv', 3, 5, 7, 8, 9, 'to_verify'),
    '18': ('18_国家级旅游度假区_已核29.csv', 0, 5, 7, 8, 9, 'to_verify'),
    '15': ('15_国家二级博物馆_七省补缺.csv', 2, 7, 9, 10, 11, 'candidate'),
    '16': ('16_国家三级博物馆_批次补全.csv', 0, 7, 9, 10, 11, 'candidate'),
    '17': ('17_国家二级博物馆_七次评估补缺_9.csv', 0, 7, 9, 10, 11, 'candidate'),
}

UPDATES = {
    '03': [
        ('龙湾国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经湖北省文旅厅wlt.hubei.gov.cn/潜江龙湾遗址博物院0728-3509118（检索词：龙湾国家考古遗址公园 官网 湖北）2026-11-06')),
        ('炭河里国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经宁乡市政府ningxiang.gov.cn/炭河里青铜博物馆（检索词：炭河里国家考古遗址公园 官网 宁乡）2026-11-06')),
        ('靖江王府及王陵国家考古遗址公园', dict(
            web='www.guilinjjwl.cn（靖江王陵考古遗址公园官网）',
            social='公众号「靖江王陵国家考古遗址公园」',
            status='verified', src='检索核验 2026-11-06')),
        ('邛窑国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经邛崃市政府qionglai.gov.cn/邛窑遗址博物馆（检索词：邛窑国家考古遗址公园 官网 邛崃）2026-11-06')),
    ],
    '04': [
        ('五老峰风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA（检索词：五老峰风景名胜区 官网 永济 门票）2026-11-06')),
        ('碛口风景名胜区', dict(
            status='na',
            src='未找到独立官网；信息经山西文旅网/临县政府（检索词：碛口风景名胜区 官网 临县 古镇）2026-11-06')),
        ('扎兰屯风景名胜区', dict(
            status='na',
            src='未找到独立官网；信息经扎兰屯市政府（检索词：扎兰屯风景名胜区 官网 吊桥公园）2026-11-06')),
        ('额尔古纳风景名胜区', dict(
            status='na',
            src='未找到独立官网；咨询0470-6998222/额尔古纳市政府（检索词：额尔古纳风景名胜区 官网 湿地）2026-11-06')),
        ('鞍山千山风景名胜区', dict(
            status='na',
            src='未找到独立官网；票价公告经鞍山市政府anshan.gov.cn（检索词：千山风景名胜区 官网 鞍山 门票）2026-11-06')),
        ('鸭绿江风景名胜区', dict(
            status='na',
            src='开放式区域无统一官网；信息经辽宁省文旅厅whly.ln.gov.cn，断桥/游船分景点购票（检索词：鸭绿江风景名胜区 官网 丹东 门票）2026-11-06')),
    ],
    '18': [
        ('苏州吴江东太湖生态旅游度假区', dict(
            status='na',
            src='无独立官网；官方信息经吴江区政府wujiang.gov.cn（管理办公室），公众号候选名「东太湖度假区」未获佐证（检索词：吴江东太湖生态旅游度假区 官网）2026-11-06')),
        ('湖州吴兴西塞山旅游度假区', dict(
            web='www.xsslvyou.com（西塞山旅游度假区官网）',
            social='公众号「西塞山旅游」/小程序「一码游西塞山」',
            status='verified', src='检索核验 2026-11-06')),
        ('黄山黟县国际乡村旅游度假区', dict(
            status='na',
            src='无独立官网；官方信息经黟县政府yixian.gov.cn/文旅部公告mct.gov.cn（检索词：黟县国际乡村旅游度假区 官网）2026-11-06')),
        ('南昌梅岭生态旅游度假区', dict(
            status='na',
            src='无独立官网；官方信息经南昌市湾里管理局，公众号候选名「梅岭旅游」未获佐证（检索词：梅岭生态旅游度假区 官网 南昌湾里）2026-11-06')),
    ],
    '15': [
        ('延边博物馆', dict(
            web='www.ybbwg.org.cn（延边博物馆官网·延边州文旅局）',
            status='verified', src='检索核验 2026-11-06')),
        ('长春市文庙博物馆', dict(
            social='公众号「长春市文庙博物馆孔子文化园」（活动发布+参观预约）',
            status='verified', src='检索核验(公众号多源一致；无独立官网) 2026-11-06')),
    ],
    '16': [
        ('大庆油田有限责任公司大庆石油科技馆', dict(
            social='公众号「大庆石油科技馆」（免费预约参观）',
            status='verified', src='检索核验(公众号预约通道多源一致；无独立官网) 2026-11-06')),
        ('同江市赫哲族博物馆', dict(
            status='na',
            src='未找到独立官网/公众号；信息经同江文旅/市文体广电旅游局（检索词：同江市赫哲族博物馆 官网 公众号）2026-11-06')),
    ],
    '17': [
        ('安徽徽州历史博物馆（歙县博物馆）', dict(
            web='www.ahhzlsbwg.com（安徽徽州历史博物馆官网）',
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
        ta['next'] = '03剩余35/04剩余211/18剩余13 + 博物馆550candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runD(tier_a): 03 v1/na3; 04 v0/na6(晋蒙辽段普遍无独立官网); 18 v1/na3; 博物馆 v4/na1'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
