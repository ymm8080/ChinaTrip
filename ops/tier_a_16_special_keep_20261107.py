# -*- coding: utf-8 -*-
"""2026-11-07 用户要求甄别:16文件inactive行中保留特殊馆。
甄别标准:①跨文件/同体复用可直升verified(零成本) ②依托世遗/5A/著名景区或城市地标。
7行→verified(复用); 26行→candidate(保留核验池); 其余452行维持inactive。"""
import csv, json, os, time
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'DESIGN', 'POIS DATASOURCE')
LOCK = os.path.join(ROOT, 'ops', 'ops_fill.lock')
TODAY = '2026-11-07'
FNAME = '16_国家三级博物馆_批次补全.csv'
NC, WC, SC, VC, RC, NCOLS = 0, 7, 9, 10, 11, 17

VERIFY = {
    '新疆喀什地区博物馆': dict(
        social='公众号「喀什地区博物馆服务号」（门票预约·全预约入馆）',
        src='复用runK已核(15文件同名喀什地区博物馆·经喀什市政府网佐证) ' + TODAY),
    '大庆石油科技馆': dict(
        social='公众号「大庆石油科技馆」（免费预约参观）',
        src='复用runD已核(16文件"大庆油田有限责任公司大庆石油科技馆"同名馆) ' + TODAY),
    '连城县博物馆': dict(
        web='www.lcxbwg.cn（连城县博物馆官网·含数字博物馆）',
        src='复用runL已核(16文件"福建省连城县博物馆"同名馆) ' + TODAY),
    '桂林甑皮岩遗址博物馆': dict(
        web='www.zpybwg.com（甑皮岩遗址博物馆官网·runC核于03甑皮岩考古遗址公园行）',
        src='复用runC已核(该官网即本博物馆官网) ' + TODAY),
    '澧县城头山古文化遗址博物馆': dict(
        web='www.chcts.net（澧县城头山官网·含博物馆栏目，runF核于03城头山行）',
        src='复用runF已核(公园官网覆盖园内博物馆) ' + TODAY),
    '桂林市靖江王陵博物馆': dict(
        web='www.guilinjjwl.cn（靖江王陵考古遗址公园官网，runC核于03靖江王陵行）',
        src='复用runC已核(公园官网覆盖王陵博物馆) ' + TODAY),
    '钓鱼城古战场遗址博物馆': dict(
        social='小程序「千古钓鱼城」（钓鱼城考古遗址公园官方渠道，runJ核于03钓鱼城行；博物馆位于园内）',
        src='复用runJ已核(公园官方渠道覆盖园内博物馆) ' + TODAY),
}
KEEP = {
    '永顺县老司城博物馆': '湖南·世界文化遗产老司城遗址的遗址博物馆',
    '泉州华侨历史博物馆': '福建·世界遗产泉州：宋元中国的世界海洋商贸中心所在城市',
    '平遥县双林寺彩塑艺术馆': '山西·世界遗产平遥古城组成部分双林寺',
    '平遥县票号博物馆': '山西·平遥古城内日昇昌票号旧址（中国票号博物馆）',
    '平遥县博物馆': '山西·平遥古城内',
    '孙中山纪念馆': '江苏·南京中山陵景区（钟山风景名胜区）',
    '南京抗日航空烈士纪念馆': '江苏·南京钟山风景区',
    '绍兴市兰亭书法博物馆': '浙江·绍兴兰亭景区',
    '昭君博物院': '内蒙古·呼和浩特昭君博物院（昭君墓景区）',
    '五大连池世界地质公园博物馆': '黑龙江·五大连池世界地质公园（04已核管委会官网）',
    '西安市钟鼓楼博物馆': '陕西·西安钟鼓楼城市地标',
    '勉县武侯祠博物馆': '陕西·勉县武侯祠（天下第一武侯祠）',
    '皇泽寺博物馆': '四川·广元皇泽寺（国保·武则天祀庙）',
    '奉节县白帝城博物馆': '重庆·白帝城·瞿塘峡5A景区',
    '溪口博物馆': '浙江·奉化溪口-滕头5A景区',
    '黄山市徽州区潜口民宅博物馆': '安徽·潜口民宅（国保·徽州文化景区）',
    '灵渠博物院': '广西·兴安灵渠（世界灌溉工程遗产·著名景区）',
    '泰宁县博物馆': '福建·泰宁古城尚书第建筑群（国保）',
    '大理市博物馆': '云南·大理古城（杜文秀帅府）',
    '迪庆州博物馆': '云南·香格里拉',
    '中华世纪坛艺术馆': '北京·中华世纪坛',
    '北京奥运博物馆': '北京·奥林匹克公园',
    '广州十三行博物馆': '广东·广州文化公园',
    '合肥市李鸿章故居陈列馆': '安徽·合肥李鸿章故居（市中心景点）',
    '乌鲁木齐市博物馆': '新疆·首府乌鲁木齐',
    '秭归县屈原纪念馆（秭归县博物馆）': '湖北·屈原故里文化旅游区（5A）',
}


def detect_fmt(path):
    with open(path, 'rb') as f:
        raw = f.read(4096)
    return ('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'), ('\r\n' if b'\r\n' in raw else '\n')


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
        path = os.path.join(BASE, FNAME)
        enc, nl = detect_fmt(path)
        with open(path, encoding=enc, newline='') as f:
            rows = list(csv.reader(f))
        n_v = n_k = miss = 0
        for r in rows[1:]:
            if len(r) <= RC or r[NC] not in VERIFY and r[NC] not in KEEP:
                continue
            name = r[NC]
            if r[VC] != 'inactive':
                continue
            if name in VERIFY:
                upd = VERIFY[name]
                if 'web' in upd:
                    r[WC] = upd['web']
                if 'social' in upd:
                    r[SC] = upd['social']
                r[VC] = 'verified'
                r[RC] = upd['src']
                n_v += 1
            else:
                r[VC] = 'candidate'
                r[RC] = '用户甄别保留(' + KEEP[name] + ') ' + TODAY
                n_k += 1
        with open(path, 'w', encoding=enc, newline='') as f:
            w = csv.writer(f, lineterminator=nl)
            for r in rows:
                w.writerow(r[:NCOLS] + [''] * max(0, NCOLS - len(r)))
        # 进度更新
        pj = os.path.join(ROOT, 'ops', 'official_channel_progress.json')
        prog = json.load(open(pj, encoding='utf-8'))
        ta = prog.setdefault('tier_a', {})
        with open(path, encoding=enc, newline='') as f:
            rows2 = list(csv.reader(f))
        c = collections.Counter(r[VC] for r in rows2[1:] if len(r) > VC)
        ta.setdefault('done', {})['16'] = '{n}行(v={v}/na={na}/inactive={inact}/cand={cd})'.format(
            n=len(rows2) - 1, v=c.get('verified', 0), na=c.get('na', 0),
            inact=c.get('inactive', 0), cd=c.get('candidate', 0))
        ta['user_decision'] = (TODAY + ' 用户决定:16文件485行candidate标inactive退出核验池;经甄别保留33行特殊馆'
                               '(7行复用直升verified+26行世遗/5A/著名景区馆回candidate),452行维持inactive')
        ta['next'] = '04×110行to_verify + 16×26行保留candidate'
        prog['last_run'] = TODAY + ' runS(user): 16文件甄别——7行复用升verified, 26行保留candidate, 452行维持inactive'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('verified(reuse):', n_v, '| kept candidate:', n_k)
        print('file counter:', dict(sorted(c.items())))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
