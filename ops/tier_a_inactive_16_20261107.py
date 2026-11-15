# -*- coding: utf-8 -*-
"""2026-11-07 用户决定：16文件(国家三级博物馆_批次补全) 485行candidate标记inactive退出核验池。
已核的17 verified + 26 na保留不动。90秒锁内执行。"""
import csv, json, os, time
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'DESIGN', 'POIS DATASOURCE')
LOCK = os.path.join(ROOT, 'ops', 'ops_fill.lock')
TODAY = '2026-11-07'

FNAME = '16_国家三级博物馆_批次补全.csv'
VC, RC, NCOLS = 10, 11, 17
NOTE = '用户决定' + TODAY + ':三级博物馆批次退出逐馆核验(行保留inactive,未逐馆搜索)'


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
        changed = 0
        for r in rows[1:]:
            if len(r) > RC and r[VC] == 'candidate':
                r[VC] = 'inactive'
                r[RC] = NOTE
                changed += 1
        with open(path, 'w', encoding=enc, newline='') as f:
            w = csv.writer(f, lineterminator=nl)
            for r in rows:
                w.writerow(r[:NCOLS] + [''] * max(0, NCOLS - len(r)))
        # 更新进度文件
        pj = os.path.join(ROOT, 'ops', 'official_channel_progress.json')
        prog = json.load(open(pj, encoding='utf-8'))
        ta = prog.setdefault('tier_a', {})
        with open(path, encoding=enc, newline='') as f:
            rows2 = list(csv.reader(f))
        c = collections.Counter(r[VC] for r in rows2[1:] if len(r) > VC)
        ta.setdefault('done', {})['16'] = '{n}行(v={v}/na={na}/inactive={inact}/cand=0)'.format(
            n=len(rows2) - 1, v=c.get('verified', 0), na=c.get('na', 0), inact=c.get('inactive', 0))
        ta['user_decision'] = (TODAY + ' 用户决定:16文件485行candidate一次性标记inactive退出核验池'
                               '(保留行与已核43行成果,未逐馆搜索);tier_a剩余工作仅04×110行to_verify')
        ta['next'] = '仅剩04×110行to_verify；16已按用户决定inactive收口'
        prog['last_run'] = TODAY + ' runR(user): 16文件485行candidate→inactive(用户决定退出核验池)'
        json.dump(prog, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('marked inactive:', changed)
        print('file counter:', dict(sorted(c.items())))
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    main()
