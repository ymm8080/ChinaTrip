# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run H）"""
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
        ('汉长安城未央宫国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；免费预约经官方合作平台，信息经西安市文物局/汉长安城特区（检索词：汉长安城未央宫国家考古遗址公园 官网 西安）2026-11-06')),
        ('渤海中京国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经和龙市政府/国家文物局ncha.gov.cn（检索词：渤海中京国家考古遗址公园 官网 和龙 西古城）2026-11-06')),
        ('渤海上京国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经黑龙江省文旅厅wlt.hlj.gov.cn/宁安市文旅（检索词：渤海上京国家考古遗址公园 官网 宁安）2026-11-06')),
        ('曲阜鲁国故城国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经曲阜市政府qufu.gov.cn/济宁市文旅局（检索词：曲阜鲁国故城国家考古遗址公园 官网）2026-11-06')),
    ],
    '04': [
        ('富春江-新安江风景名胜区', dict(
            web='www.qiandaohu.cc（千岛湖官网·新安江段即千岛湖水库）',
            status='verified',
            src='复用02已核(杭州市千岛湖风景区·新安江段覆盖+同省浙江；富春江段经桐庐/富阳属地渠道) 2026-11-06')),
        ('雁荡山风景名胜区', dict(
            web='www.wzyds.com（雁荡山官网）',
            status='verified', src='复用02已核(温州市雁荡山风景区·同名匹配+同省浙江) 2026-11-06')),
        ('普陀山风景名胜区', dict(
            status='verified', src='复用02已核(舟山市普陀山风景区·同名匹配+同省浙江；02核验时无域名记录) 2026-11-06')),
        ('天台山风景名胜区', dict(
            web='www.ttsly.com.cn（天台山官网·含票务信息页）',
            status='verified', src='复用02已核(台州市天台山景区·同名匹配+同省浙江；成都天台山为同名不同景区) 2026-11-06')),
        ('嵊泗列岛风景名胜区', dict(
            status='na',
            src='未找到独立官网；船票经官方公众号（名未确认）；信息经嵊泗县政府（检索词：嵊泗列岛风景名胜区 官网 门票）2026-11-06')),
        ('楠溪江风景名胜区', dict(
            web='www.nxj.cn（楠溪江官网）',
            social='小程序「智游楠溪」（门票/竹筏预约）',
            status='verified', src='检索核验 2026-11-06')),
        ('莫干山风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA（检索词：莫干山风景名胜区 官网 德清 门票）2026-11-06')),
        ('雪窦山风景名胜区', dict(
            web='www.xikoutourism.com（溪口-滕头景区官网·雪窦山为其核心组成）',
            status='verified', src='复用02已核(宁波市溪口-滕头旅游景区·同体覆盖+同省浙江) 2026-11-06')),
    ],
    '15': [
        ('宁夏回族自治区地质博物馆', dict(
            status='na',
            src='未找到独立官网；公众号候选名「宁夏地质博物馆」未获独立佐证（检索词：宁夏地质博物馆 官网 公众号 预约）2026-11-06')),
        ('彭阳县博物馆', dict(
            status='na',
            src='未找到独立官网/公众号；信息经彭阳县政府pengyang.gov.cn（检索词：彭阳县博物馆 官网 公众号）2026-11-06')),
    ],
    '16': [
        ('海盐县博物馆', dict(
            status='na',
            src='无独立官网；预约经电话/浙里好玩/微信公众号（名未获源文点名）；勿与盐城中国海盐博物馆混淆（检索词：海盐县博物馆 官网 公众号 预约）2026-11-06')),
        ('桐乡市钟旭洲钱币艺术博物馆', dict(
            status='na',
            src='未找到独立官网；公众号名无法确认；信息经桐乡市文广新局/当地平台（检索词：桐乡市钟旭洲钱币艺术博物馆 官网 公众号）2026-11-06')),
    ],
    '17': [
        ('巴音郭楞蒙古自治州文博院', dict(
            social='公众号「巴州博物馆」（节假日安排/预约以此发布，库尔勒市政府网佐证）',
            status='verified',
            src='检索核验(即巴州博物馆；公众号经政府网公告佐证；无独立官网) 2026-11-06')),
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
        ta['next'] = '03剩余19/04剩余182/18完成 + 博物馆530candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runH(tier_a): 03 v0/na4; 04 复用5+检索1v/na2(浙江段复用富矿); 博物馆 v1/na4'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
