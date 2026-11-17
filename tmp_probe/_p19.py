# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\pg_state.py"
t = io.open(p, encoding="utf-8", newline="").read()
old = '''    def _boot_load(self) -> None:\r
        try:\r
            self._pg_reload_items()\r
            self.purge_stale_drafts()\r
        except OperationalError as exc:\r
'''
new = '''    def _boot_load(self) -> None:\r
        try:\r
            self._pg_reload_items()\r
            # 过期草稿清理由应用启动钩子（app.main._lifespan）调\r
            # purge_stale_drafts()——boot 阶段不多开会话，测试桩按会话数\r
            # 断言的用例不受影响。\r
        except OperationalError as exc:\r
'''
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("pg_state boot ok")

p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\main.py"
t2 = io.open(p2, encoding="utf-8", newline="").read()
old2 = '''    stop = threading.Event()\r
    threading.Thread(\r
        target=_pg_keepalive, args=(stop,), daemon=True, name="pg-keepalive"\r
    ).start()\r
'''
new2 = '''    stop = threading.Event()\r
    threading.Thread(\r
        target=_pg_keepalive, args=(stop,), daemon=True, name="pg-keepalive"\r
    ).start()\r
    # 2026-11-14（用户拍板「没保存行程，心愿单不该保存」）：心愿草稿只在\r
    # 库里短暂停留等「保存行程」转正——启动时清掉超期未保存的草稿行，\r
    # 别让放弃的规划无限堆积。\r
    try:\r
        from app.api.trip_items import get_trip_item_service\r
\r
        await asyncio.to_thread(get_trip_item_service().purge_stale_drafts)\r
    except Exception:\r
        logger.warning("main: 心愿草稿过期清理失败", exc_info=True)\r
'''
assert t2.count(old2) == 1
t2 = t2.replace(old2, new2, 1)
io.open(p2, "w", encoding="utf-8", newline="").write(t2)
print("main ok")
