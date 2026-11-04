@echo off
rem Ensure the PRODUCTION database is reachable and verified.
rem
rem Production DB = Docker container chinatripcodes-db-1 (postgis 16, volume
rem chinatripcodes_pgdata), reached from Windows via localhost:5432.
rem The native PostgreSQL 18 inside WSL is a pre-migration stale snapshot
rem (2026-11-04 incident: after Docker Desktop died it auto-started, grabbed
rem port 5432 and H5/daily jobs silently served 10-29 data -- it is now
rem systemctl-disabled; do not rely on it).
rem
rem Steps: 1) start Docker Desktop if engine is down (wait ~90s)
rem        2) docker start the db container (no-op if already running)
rem        3) ops/db_fingerprint.py verifies instance identity by pois count;
rem           stale snapshot / unreachable => CRITICAL log, rc!=0.
rem           (Existing callers ignore rc, but the log line must be loud.)
rem
rem NOTE: no goto/labels inside parenthesized blocks -- cmd cannot parse
rem that ("89 was unexpected at this time" style errors). Flat flow only.
docker ps >nul 2>&1
if not errorlevel 1 goto :engineup
if exist "D:\Docker Desktop\Docker Desktop.exe" start "" "D:\Docker Desktop\Docker Desktop.exe"
set /a DBUP_J=0
:waitengine
timeout /t 5 /nobreak >nul
docker ps >nul 2>&1
if not errorlevel 1 goto :engineup
set /a DBUP_J+=1
if %DBUP_J% lss 18 goto :waitengine
echo [%date% %time%] WARN: docker engine not ready after %DBUP_J% tries >> "%DB_LOGFILE%"
:engineup
docker start chinatripcodes-db-1 >nul 2>&1
if not defined DB_LOGFILE set "DB_LOGFILE=%TEMP%\db_up.log"
set "DBUP_PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%DBUP_PY%" goto :nofp
"%DBUP_PY%" "%~dp0db_fingerprint.py" >> "%DB_LOGFILE%" 2>&1
exit /b %errorlevel%
:nofp
echo [%date% %time%] WARN: db_up: venv python missing, fingerprint skipped >> "%DB_LOGFILE%"
exit /b 0
