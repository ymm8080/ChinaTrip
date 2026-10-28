@echo off
rem Monthly intro drip backfill (schtasks day-1 05:10): Wikidata + api.wikimedia.org
rem Log: devlogs\poi_intro_monthly.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_intro_monthly.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === poi intro monthly start === >> "%LOG%"
rem Fill-empty only (never overwrite); full sweep of empty rows, ~6 rows/min
"%PY%" -m app.jobs.backfill_intro --limit 5000 >> "%LOG%" 2>&1
echo [%date% %time%] === poi intro monthly done === >> "%LOG%"
