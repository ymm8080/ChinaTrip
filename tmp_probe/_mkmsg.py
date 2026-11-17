import io
msg = """feat(plan): 心愿单只在保存/删除时进数据库 + USER ID 归属键 + 删行程退回心愿单（2026-11-15）

用户拍板三连收口：
1. 心愿单只在「保存新行程 / 保存修改 / 删除」三个时刻写数据库；规划期间
   不落库、不复制、不缓存——愿望记在会话（wish_sources/must_visits/
   avoid_sites/绑定），保存时 materialize_wish_rows 按最终排期一次性物化，
   sync_trip_rows(at_save=True) 对账（翻已排期/回心愿单/去重）。
2. USER ID 归属键：trip_items/itinerary_items/action_handoffs 加
   owner_account_id（登录账号，迁移 w12_0036，存量 JOIN 行程头回填）；
   打开行程中心按设备或账号出本用户内容，换设备登录同看一眼。
3. 删行程=名下心愿行 TRIP ID 清空退回心愿单（不再删除/重建）；会话草稿
   行释放转正；booked 真实订单只解绑。

配套：trip_items 加 draft_session_id（w12_0035，过渡口径，存量已软删
retire）；看板读口 include_drafts=False + Cache-Control: no-store + SW 对
trip-items 直连网络不缓存；_sync_wish_rows/_sync_planned_rows 去重与认领闸；
保存收编孤儿心愿行；predates 的 draft 行已 retire（备份在 DESIGN/backup）。

门禁：trip_items/wish_draft_lifecycle/planned_rows_sync/pg_state/state_persist
104 绿；plan_api 72 绿+5 基线红（move×2/refresh/get_session/fallback 150→120
并行在途）；plan_agent 128 绿+2 基线红；ruff 绿；双口 FullSmoke PASS；
真机三连（规划期不落库→保存物化进已排期→删行程退回心愿单）全过。
"""
io.open(r"D:\CHINATRIP\tmp_probe\_commit_msg.txt", "w", encoding="utf-8", newline="\n").write(msg)
print("msg ok")
