# -*- coding: utf-8 -*-
"""Tier A 官方渠道收尾·本轮写回（2026-11-06 run E）"""
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
        ('石峁国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经神木市政府/石峁遗址管理处（检索词：石峁国家考古遗址公园 官网 神木 博物馆）2026-11-06')),
        ('统万城国家考古遗址公园', dict(
            web='www.tongwanchengyizhi.com（统万城国家考古遗址公园官网·0912-4642000）',
            social='公众号/视频号/微博/抖音「统万城」官方矩阵',
            status='verified', src='检索核验 2026-11-06')),
        ('元中都国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；咨询0313-5216142/张北县文旅（检索词：元中都国家考古遗址公园 官网 张北）2026-11-06')),
        ('大窑龙泉窑国家考古遗址公园', dict(
            status='na',
            src='未找到独立官网；官方信息经龙泉市文物局/丽水市文旅局（检索词：大窑龙泉窑国家考古遗址公园 官网 龙泉）2026-11-06')),
    ],
    '04': [
        ('金石滩风景名胜区', dict(
            web='www.jinshitan.com（大连金石滩官网）',
            status='verified', src='复用02已核(大连市金石滩·核心名匹配+同省辽宁) 2026-11-06')),
        ('兴城海滨风景名胜区', dict(
            status='na',
            src='未找到独立官网；官方信息经兴城市政府zg-xc.gov.cn景区页（检索词：兴城海滨风景名胜区 官网 葫芦岛 兴城古城）2026-11-06')),
        ('大连海滨-旅顺口风景名胜区', dict(
            status='na',
            src='无独立官网（设管理局）；官方信息经大连市自然资源局/旅顺口区政府（检索词：大连海滨旅顺口风景名胜区 官网）2026-11-06')),
        ('凤凰山风景名胜区', dict(
            status='na',
            src='未找到独立官网（运营方辽宁凤凰山旅游集团无公开站）；信息经凤城市政府/辽宁省政府官网（检索词：凤凰山风景名胜区 官网 丹东 凤城）2026-11-06')),
        ('本溪水洞风景名胜区', dict(
            status='verified', src='复用02已核(本溪市本溪水洞·核心名匹配+同省辽宁；02核验时无域名记录) 2026-11-06')),
    ],
    '18': [
        ('德州齐河黄河国际生态城旅游度假区', dict(
            status='na',
            src='无独立官网；咨询0534-5395996/齐河县政府qihe.gov.cn（检索词：齐河黄河国际生态城旅游度假区 官网）2026-11-06')),
        ('郑州银基国际旅游度假区', dict(
            web='www.enjoyland.cn（银基国际旅游度假区官网·含动物王国/冰雪世界票务）',
            status='verified', src='检索核验 2026-11-06')),
        ('武汉黄陂区木兰湖旅游度假区', dict(
            web='mulanlake.com（木兰湖官网·木兰湖旅游度假区服务中心主办）',
            status='verified', src='检索核验 2026-11-06')),
        ('长沙铜官窑文化旅游度假区', dict(
            web='www.macrolink.com.cn（新华联官网·铜官窑古镇项目页；主导景区由新华联运营）',
            status='verified',
            src='检索核验(复合度假区无独立官网，采信主导景区运营商官网项目页) 2026-11-06')),
    ],
    '15': [
        ('天津沉香艺术博物馆', dict(
            web='www.chenxiang-art.com（天津沉香艺术博物馆官网）',
            social='公众号「沉香艺术博物馆」（官网首页扫码入口）',
            status='verified', src='检索核验 2026-11-06')),
        ('天津市滨海新区博物馆', dict(
            status='na',
            src='未找到独立官网；公众号候选名「滨海新区博物馆」未获独立佐证（检索词：天津市滨海新区博物馆 官网 公众号）2026-11-06')),
    ],
    '16': [
        ('黑龙江北方民俗博物馆', dict(
            web='bfmsbwg.com（黑龙江北方民俗博物馆官网·巴彦县）',
            status='verified', src='检索核验 2026-11-06')),
        ('上海纺织博物馆', dict(
            status='na',
            src='无独立官网；公众号存在经解放日报报道但认证名未确认，勿与东华大学「纺织服饰博物馆」混淆（检索词：上海纺织博物馆 官网 公众号）2026-11-06')),
    ],
    '17': [
        ('中国共产党湖南历史展览馆', dict(
            web='www.hndsclg.com（中国共产党湖南历史展览馆官网·含网上预约）',
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
        ta['next'] = '03剩余31/04剩余206(青山沟下轮先做)/18剩余9 + 博物馆545candidate；下轮续搜'
        prog['last_run'] = TODAY + ' runE(tier_a): 03 v1/na3; 04 复用2(金石滩/本溪水洞)+na3; 18 v3/na1; 博物馆 v3/na2'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
