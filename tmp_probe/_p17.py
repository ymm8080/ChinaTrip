# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\pg_state.py"
t = io.open(p, encoding="utf-8", newline="").read()

def sub(old, new, n=1):
    global t
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''    def _boot_load(self) -> None:\r
        try:\r
            self._pg_reload_items()\r
        except OperationalError as exc:\r
            self._pg_ok = False\r
            logger.warning("pg_state: PG 不可达，trip items 降级纯内存: %s", exc)\r
\r
    def _try_refresh(self) -> None:\r
''', '''    def purge_stale_drafts(self, *, days: int = 7) -> int:\r
        """过期心愿草稿物理清理（2026-11-14）：草稿从未进过心愿单（看板/\r
        视图都不可见），保留 N 天只是给「保存行程」留转正窗口——超过就删，\r
        别让未保存行程的行在库里无限堆积。迁移回填的 legacy 草稿同样按\r
        建行时间清。"""\r
        if not self._pg_ok:\r
            return 0\r
        try:\r
            with self._session_factory() as session, session.begin():\r
                result = session.execute(\r
                    text(\r
                        "DELETE FROM trip_items"\r
                        " WHERE draft_session_id IS NOT NULL"\r
                        "   AND created_at < NOW() - (:days || \' days\')::interval"\r
                    ),\r
                    {"days": days},\r
                )\r
                rowcount = getattr(result, "rowcount", None)\r
                purged = int(rowcount or 0)\r
        except Exception:\r
            logger.warning("pg_state: 心愿草稿过期清理失败", exc_info=True)\r
            return 0\r
        if purged:\r
            logger.info("pg_state: 心愿草稿过期清理 %d 行（>%d 天未保存）", purged, days)\r
            self._pg_reload_items()\r
        return purged\r
\r
    def _boot_load(self) -> None:\r
        try:\r
            self._pg_reload_items()\r
            self.purge_stale_drafts()\r
        except OperationalError as exc:\r
            self._pg_ok = False\r
            logger.warning("pg_state: PG 不可达，trip items 降级纯内存: %s", exc)\r
\r
    def _try_refresh(self) -> None:\r
''')

io.open(p, "w", encoding="utf-8", newline="").write(t)
print("ok")
