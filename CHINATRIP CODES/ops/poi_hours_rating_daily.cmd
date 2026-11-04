@echo off
rem Daily hours/rating fill driver - two engines, each with its own daily quota:
rem   baidu place search (~100/day personal), amap v5 text business block
rem   (~166/day from the shared 5k/month search pool; quota/WAF stops clean).
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
"%PY%" ops\fill_hours_rating_driver.py --engine amap --limit 150 --concurrency 2 >> "%LOG%" 2>&1
echo [%date% %time%] === hours/rating daily done rc=%errorlevel% === >> "%LOG%"
