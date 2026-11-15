# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run J）"""
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
}

UPDATES = {
    '03': [
        ('甑皮岩国家考古遗址公园', dict(
            web='www.zpybwg.com（桂林甑皮岩遗址博物馆官网·含参观服务/研学）',
            status='verified', src='检索核验 2026-11-06')),
        ('钓鱼城国家考古遗址公园', dict(
            social='小程序「千古钓鱼城」（官方购票渠道）',
            status='verified',
            src='检索核验(无独立官网；官方小程序购票渠道经检索确认) 2026-11-06')),
        ('北庭故城国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经吉木萨尔县政府/北庭高昌回鹘佛寺遗址博物馆（检索词：北庭故城国家考古遗址公园 官网 吉木萨尔）2026-11-06')),
        ('鸿山国家考古遗址公园', dict(
            web='hongbozhijia.com（鸿博之家·鸿山遗址公园运营方页）',
            status='verified',
            src='检索核验(运营方官网项目页采信，性质注明；2025博物馆焕新开馆) 2026-11-06')),
        ('隋唐洛阳城国家考古遗址公园', dict(
            web='www.suitangluoyang.com（洛阳市隋唐城遗址博物馆官网·应天门/明堂/九洲池）',
            status='verified', src='检索核验 2026-11-06')),
        ('陶寺国家考古遗址公园', dict(
            status='na',
            src='无独立官网；官方信息经新华社/国家文物局ncha.gov.cn/襄汾县（检索词：陶寺国家考古遗址公园 官网 襄汾 遗址博物馆）2026-11-06')),
        ('萨拉乌苏国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网（设管理局）；官方信息经乌审旗政府/内蒙古文物局（检索词：萨拉乌苏国家考古遗址公园 官网 内蒙古）2026-11-06')),
        ('和林格尔土城子国家考古遗址公园', dict(
            status='na',
            src='无独立官网；官方信息经和林格尔县政府/呼和浩特文旅广电局wlgd.huhhot.gov.cn（检索词：和林格尔土城子国家考古遗址公园 官网）2026-11-06')),
    ],
    '04': [
        ('天姥山风景名胜区', dict(
            status='na',
            src='未找到独立官网；官方信息经新昌县政府xinchang.gov.cn（检索词：天姥山风景名胜区 官网 新昌）2026-11-06')),
        ('大红岩风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA（检索词：大红岩风景名胜区 官网 武义 门票）2026-11-06')),
        ('大盘山风景名胜区', dict(
            status='na',
            src='未找到独立官网（设国家级自然保护区管理局）；官方信息经磐安县政府panan.gov.cn（检索词：大盘山风景名胜区 官网 磐安）2026-11-06')),
        ('桃渚风景名胜区', dict(
            status='na',
            src='未找到独立官网；官方信息经临海市政府/临海文旅（检索词：桃渚风景名胜区 官网 临海）2026-11-06')),
        ('仙华山风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA（检索词：仙华山风景名胜区 官网 浦江 门票）2026-11-06')),
        ('九华山风景名胜区', dict(
            web='chinahuashan.com（九华山景区官网·含票务）',
            status='verified', src='复用02已核(池州市九华山风景区·同名匹配+同省安徽) 2026-11-06')),
        ('天柱山风景名胜区', dict(
            web='www.tzsgy.com（天柱山世界地质公园官网）',
            status='verified', src='复用02已核(安庆市天柱山风景区·同名匹配+同省安徽) 2026-11-06')),
        ('琅琊山风景名胜区', dict(
            web='lysfjq.cn（琅琊山官网·含门票预订）',
            status='verified', src='复用02已核(滁州市琅琊山景区·同名匹配+同省安徽) 2026-11-06')),
    ],
    '15': [
        ('中卫市博物馆', dict(
            social='公众号「中卫博物馆」（实名预约，媒体点名佐证）',
            status='verified',
            src='检索核验(公众号经媒体预约指南点名；无独立官网) 2026-11-06')),
        ('阿克苏地区文博院（博物馆）', dict(
            status='na',
            src='无独立官网；公众号候选名「阿克苏地区文博院」为建议性表述未获佐证（检索词：阿克苏地区文博院 博物馆 官网 公众号）2026-11-06')),
    ],
    '16': [
        ('浦江博物馆', dict(
            status='na',
            src='未找到独立官网/公众号；信息经浦江文旅等当地渠道（检索词：浦江博物馆 官网 公众号）2026-11-06')),
        ('兰溪市博物馆', dict(
            status='na',
            src='无独立官网；公众号存在迹象（微信文章链接）但认证名未获源文点名；信息经兰溪市政府/兰溪文旅（检索词：兰溪市博物馆 官网 公众号）2026-11-06')),
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
        ta['next'] = '03剩余7/04剩余166/18完成 + 博物馆519candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runJ(tier_a): 03 v4/na4; 04 复用3+na5(浙江小景区段普遍无官网); 博物馆 v1/na3'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
