# -*- coding: utf-8 -*-
import io, os
base = r"D:\CHINATRIP\CHINATRIP CODES"
mp = os.path.join(base, "app", "models.py")
text = io.open(mp, encoding="utf-8", newline="").read()
old = '''    itinerary_ref: Mapped[str | None] = mapped_column(String(64), index=True)\r
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(\r
        UUID(as_uuid=True), ForeignKey("itineraries.id")\r
    )\r
'''
new = old + '''    # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：规划会话建行\r
    # 时写入会话号——非空 = 草稿，看板/心愿单视图不返回；点「💾 保存行程」\r
    # 时清空转正，删行程时按 itinerary_ref 一并软删。\r
    draft_session_id: Mapped[str | None] = mapped_column(String(64), index=True)\r
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)
io.open(mp, "w", encoding="utf-8", newline="").write(text)
print("models patched")
