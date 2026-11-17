@echo off
REM ============================================================
REM  ChinaTrip manual backfill trigger (2026-11-12 v3, ASCII only)
REM  Usage: manual_trigger.cmd [limit]   default 600
REM  Manual harvest entry besides the 03:55 daily batch:
REM  ctrip detail batch (curated priority group first) + gap delta.
REM  Gate blocks only map-channel enrichers (ctrip/baidu/amap);
REM  enrich_llm_web (GLM alias round) does NOT block.
REM ============================================================
setlocal
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set LIMIT=%1
if "%LIMIT%"=="" set LIMIT=600
set LOG=ops\manual_trigger_last.log

echo [manual_trigger] %date% %time%  limit=%LIMIT% > "%LOG%"
echo [1/4] process gate (ctrip_detail/baidu_map/amap_detail only) >> "%LOG%"
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'enrich_(ctrip_detail|baidu_map|amap_detail)' }; if ($p) { $p | ForEach-Object { Write-Host ('  BUSY: ' + $_.CommandLine.Substring(0,[Math]::Min(120,$_.CommandLine.Length))) }; exit 1 } else { Write-Host '  idle'; exit 0 }" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [GATE] map-channel enricher in flight, skip this run. See %LOG%
  type "%LOG%"
  pause
  exit /b 1
)

echo [2/4] gaps before >> "%LOG%"
.venv\Scripts\python.exe -I -c "import sys; sys.path.insert(0,'.'); from sqlalchemy import func,select; from app.db import get_session_factory; from app.models import Poi; sf=get_session_factory(); s=sf(); print('curated missing ticket=', s.scalar(select(func.count()).select_from(Poi).where(Poi.source=='curated',Poi.status=='active',Poi.ticket_price_min.is_(None))), ' missing rating=', s.scalar(select(func.count()).select_from(Poi).where(Poi.source=='curated',Poi.status=='active',Poi.rating.is_(None))))" >> "%LOG%" 2>&1

echo [3/4] ctrip harvest %LIMIT% rows >> "%LOG%"
.venv\Scripts\python.exe -I -c "import sys; sys.path.insert(0,'.'); from app.jobs.enrich_ctrip_detail import main; sys.argv=['enrich_ctrip_detail','--limit','%LIMIT%','--concurrency','2']; main()" >> "%LOG%" 2>&1

echo [4/4] gaps after >> "%LOG%"
.venv\Scripts\python.exe -I -c "import sys; sys.path.insert(0,'.'); from sqlalchemy import func,select; from app.db import get_session_factory; from app.models import Poi; sf=get_session_factory(); s=sf(); print('curated missing ticket=', s.scalar(select(func.count()).select_from(Poi).where(Poi.source=='curated',Poi.status=='active',Poi.ticket_price_min.is_(None))), ' missing rating=', s.scalar(select(func.count()).select_from(Poi).where(Poi.source=='curated',Poi.status=='active',Poi.rating.is_(None))))" >> "%LOG%" 2>&1

echo [manual_trigger] done >> "%LOG%"
type "%LOG%"
echo.
echo Log: %CD%\%LOG%
pause
