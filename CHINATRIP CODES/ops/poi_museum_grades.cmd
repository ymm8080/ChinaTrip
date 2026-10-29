@echo off
rem Museum grade lists (national first/second/third-grade museums).
rem Grading runs ~every 3 years; downgrades/promotions come as ad-hoc
rem announcements (China Museum Association). Re-run after each one.
rem Idempotent: only appends missing skeleton rows, never overwrites.
rem Log: devlogs\poi_museum_grades.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_museum_grades.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === museum grades import start === >> "%LOG%"
"%PY%" -m app.jobs.import_museum_grades --csv data\museum_grades.csv >> "%LOG%" 2>&1
echo [%date% %time%] === museum grades import done === >> "%LOG%"
