@echo off
rem Michelin monthly check (7th, 04:00). Upstream mirror publishes days 2-5
rem most months, so day 7 rarely misses a new list. Union tagging;
rem unmatched entries in covered cities are appended as skeleton rows.
rem Download via ops\fetch_url.py (urllib) - curl.exe hangs in cmd/schtasks
rem context on CN network (2026-10-24 live incident).
rem Log: devlogs\poi_monthly.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_monthly.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === poi monthly start === >> "%LOG%"

rem ngshiheng/michelin-my-maps monthly CSV lives in repo data/ dir; raw host
rem often blocked on CN network - codeload tarball works, extract via bsdtar -O
set "MICH_TGZ=data\michelin_repo.tgz"
set "MICH_URL=https://codeload.github.com/ngshiheng/michelin-my-maps/tar.gz/refs/heads/main"
"%PY%" "%~dp0fetch_url.py" "%MICH_URL%" "%MICH_TGZ%" 300 >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] michelin csv download FAILED >> "%LOG%"
) else (
  tar -xzf "%MICH_TGZ%" -O michelin-my-maps-main/data/michelin_my_maps.csv > data\michelin.csv 2>> "%LOG%"
  del /q "%MICH_TGZ%" >nul 2>&1
  rem tag matched rows; append missing as skeleton rows (city-gated, WGS84 to GCJ02)
  "%PY%" -m app.jobs.tag_quality --csv data\michelin.csv --kind michelin >> "%LOG%" 2>&1
)

rem Black Pearl moved to poi_blackpearl.cmd (2nd monthly, staggered)
echo [%date% %time%] === poi monthly done === >> "%LOG%"
