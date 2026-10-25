@echo off
rem poi_stats 夜聚合（DESIGN §3.4 D2）：trip_items 行为 + 反馈计数 → poi_stats 全量重建
rem 时机：每日 03:40（refresh 02:00 城轮转后、避开整点）——幂等可重跑
rem 日志: devlogs\poi_stats_nightly.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\poi_stats_nightly.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === poi stats aggregate start === >> "%LOG%"
"%PY%" -m app.jobs.aggregate_poi_stats >> "%LOG%" 2>&1
echo [%date% %time%] === poi stats aggregate done === >> "%LOG%"
