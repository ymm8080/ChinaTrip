# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run C）"""
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
        ('仰韶村国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经渑池县政府mianchi.gov.cn（检索词：仰韶村国家考古遗址公园 官网 渑池）2026-11-06')),
        ('二里头国家考古遗址公园', dict(
            web='www.eltxdmuseum.com（二里头夏都遗址博物馆官网·免费预约）',
            status='verified', src='检索核验 2026-11-06')),
        ('郑州商城国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；资讯经「郑州商代都城遗址博物院」公众号/郑州市文物局（检索词：郑州商城国家考古遗址公园 官网 公众号）2026-11-06')),
        ('屈家岭国家考古遗址公园', dict(
            web='www.qujialingsitemuseum.com（屈家岭遗址博物馆官网）',
            status='verified', src='检索核验 2026-11-06')),
    ],
    '04': [
        ('太行大峡谷风景名胜区', dict(
            status='na',
            src='河北境内=邢台信都区路罗镇（2012第八批国家级），与河南林州太行大峡谷(thdxg.net)非同一景区，官网不可挪用；未找到邢台侧独立官网（检索词：太行大峡谷风景名胜区 河北/邢台 太行大峡谷 官网 信都区）2026-11-06')),
        ('响堂山风景名胜区', dict(
            web='xtstour.com（数字响堂官方平台·数字展示馆）',
            status='verified', src='检索核验 2026-11-06')),
        ('娲皇宫风景名胜区', dict(
            web='www.shexianwahuanggong.com（娲皇宫官网·涉县娲皇宫管理中心，含预订服务页）',
            status='verified', src='检索核验 2026-11-06')),
        ('恒山风景名胜区', dict(
            web='www.byhs.net.cn（北岳恒山景区官网·恒山风景名胜区管理中心）',
            social='公众号「恒山景区」/「北岳恒山景区」（官方授权售票）',
            status='verified', src='检索核验 2026-11-06')),
        ('北武当山风景名胜区', dict(
            status='na',
            src='未找到独立官网；咨询0358-6071189（检索词：北武当山景区 官网 方山县 门票）2026-11-06')),
    ],
    '18': [
        ('晋城太行锡崖沟旅游度假区', dict(
            web='太行锡崖沟.com（中文域名官网·punycode xn--sss24g5rrx30akon.com）',
            status='verified', src='检索核验(域名解码与度假区名全合，含About子页) 2026-11-06')),
        ('兴安盟阿尔山旅游度假区', dict(
            status='na',
            src='无独立度假区官网；官方信息经兴安盟行署xam.gov.cn/阿尔山市文旅体局（检索词：阿尔山旅游度假区 官网 兴安盟）2026-11-06')),
        ('大连长山群岛旅游度假区', dict(
            web='长山群岛旅游度假区.cn（中文域名官网·punycode xn--sxqt5e87giyd9f79iuyrooq140b257a56m.cn）',
            status='verified', src='检索核验(域名解码与度假区名全合) 2026-11-06')),
        ('长白山华美胜地旅游度假区', dict(
            social='公众号「长白山华美胜地」（经新华网报道佐证）',
            status='verified',
            src='检索核验(公众号经媒体佐证；无独立官网，勿与万达度假区wandaresorts.com混淆) 2026-11-06')),
    ],
    '15': [
        ('吉林市满族博物馆', dict(
            web='www.jlsmzbwg.org.cn（官网·吉林市文旅局）',
            status='verified', src='检索核验 2026-11-06')),
        ('集安市博物馆', dict(
            status='na',
            src='复用runB对同名馆检索结论：未找到独立官网/公众号；信息经集安高句丽旅游网gaogouli-tour.com/吉林省文旅厅 2026-11-06')),
    ],
    '16': [
        ('汤原县博物馆', dict(
            web='www.tybwg.org.cn（汤原博物馆官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('黑龙江省双鸭山市博物馆', dict(
            status='na',
            src='未找到独立官网/公众号确认；预订经OTA（检索词：双鸭山市博物馆 官网 公众号/官方网站 预约）2026-11-06')),
    ],
    '17': [
        ('杭州西溪湿地博物馆', dict(
            social='公众号「中国湿地博物馆」（博悦游栏目预约）',
            status='verified',
            src='检索核验(即中国湿地博物馆；无独立官网，公众号为官方预约通道) 2026-11-06')),
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
        ta['next'] = '03剩余39/04剩余217/18剩余17 + 博物馆555candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runC(tier_a): 03 v2/na2; 04 v3/na2(太行大峡谷已与河南消歧); 18 v3/na1; 博物馆 v3/na2(集安15复用runB)'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
