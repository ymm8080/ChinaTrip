@echo off
rem ChinaTrip 8000 dev server manager (zombie-proof hot reload)
rem   dev_server.cmd              -> managed watch mode (Ctrl+C to stop)
rem   dev_server.cmd start        -> detached single-process server
rem   dev_server.cmd restart|stop|status
set ROOT=%~dp0
"%ROOT%CHINATRIP CODES\.venv\Scripts\python.exe" "%ROOT%scripts\dev_watch.py" %*
