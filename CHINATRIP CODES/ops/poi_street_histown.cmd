@echo off
rem Street/histown grade lists: national tourism & leisure streets (first
rem batch 2022) and China historic & cultural towns (first batch 2003).
rem Only batch-1 rows are in data\streets.csv / data\hist_towns.csv; later
rem batches get appended to the CSVs when adopted, then re-run.
rem Idempotent: only appends missing skeleton rows, never overwrites.
rem DB: WSL postgres via ops\db_up.cmd -- NEVER `docker compose up db`
rem (the docker postgis container hijacks port 5432 with an empty shadow DB).
rem Log: devlogs\poi_street_histown.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_street_histown.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === street/histown import start === >> "%LOG%"
"%PY%" -m app.jobs.import_museum_grades --csv data\streets.csv >> "%LOG%" 2>&1
"%PY%" -m app.jobs.import_museum_grades --csv data\hist_towns.csv >> "%LOG%" 2>&1
echo [%date% %time%] === street/histown import done === >> "%LOG%"
