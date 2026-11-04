@echo off
rem Daily alias/duration LLM+web enrich driver (resumable relay).
rem Only fills empty cells (name_aliases IS NULL / duration heuristic floor);
rem targets the highest-rated rows first. Guarded: if another
rem enrich_llm_web process is already running, skip this round so the
rem shared GLM account (also serves the live planner) never gets doubled.
rem Log: devlogs\poi_alias_llm.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\poi_alias_llm.log"
if not exist devlogs mkdir devlogs
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0poi_alias_llm_guard.ps1"
if errorlevel 1 (
  echo [%date% %time%] skip: enrich_llm_web already running >> "%LOG%"
  exit /b 0
)
call "%~dp0db_up.cmd"
echo [%date% %time%] === alias llm start === >> "%LOG%"
"%PY%" -m app.jobs.enrich_llm_web --limit 1000 --concurrency 2 >> "%LOG%" 2>&1
echo [%date% %time%] === alias llm done rc=%errorlevel% === >> "%LOG%"
