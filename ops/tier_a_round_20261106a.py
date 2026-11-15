# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run A）
在 ops_fill.lock（90秒）保护下写 CSV + 更新 progress tier_a。
只更新 status 仍为 to_verify/candidate 的行（守卫防重复写）。
"""
import csv, json, os, time, io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'DESIGN', 'POIS DATASOURCE')
LOCK = os.path.join(ROOT, 'ops', 'ops_fill.lock')
TODAY = '2026-11-06'

# (file, name_col, web_col, booking_col, social_col, status_col, src_col, ncols, guard_status)
FILES = {
    '03': ('03_国家考古遗址公园_65.csv', 1, 4, 5, 6, 7, 8, None, 'to_verify'),
    '04': ('04_国家级风景名胜区_244.csv', 3, 5, 6, 7, 8, 9, None, 'to_verify'),
    '18': ('18_国家级旅游度假区_已核29.csv', 0, 5, 6, 7, 8, 9, None, 'to_verify'),
    '15': ('15_国家二级博物馆_七省补缺.csv', 2, 7, 8, 9, 10, 11, None, 'candidate'),
    '16': ('16_国家三级博物馆_批次补全.csv', 0, 7, 8, 9, 10, 11, None, 'candidate'),
    '17': ('17_国家二级博物馆_七次评估补缺_9.csv', 0, 7, 8, 9, 10, 11, None, 'candidate'),
}

# key=文件组, value=list of (name, {web/social/status/src})
UPDATES = {
    '03': [
        ('泥河湾国家考古遗址公园', dict(
            web='www.dfnihewan.com（泥河湾国家考古遗址公园官网·河北东方泥河湾文旅运营）',
            status='verified', src='检索核验 2026-11-06')),
        ('赵王城国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网/认证公众号；官方信息经河北省文物局wenwu.hebei.gov.cn/邯郸市文旅局（检索词：赵王城国家考古遗址公园 官网 邯郸）2026-11-06')),
        ('邺城国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网/公众号；官方信息经临漳县政府linzhang.gov.cn/邺城博物馆（检索词：邺城国家考古遗址公园 官网 公众号 临漳）2026-11-06')),
        ('凌家滩国家考古遗址公园', dict(
            status='na',
            src='无独立官网；官方信息经含山县政府ahhs.gov.cn/国家文物局ncha.gov.cn（检索词：凌家滩国家考古遗址公园 官网 含山）2026-11-06')),
    ],
    '04': [
        ('四面山风景名胜区', dict(
            status='verified', src='复用02已核(核心名全等+同省重庆) 2026-11-06')),
        ('青海湖风景名胜区', dict(
            web='qhh.qinghai.gov.cn（青海湖景区保护利用管理局）',
            status='verified', src='复用02已核(核心名全等+同省青海) 2026-11-06')),
        ('八达岭-十三陵风景名胜区', dict(
            web='www.mingshisanling.com（明十三陵官网）；www.badaling.cn（八达岭长城官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('承德避暑山庄外八庙风景名胜区', dict(
            web='www.bishushanzhuang.com.cn（避暑山庄及周围寺庙官网·承德市文物局，中英日韩）',
            social='公众号「避暑山庄及周围寺庙」（实名分时预约）',
            status='verified', src='检索核验 2026-11-06')),
        ('野三坡风景名胜区', dict(
            web='野三坡风景名胜区.中国（中文域名官网，含百里峡/拒马河/龙门天关等七大景区）',
            status='verified', src='检索核验 2026-11-06')),
        ('石花洞风景名胜区', dict(
            status='na',
            src='未找到独立官网；信息经北京旅游网s.visitbeijing.com.cn/attraction/101426（检索词：石花洞风景名胜区 官方网站 门票）2026-11-06')),
        ('秦皇岛北戴河风景名胜区', dict(
            status='na',
            src='未找到独立官网；官方信息经北戴河区人民政府官网（检索词：秦皇岛北戴河风景名胜区 官网 鸽子窝公园）2026-11-06')),
    ],
    '18': [
        ('四川成都天府青城康养休闲旅游度假区', dict(
            web='www.tfqc-lb.com（天府青城康养休闲旅游度假区官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('广西桂林阳朔遇龙河旅游度假区', dict(
            web='www.ysylh.cn（遇龙河景区官网·竹筏码头预约）',
            social='小程序「遇龙河景区」/「i游阳朔」（官方指定预约）',
            status='verified', src='检索核验 2026-11-06')),
        ('云南玉溪抚仙湖旅游度假区', dict(
            web='www.cjfxh.com（抚仙湖国家级旅游度假区官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('广东河源巴伐利亚庄园', dict(
            web='www.hybava.com（巴伐利亚庄园官网，电话0762-8886888）',
            status='verified', src='检索核验(官网域名经本地宝收录页确认) 2026-11-06')),
    ],
    '15': [
        ('白城市博物馆', dict(
            social='微信公众号「白城市博物馆」（公众平台主页biz=MzkyNDUwMzYyMA）',
            status='verified', src='检索核验 2026-11-06')),
        ('白山市长白山满族文化博物馆', dict(
            web='cbsmzwhbwg.com（官网）',
            status='verified', src='检索核验 2026-11-06')),
    ],
    '16': [
        ('泥河湾博物馆', dict(
            web='nihewanmuseum.com（官网）',
            status='verified', src='检索核验 2026-11-06')),
        ('武乡县八路军总部旧址王家峪纪念馆', dict(
            status='na',
            src='未找到独立官网/公众号；信息经武乡县政府wuxiang.gov.cn/八路军太行纪念馆渠道（检索词：八路军总部王家峪旧址纪念馆 武乡 公众号 官网）2026-11-06')),
    ],
    '17': [
        ('西藏文化博物馆', dict(
            web='xzmuseum.cn（西藏文化博物馆官网·中国藏学研究中心）',
            social='微信公众平台「西藏文化博物馆」（2019上线·西藏自治区政府网公告）',
            status='verified', src='检索核验 2026-11-06')),
    ],
}


def detect_fmt(path):
    with open(path, 'rb') as f:
        raw = f.read(4096)
    bom = raw.startswith(b'\xef\xbb\xbf')
    crlf = b'\r\n' in raw
    return ('utf-8-sig' if bom else 'utf-8'), ('\r\n' if crlf else '\n')


def apply_group(key):
    fname, nc, wc, bc, sc, vc, rc, _, guard = FILES[key]
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
                if r[vc] != guard:
                    skipped.append((name, 'status=' + r[vc]))
                    hit = True
                    break
                if 'web' in upd:
                    r[wc] = upd['web']
                if 'social' in upd:
                    r[sc] = upd['social']
                r[vc] = upd['status']
                r[rc] = upd['src']
                applied.append((name, upd['status']))
                hit = True
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
                    os.remove(LOCK)  # 过期锁抢占
                    continue
            except OSError:
                continue
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
        # 更新 progress tier_a
        pj = os.path.join(ROOT, 'ops', 'official_channel_progress.json')
        prog = json.load(open(pj, encoding='utf-8'))
        ta = prog.setdefault('tier_a', {})
        done_map = ta.setdefault('done', {})
        import collections
        for key in FILES:
            fname, _, _, _, _, vc, _, _, _ = FILES[key]
            path = os.path.join(BASE, fname)
            enc, _ = detect_fmt(path)
            with open(path, encoding=enc, newline='') as f:
                rows = list(csv.reader(f))
            c = collections.Counter(r[vc] for r in rows[1:] if len(r) > vc)
            done_map[key] = '{n}行(v={v}/na={na}/to={to}/cand={cd})'.format(
                n=len(rows) - 1, v=c.get('verified', 0), na=c.get('na', 0),
                to=c.get('to_verify', 0), cd=c.get('candidate', 0))
        ta['next'] = '03剩余47/04剩余226/18剩余25 + 博物馆563candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runA(tier_a): 03升级1+na3; 04复用2+检索3+na2; 18检索4; 博物馆抽检5(v4/na1)'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
