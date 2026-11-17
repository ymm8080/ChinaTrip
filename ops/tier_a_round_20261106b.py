# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run B）
含 run A 误记修正：野三坡行 web 由误猜的中文域名改为管委会官网 hbysp.cn。
"""
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
# files: (name, name_col, web_col, social_col, status_col, src_col, guard)

UPDATES = {
    '03': [
        ('辽上京国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网/公众号；官方信息经赤峰市文旅局wlj.chifeng.gov.cn/巴林左旗政府·辽上京博物馆（检索词：辽上京国家考古遗址公园 官网 博物馆）2026-11-06')),
        ('安吉古城国家考古遗址公园', dict(
            web='www.ajgcpark.com（安吉古城国家考古遗址公园官网·含遗址博物馆）',
            status='verified', src='检索核验 2026-11-06')),
        ('城村汉城国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经福建闽越王城博物馆/福建省文物局wwj.wlt.fujian.gov.cn（检索词：城村汉城国家考古遗址公园 官网 武夷山 闽越王城）2026-11-06')),
        ('汉代海昏侯国国家考古遗址公园', dict(
            web='www.hhhmuseum.cn（南昌汉代海昏侯国遗址博物馆官网）；www.hhh.gov.cn（遗址管理局）',
            status='verified', src='检索核验 2026-11-06')),
    ],
    '04': [
        ('野三坡风景名胜区', dict(
            web='www.hbysp.cn（野三坡景区管委会官网·涞水县）',
            status='verified',
            src='检索核验(管委会官网；修正上轮中文域名"野三坡景点介绍.网址"误记) 2026-11-06')),
        ('苍岩山风景名胜区', dict(
            status='na',
            src='未找到独立官网；信息经石家庄市政府sjz.gov.cn景区介绍页（检索词：苍岩山风景名胜区 官网 井陉 门票）2026-11-06')),
        ('嶂石岩风景名胜区', dict(
            web='www.hbzsyjq.cn（嶂石岩景区官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('西柏坡-天桂山风景名胜区', dict(
            web='www.xbpjng.cn（西柏坡纪念馆官网）；天桂山段无独立官网（平山县政府sjzps.gov.cn介绍页；中文域名"天桂山景点介绍.网址"归属存疑未采信）',
            status='verified',
            src='检索核验(西柏坡段官网已核+天桂山段政府页；核心名匹配) 2026-11-06')),
        ('崆山白云洞风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经微景通nwx.weijingtong.net/ticket?clientId=1024（检索词：崆山白云洞 临城 官网 门票预订）2026-11-06')),
    ],
    '18': [
        ('宿迁骆马湖旅游度假区', dict(
            web='www.sqlmlake.com（骆马湖国家级旅游度假区官网·宿迁湖滨新区旅游经济发展局主办）',
            social='公众号「骆马湖旅游度假区」',
            status='verified', src='检索核验 2026-11-06')),
        ('北海银滩国家旅游度假区', dict(
            web='www.bhyintan.com（北海银滩国家级旅游度假区官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('琼海博鳌东屿岛旅游度假区', dict(
            status='na',
            src='无独立度假区官网；官方信息经博鳌亚洲论坛官网boaoforum.org/琼海市文旅（检索词：博鳌东屿岛旅游度假区 官网）2026-11-06')),
        ('密云古北水镇国际休闲旅游度假区', dict(
            web='www.wtown.com（古北水镇官网·含票务预订）',
            status='verified', src='检索核验 2026-11-06')),
    ],
    '15': [
        ('东北师范大学东北民族民俗博物馆', dict(
            web='dbmzms.nenu.edu.cn（官网·东北师范大学）',
            social='公众号「东北师范大学东北民族民俗博物馆」',
            status='verified', src='检索核验 2026-11-06')),
        ('吉林省中医药博物馆', dict(
            web='museum.ccucm.edu.cn（长春中医药大学博物馆官网·含本馆数字展厅）',
            status='verified', src='检索核验 2026-11-06')),
    ],
    '16': [
        ('内蒙古乌海博物馆', dict(
            social='公众号「乌海市博物馆」（活动/云上展览发布）',
            status='verified', src='检索核验(公众号经媒体报道佐证；无独立官网) 2026-11-06')),
        ('集安市博物馆', dict(
            status='na',
            src='未找到独立官网/公众号；信息经集安高句丽旅游网gaogouli-tour.com/吉林省文旅厅（检索词：集安市博物馆 官网 公众号 高句丽）2026-11-06')),
    ],
    '17': [
        ('通辽市文博院', dict(
            web='www.keerqinmuseum.com（通辽市文博院门户网站）',
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
                if r[vc] not in (guard, 'na'):  # na 允许覆写（野三坡修正）
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
        ta['next'] = '03剩余43/04剩余221/18剩余21 + 博物馆558candidate；下轮续搜（04注意太行大峡谷需带省份歧义消解）'
        prog['last_run'] = TODAY + ' runB(tier_a): 03 v2/na2; 04 v3(含野三坡修正)/na2; 18 v3/na1; 博物馆 v4/na1'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
