@echo off
rem POIS DATASOURCE gap-fill: national scenic areas (04) + 5A/UNESCO/reservation
rem list gaps (02/08/09). Idempotent: variant pre-check skips covered names,
rem only truly missing skeleton rows are appended (never overwrites).
rem Re-run after each new list batch or refresh of DESIGN/POIS DATASOURCE/.
rem Log: devlogs\pois_datasource_gaps.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\pois_datasource_gaps.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === pois datasource gaps import start === >> "%LOG%"
for %%D in (scenic 5a unesco reservation) do (
  echo [%date% %time%] --- dataset %%D --- >> "%LOG%"
  "%PY%" -m app.jobs.import_scenic_areas --dataset %%D >> "%LOG%" 2>&1
)
echo [%date% %time%] === pois datasource gaps import done === >> "%LOG%"
