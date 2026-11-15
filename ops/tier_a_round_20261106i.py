# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run I）"""
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
        ('大运河南旺枢纽国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经汶上县政府wenshang.gov.cn/济宁市文旅局（检索词：大运河南旺枢纽国家考古遗址公园 官网 汶上）2026-11-06')),
        ('汉魏洛阳故城国家考古遗址公园', dict(
            web='www.hanweimuseum.cn（汉魏洛阳故城遗址博物馆官网·2025开馆）；suitangluoyang.com（洛阳汉魏隋唐都城遗址保护中心）',
            status='verified', src='检索核验 2026-11-06')),
        ('熊家冢国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网（楚王车马阵景区）；官方信息经湖北省文旅厅wlt.hubei.gov.cn/荆州市文旅（检索词：熊家冢国家考古遗址公园 官网 荆州 楚王车马阵）2026-11-06')),
        ('长沙铜官窑国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网（铜官窑博物馆亦无）；资讯经望城区文旅；勿与新华联铜官窑古镇（商业运营）混淆（检索词：长沙铜官窑国家考古遗址公园 官网 铜官窑博物馆）2026-11-06')),
    ],
    '04': [
        ('双龙风景名胜区', dict(
            web='www.shuanglongdong.com（双龙洞官网·含订票页）',
            status='verified', src='复用02已核(金华市双龙风景旅游区·同名匹配+同省浙江) 2026-11-06')),
        ('仙都风景名胜区', dict(
            web='www.zgxdly.cn（仙都景区官网）',
            status='verified', src='复用02已核(丽水市缙云仙都景区·同名匹配+同省浙江) 2026-11-06')),
        ('江郎山风景名胜区', dict(
            web='www.jlsnbd.com（江郎山廿八都官网）',
            status='verified', src='复用02已核(衢州市江郎山·廿八都旅游区·江郎山段匹配+同省浙江) 2026-11-06')),
        ('仙居风景名胜区', dict(
            web='www.zjshenxianju.com（神仙居官网·含预订页）',
            status='verified', src='复用02已核(台州市神仙居景区·仙居风景名胜区核心景区+同省浙江) 2026-11-06')),
        ('浣江-五泄风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA；信息经诸暨市文旅（检索词：五泄风景名胜区 官网 诸暨 门票）2026-11-06')),
        ('方岩风景名胜区', dict(
            web='www.ykfangyan.com（永康市方岩风景区投资经营有限公司官网·含扫码购票）',
            status='verified', src='检索核验 2026-11-06')),
        ('百丈漈-飞云湖风景名胜区', dict(
            status='na',
            src='未找到独立官网；公众号候选名「文成旅游」未确认；信息经文成县政府wencheng.gov.cn（检索词：百丈漈飞云湖风景名胜区 官网 文成）2026-11-06')),
        ('方山-长屿硐天风景名胜区', dict(
            web='www.changyudongtian.com（长屿硐天官网·方山段电话0576-86330237购票）',
            status='verified', src='检索核验 2026-11-06')),
    ],
    '15': [
        ('西北农耕博物馆', dict(
            web='xbngbwg.com（西北农耕博物馆官网·固原）',
            status='verified', src='检索核验 2026-11-06')),
        ('银川世界岩画馆', dict(
            status='na',
            src='无独立官网/公众号确认；位于贺兰口岩画景区内，公众号候选名「贺兰山岩画」未确认（检索词：银川世界岩画馆 官网 公众号 贺兰山岩画）2026-11-06')),
    ],
    '16': [
        ('东阳市博物馆', dict(
            status='na',
            src='无独立官网；自有微信公众号存在（活动报名经凤凰网报道佐证）但认证名未获点名（检索词：东阳市博物馆 官网 公众号 预约）2026-11-06')),
        ('君匋艺术院', dict(
            status='na',
            src='未找到独立官网/公众号；信息经桐乡本地官方渠道（检索词：君匋艺术院 桐乡 官网 公众号）2026-11-06')),
    ],
    '17': [
        ('新疆生产建设兵团军垦博物馆', dict(
            status='na',
            src='无独立官网；公众号候选名「新疆兵团军垦博物馆」未获源文点名；介绍经文旅部mct.gov.cn/国家民委neac.gov.cn（检索词：新疆生产建设兵团军垦博物馆 官网 公众号 石河子）2026-11-06')),
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
        ta['next'] = '03剩余15/04剩余174/18完成 + 博物馆525candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runI(tier_a): 03 v1/na3; 04 复用4+检索2v/na2(浙江段复用持续收割); 博物馆 v1/na4'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
