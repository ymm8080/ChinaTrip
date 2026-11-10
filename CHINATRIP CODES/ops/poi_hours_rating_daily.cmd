@echo off
rem Daily hours/rating fill driver - two engines, each with its own daily quota:
rem   baidu place search (~100/day personal), amap v5 place/around business
rem   block (v5 text is WAF-denied since 2026-11-03; around is a separate
rem   quota/risk pool). Paced with --delay 0.5: around returns 10002 when
rem   bursted, so amap runs one request at a time with spacing.
rem Fill-empty-only + per-engine miss ledgers (fill_hours_rating_missed*.txt):
rem failed rows tried once, quota always goes to fresh rows.
rem Order: baidu first, amap second, after the 02:00 refresh daily.
rem Log: devlogs\poi_hours_rating_daily.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_hours_rating_daily.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === hours/rating daily start === >> "%LOG%"
"%PY%" ops\fill_hours_rating_driver.py --engine baidu --limit 120 --concurrency 2 >> "%LOG%" 2>&1
"%PY%" ops\fill_hours_rating_driver.py --engine amap --limit 150 --concurrency 1 --delay 0.7 >> "%LOG%" 2>&1
rem ctrip daily batch (2026-11-10: rating authority switch amap->ctrip override
rem + hours trickle; job self-locks 90min; ~600 detail pages/day within IP tolerance)
"%PY%" -m app.jobs.enrich_ctrip_detail --limit 600 >> "%LOG%" 2>&1
echo [%date% %time%] === hours/rating daily done rc=%errorlevel% === >> "%LOG%"
