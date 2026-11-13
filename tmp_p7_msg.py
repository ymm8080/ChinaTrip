msg = """refactor(trip): 明细重建抽成 rewrite_trip_detail + 存量回填脚本

- trip_changes.rewrite_trip_detail(session, uid, plan)：保存与回填共用一个
  实现（天 + 点位含备选 1-3），避免两份口径漂移
- ops/backfill_trip_detail.py：把存量行程的头派生列与明细写进库（不写
  change log —— 那不是用户点保存）；已实跑回填 7 条行程
- 修重构时 new_plan/plan 变量笔误
"""
open(r"D:\tmp_ct_push7_msg.txt", "w", encoding="utf-8", newline="\n").write(msg)
print("ok")
