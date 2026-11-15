@echo off
rem ===== Night photos driver wrapper (every 5 min schtask) =====
rem Runs ops/night_photos_driver.py; on exit code 3 (complete) deletes the
rem scheduled task itself. ASCII-only file.
rem Log: ops\night_photos_driver.log   Ledger: ops\p1_data_tasks_progress.md

cd /d "D:\CHINATRIP\CHINATRIP CODES"
.venv\Scripts\python.exe ops\night_photos_driver.py >> ops\night_photos_driver.log 2>&1
set RC=%ERRORLEVEL%
if "%RC%"=="3" (
  schtasks /Delete /F /TN "ChinaTrip\rest photos driver" > nul 2>&1
  echo %date% %time% driver COMPLETE - task self-deleted >> ops\night_photos_driver.log
)
exit /b %RC%
