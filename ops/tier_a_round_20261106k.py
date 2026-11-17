# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run K）——03 文件本轮清零"""
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
        ('上山国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网（新馆2025年底开馆）；官方信息经浦江县政府/浦江发布（检索词：上山国家考古遗址公园 官网 浦江）2026-11-06')),
        ('双墩国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网（2025挂牌）；官方信息经淮上区政府huaishang.gov.cn/蚌埠文旅（检索词：双墩国家考古遗址公园 官网 蚌埠）2026-11-06')),
        ('大汶口国家考古遗址公园', dict(
            web='www.dawenkoupark.com（大汶口国家考古遗址公园官网）',
            social='小程序「大汶口国家考古遗址公园」',
            status='verified', src='检索核验 2026-11-06')),
        ('大河村国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网（2025-12焕新开园）；官方信息经郑州市政府zhengzhou.gov.cn（检索词：大河村国家考古遗址公园 官网 郑州）2026-11-06')),
        ('铜绿山国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经大冶市政府hbdaye.gov.cn/湖北省文旅厅（检索词：铜绿山国家考古遗址公园 官网 大冶）2026-11-06')),
        ('宝墩国家考古遗址公园', dict(
            status='na',
            src='无独立官网（2025挂牌）；官方信息经新津区/成都文物考古研究院（检索词：宝墩国家考古遗址公园 官方 新津）2026-11-06')),
        ('秦咸阳城咸阳宫国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；秦咸阳宫遗址博物馆无独立站（029-32868962）；信息经咸阳本地宝/新华网（检索词：秦咸阳城国家考古遗址公园 官网 咸阳宫）2026-11-06')),
    ],
    '04': [
        ('齐云山风景名胜区', dict(
            social='小程序「祥源旅行」（运营方祥源官方预订·齐云山）',
            status='verified',
            src='检索核验(无独立官网；采信运营方祥源官方预订小程序) 2026-11-06')),
        ('采石风景名胜区', dict(
            web='csjfjq.com（长江采石矶官网）',
            status='verified', src='复用02已核(马鞍山市长江采石矶文化生态旅游区·采石矶段核心匹配+同省安徽) 2026-11-06')),
        ('巢湖风景名胜区', dict(
            status='na',
            src='未找到独立官网；官方信息经合肥市/巢湖市政府（中庙-姥山岛创建5A中）（检索词：巢湖风景名胜区 官网 合肥 中庙）2026-11-06')),
        ('花山谜窟-渐江风景名胜区', dict(
            status='na',
            src='未找到独立官网；票务经OTA/大河票务，资讯经黄山文旅（检索词：花山谜窟 官网 黄山 门票）2026-11-06')),
        ('太极洞风景名胜区', dict(
            status='na',
            src='未找到独立官网；官方信息经广德市政府guangde.gov.cn（检索词：太极洞风景名胜区 官网 广德 门票）2026-11-06')),
        ('花亭湖风景名胜区', dict(
            web='www.hthfjq.com（花亭湖旅游区官网·含在线购票）',
            status='verified', src='检索核验 2026-11-06')),
        ('龙川风景名胜区', dict(
            status='verified', src='复用02已核(宣城市龙川景区·同名匹配+同省安徽；02核验时无域名记录) 2026-11-06')),
        ('齐山-平天湖风景名胜区', dict(
            status='na',
            src='未找到独立官网（免费开放4A）；官方信息经池州市政府czxf.gov.cn（检索词：齐山平天湖风景名胜区 官网 池州）2026-11-06')),
    ],
    '15': [
        ('和田地区博物馆', dict(
            status='na',
            src='无独立官网/专属公众号确认；预约经「和田零距离」公众号-和田文旅一卡通平台（检索词：和田地区博物馆 官网 公众号 预约）2026-11-06')),
        ('喀什地区博物馆', dict(
            social='公众号「喀什地区博物馆服务号」（门票预约·全预约入馆）',
            status='verified',
            src='检索核验(公众号预约通道经喀什市政府网xjks.gov.cn佐证；无独立官网) 2026-11-06')),
        ('克拉玛依市文博院（展览馆）', dict(
            status='na',
            src='未找到独立官网/公众号（哈密文博院有站、克拉玛依暂无）；信息经克拉玛依市政府klmy.gov.cn（检索词：克拉玛依市文博院 展览馆 官网 公众号）2026-11-06')),
    ],
    '16': [
        ('福建民俗博物馆', dict(
            web='minsu.fjsen.com（福建民俗博物馆官网·省文旅厅直属·三坊七巷郎官巷）',
            status='verified', src='检索核验 2026-11-06')),
        ('南安市博物馆', dict(
            social='小程序「南安文博」（官方数字平台·云展厅，省文物局报道）',
            status='verified',
            src='检索核验(官方小程序经福建省文物局wwj.wlt.fujian.gov.cn报道佐证；无独立官网) 2026-11-06')),
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
        ta['next'] = '03完成(to=0)/04剩余158/18完成 + 博物馆515candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runK(tier_a): 03 v1/na6→65行全部收口; 04 复用2+检索2v/na4; 博物馆 v3/na2'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
