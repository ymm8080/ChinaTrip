@echo off
rem 17 馆预约规则每周全量核对（用户拍板 2026-10-25：每周日晚上跑）
rem zhipu web_search 逐馆核对官方口径 → 快照 JSON + diff 报告 + 表行刷新
rem 计划任务：ChinaTrip_reservation_rules_weekly（周日 21:00）
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\reservation_rules_weekly.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === reservation rules weekly start === >> "%LOG%"
"%PY%" -m app.jobs.refresh_reservation_rules --with-visa >> "%LOG%" 2>&1
echo [%date% %time%] === reservation rules weekly done === >> "%LOG%"
