@echo off
rem Daily hours/rating fill driver (baidu place search, ~100/day personal quota).
rem Fill-empty-only + miss ledger (ops/fill_hours_rating_missed.txt): failed rows
rem tried once, quota always goes to fresh rows. Quota error stops the round.
rem Log: devlogs\poi_hours_rating_daily.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_hours_rating_daily.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === hours/rating daily start === >> "%LOG%"
"%PY%" ops\fill_hours_rating_driver.py --limit 120 --concurrency 2 >> "%LOG%" 2>&1
echo [%date% %time%] === hours/rating daily done rc=%errorlevel% === >> "%LOG%"
