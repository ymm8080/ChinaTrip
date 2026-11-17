import io
msg = """feat(plan): 心愿单只写库于保存/修改保存/删除 + 会话态承载规划期心愿

用户拍板「WISH LIST SHOULD BE SAVED INTO DATABASE ONLY WHEN NEW TRIP IS
SAVED, OR CHANGES ARE SAVED, OR DELETION IS MADE. IT SHOULD NOT BE COPIED OR
CACHED OR PUT ANYWHERE LOCALLY」的 plan.py 侧收口（USER ID 键、迁移
w12_0035/0036、trip_items release/dedupe 已在库）：

- PlanSession.wish_sources：规划期心愿只记会话（来源/备注/城市/是否撤掉），
  不建行、不复制、不缓存；_record_link_sites / sync_wishes_to_trip_items /
  _finalize_wish_cities / _answer_wish_city / sync_removals_to_trip_items
  全部改写成「只写会话」（avoid_sites 记排除、site_cities 记城市）。
- materialize_wish_rows + commit_wish_drafts：保存行程的时刻按最终排期一次
  物化（排上的翻已排期并带日期时刻、没排上的落心愿单、城市不在行程的落
  无行程行、dropped 落 unwanted、avoid_sites 打 EXCLUSION）。
- sync_trip_rows / _sync_wish_rows / _sync_planned_rows 加 at_save 闸：
  规划回合内一律 no-op，看板保持「最后一次保存」的状态。
- _sync_planned_rows 的已排期选择不再要求 item.poi_id（用户点名的条目也要
  能翻已排期）。
- _wish_draft_session 恒 None（草稿口径由保存物化取代）。

门禁：test_wish_draft_lifecycle + test_planned_rows_sync + test_trip_items
= 81 绿；双口 FullSmoke PASS；真机三连（规划期看板空 → 保存进已排期 →
删行程退回心愿单）全过。
"""
io.open(r"D:\CHINATRIP\tmp_probe\_msg2.txt", "w", encoding="utf-8", newline="\n").write(msg)
print("ok")
