# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

# 兜底：回合末把「本轮说出的愿望」都记进会话（不落库），保存时物化
helper = '''    def _remember_wishes(self, session: PlanSession, wishes: list[str]) -> None:
        """回合末兜底（2026-11-15）：本轮用户说出的愿望一律记进会话
        wish_sources（规划期不写库）；某些分支（已排上的专名/绑定命中）
        不进 sync 的记录段，这里补齐，保证保存时 materialize 不丢愿望。"""
        if not wishes:
            return
        sources = dict(session.wish_sources or {})
        for wish in wishes:
            name = str(wish or "").strip()
            if not name or name in sources:
                continue
            sources[name] = {
                "source": "chat",
                "note": L("来自聊天", "From chat"),
                "city": session.site_cities.get(name),
            }
        session.wish_sources = sources

'''
anchor = "    async def sync_wishes_to_trip_items(\n"
assert t.count(anchor) == 1
t = t.replace(anchor, helper + anchor, 1)

sub('''            sync_notes, unresolved = await self.sync_wishes_to_trip_items(
                session,
                wishes,
                user_texts=self._user_corpus(session),
            )
''', '''            sync_notes, unresolved = await self.sync_wishes_to_trip_items(
                session,
                wishes,
                user_texts=self._user_corpus(session),
            )
            self._remember_wishes(session, wishes)
''')
sub('''        sync_notes, unresolved = await self.sync_wishes_to_trip_items(
            session, wishes, user_texts=self._user_corpus(session)
        )
''', '''        sync_notes, unresolved = await self.sync_wishes_to_trip_items(
            session, wishes, user_texts=self._user_corpus(session)
        )
        self._remember_wishes(session, wishes)
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
