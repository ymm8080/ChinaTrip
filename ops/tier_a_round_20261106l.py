# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run L）"""
import csv, json, os, time
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'DESIGN', 'POIS DATASOURCE')
LOCK = os.path.join(ROOT, 'ops', 'ops_fill.lock')
TODAY = '2026-11-06'

FILES = {
    '04': ('04_国家级风景名胜区_244.csv', 3, 5, 7, 8, 9, 'to_verify'),
    '15': ('15_国家二级博物馆_七省补缺.csv', 2, 7, 9, 10, 11, 'candidate'),
    '16': ('16_国家三级博物馆_批次补全.csv', 0, 7, 9, 10, 11, 'candidate'),
}

UPDATES = {
    '04': [
        ('清源山风景名胜区', dict(
            web='www.qysfjq.com（清源山官网·含门票预订/线上购票）',
            status='verified', src='复用02已核(泉州市清源山风景名胜区·同名全匹配+同省福建) 2026-11-06')),
        ('鼓浪屿-万石山风景名胜区', dict(
            web='www.glyylq.cn（鼓浪屿文化旅游发展中心官网）；www.xmferry.com（厦门轮渡官网·鼓浪屿渡运）',
            status='verified',
            src='复用02/08已核(厦门市鼓浪屿风景名胜区+世遗鼓浪屿历史国际社区·鼓浪屿段双证覆盖；万石山段经厦门园林部门) 2026-11-06')),
        ('太姥山风景名胜区', dict(
            status='verified', src='复用02已核(宁德市太姥山旅游区·同名匹配+同省福建；02核验时无域名记录) 2026-11-06')),
        ('桃源洞-鳞隐石林风景名胜区', dict(
            status='na',
            src='未找到独立官网；预订经OTA；信息经永安市文旅（检索词：桃源洞鳞隐石林风景名胜区 官网 永安 门票）2026-11-06')),
        ('泰宁风景名胜区', dict(
            web='www.taininggeopark.com（泰宁世界地质公园官网·资讯）',
            status='verified', src='复用02已核(三明市泰宁风景旅游区·同名匹配+同省福建) 2026-11-06')),
        ('海坛风景名胜区', dict(
            status='na',
            src='未找到独立官网；票务资讯经平潭官方网pingtan.cn/实验区文旅（检索词：海坛风景名胜区 官网 平潭 门票）2026-11-06')),
        ('冠豸山风景名胜区', dict(
            web='www.lcxgzs.cn（冠豸山官网·含在线购票页）',
            status='verified', src='复用02已核(龙岩市冠豸山景区·同名匹配+同省福建) 2026-11-06')),
        ('鼓山风景名胜区', dict(
            status='na',
            src='登山免费无独立官网（涌泉寺等收费点分设）；票价经福州市发改委fgw.fuzhou.gov.cn公示（检索词：鼓山风景名胜区 官网 福州 门票）2026-11-06')),
    ],
    '15': [
        ('新疆巴音郭楞蒙古自治州文博院（新疆巴音郭楞蒙古自治州博物馆）', dict(
            social='公众号「巴州博物馆」（节假日安排/预约发布，库尔勒市政府网佐证）',
            status='verified',
            src='复用runH对同名馆检索结论(即巴州博物馆；公众号经政府网公告佐证) 2026-11-06')),
        ('伊犁哈萨克自治州博物馆', dict(
            status='na',
            src='无独立官网；公众号候选名未确认（预约经官方公众号，伊犁州文旅局口径）；信息经伊犁州政府xjyl.gov.cn（检索词：伊犁哈萨克自治州博物馆 官网 公众号 预约）2026-11-06')),
    ],
    '16': [
        ('毛主席率领红军攻克漳州纪念馆', dict(
            status='na',
            src='未找到独立官网/公众号（芝山红楼）；公告经媒体发布；信息经漳州市文旅局/省文物局（检索词：毛主席率领红军攻克漳州纪念馆 官网 公众号）2026-11-06')),
        ('福建省连城县博物馆', dict(
            web='www.lcxbwg.cn（连城县博物馆官网·含数字博物馆）',
            status='verified', src='检索核验 2026-11-06')),
        ('客家族谱博物馆', dict(
            status='na',
            src='无独立官网；公众号存在迹象（微信文章）但认证名未确认；信息经上杭县文旅（检索词：客家族谱博物馆 上杭 官网 公众号）2026-11-06')),
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
        ta['next'] = '03/17/18完成/04剩余150/01预填 + 博物馆511candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runL(tier_a): 04 复用5(福建段富矿:清源山/鼓浪屿/太姥山/泰宁/冠豸山)+na3; 博物馆 v2/na3'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
