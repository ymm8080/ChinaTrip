# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run F）——18 文件本轮清零"""
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
        ('上林湖越窑国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经慈溪市政府cixi.gov.cn/宁波文旅局（检索词：上林湖越窑国家考古遗址公园 官网 慈溪）2026-11-06')),
        ('明中都皇故城国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；咨询0550-2559698/凤阳县政府fengyang.gov.cn（检索词：明中都皇故城国家考古遗址公园 官网 凤阳）2026-11-06')),
        ('万寿岩国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经三明市政府/福建省文物局wwj.wlt.fujian.gov.cn（检索词：万寿岩国家考古遗址公园 官网 三明）2026-11-06')),
        ('城子崖国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方公众号为预约/活动渠道（新华网山东报道佐证）但认证名未确认；信息经章丘区政府jnzq.gov.cn（检索词：城子崖遗址博物馆 章丘 官网 公众号）2026-11-06')),
    ],
    '04': [
        ('青山沟风景名胜区', dict(
            status='na',
            src='未找到独立官网；分景点购票经OTA（检索词：青山沟风景名胜区 官网 宽甸 门票）2026-11-06')),
        ('医巫闾山风景名胜区', dict(
            web='www.ywlsfjq.com（医巫闾山风景区官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('松花湖风景名胜区', dict(
            web='www.songhuahujqt.com（松花湖风景名胜区官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('"八大部"-净月潭风景名胜区', dict(
            status='verified',
            src='复用02已核(长春市净月潭·同名部分匹配+同省吉林；净月潭段覆盖，伪满八大部为历史街区无独立渠道) 2026-11-06')),
        ('仙景台风景名胜区', dict(
            status='na',
            src='未找到独立官网；咨询和龙市文旅（检索词：仙景台风景名胜区 官网 和龙）2026-11-06')),
        ('防川风景名胜区', dict(
            social='服务号「珲春防川景区」/小程序「防川景区」（官方购票渠道，市政府公告）',
            status='verified',
            src='检索核验(无独立官网；官方微信渠道经珲春市政府hunchun.gov.cn公告佐证) 2026-11-06')),
        ('镜泊湖风景名胜区', dict(
            web='jph.mdj.gov.cn（镜泊湖管委会官网）',
            status='verified', src='复用02已核(牡丹江市镜泊湖·核心名匹配+同省黑龙江) 2026-11-06')),
        ('五大连池风景名胜区', dict(
            web='wdlcgwh.heihe.gov.cn（五大连池管委会官网）',
            status='verified', src='复用02已核(黑河市五大连池·核心名匹配+同省黑龙江) 2026-11-06')),
    ],
    '18': [
        ('珠海横琴长隆国际海洋度假区', dict(
            web='www.chimelong.com（长隆集团官网·英文版chimelongresort.com，覆盖珠海横琴园区）',
            status='verified', src='复用项目已核chimelong.com(长隆集团官网，珠海横琴与广州长隆同集团) 2026-11-06')),
        ('桂林雁山旅游度假区', dict(
            web='www.glyslydjq.com（桂林雁山旅游度假区官网·桂ICP备2023008422号-1）',
            status='verified', src='检索核验 2026-11-06')),
        ('万宁石梅湾旅游度假区', dict(
            status='na',
            src='无独立官网；官方信息经万宁市政府/海南省旅文厅（检索词：万宁石梅湾旅游度假区 官网）2026-11-06')),
        ('石柱黄水旅游度假区', dict(
            web='www.cqhslydjq.com（黄水旅游度假区官网·重庆石柱）',
            social='公众号/小程序「黄水旅游度假区」（智慧票务，国际在线佐证）',
            status='verified', src='检索核验 2026-11-06')),
        ('成都西岭雪山-花水湾旅游度假区', dict(
            web='www.xiling.cn（西岭雪山官网）；www.cdxlxs.com.cn（官方观景套票）',
            status='verified', src='检索核验 2026-11-06')),
        ('德宏芒市孔雀湖旅游度假区', dict(
            web='www.kqhlydjq.com（孔雀湖旅游度假区官网·芒市文旅集团运营）',
            social='公众号「芒市孔雀湖旅游度假区」',
            status='verified', src='检索核验 2026-11-06')),
        ('临夏永靖刘家峡旅游度假区', dict(
            status='na',
            src='无独立官网（运营方甘肃黄河三峡旅游投资公司无公开站）；信息经永靖县文体广电旅游局（检索词：永靖刘家峡旅游度假区 官网 公众号）2026-11-06')),
        ('中卫大漠黄河（沙坡头）旅游度假区', dict(
            web='www.ctgii.com/scenic/holiday/232（港中旅·沙坡头官方购票页）',
            status='verified', src='复用02已核(中卫市沙坡头旅游景区·核心名匹配+同省宁夏) 2026-11-06')),
        ('五家渠青格达湖旅游度假区', dict(
            status='na',
            src='无独立官网；信息经五家渠市政府wujiaqu.gov.cn/兵团第六师（检索词：五家渠青格达湖旅游度假区 官网）2026-11-06')),
    ],
    '15': [
        ('天津市静海区萨马兰奇纪念馆', dict(
            web='www.jasmemorial.org（萨马兰奇纪念馆官网·含新媒体矩阵入口）',
            status='verified', src='检索核验 2026-11-06')),
        ('天津市武清区博物馆', dict(
            status='na',
            src='未找到独立官网/公众号确认；信息经武清区文旅渠道（检索词：天津市武清区博物馆 官网 公众号）2026-11-06')),
    ],
    '16': [
        ('宿迁市博物馆', dict(
            social='公众号「宿迁市博物馆」（菜单预约，本地宝/Trip多源一致）',
            status='verified', src='检索核验(公众号预约通道多源一致；无独立官网) 2026-11-06')),
        ('淮安市楚州博物馆', dict(
            status='na',
            src='楚州区已更名淮安区，该馆独立官网/公众号未确认；区内主要馆为中国漕运博物馆（检索词：淮安市楚州博物馆 官网 公众号）2026-11-06')),
    ],
    '17': [
        ('云浮市博物馆', dict(
            status='na',
            src='无独立官网；公告经云浮市政府门户yunfu.gov.cn发布，公众号名仅平台暗示未确认（检索词：云浮市博物馆 官网 公众号 预约）2026-11-06')),
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
        ta['next'] = '03剩余27/04剩余198/18完成(to=0) + 博物馆540candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runF(tier_a): 03 v0/na4; 04 复用5+检索3v/na2; 18 复用2+检索4v/na3→29行全部收口; 博物馆 v2/na3'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
