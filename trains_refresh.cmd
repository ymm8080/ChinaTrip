@echo off
rem Daily train schedule cache refresh (chinatrip PR#9 train_cache).
rem Runs python -m app.jobs.refresh_trains from the repo dir so the
rem relative sqlite path data/train_cache.db resolves consistently.
cd /d "D:\chinatrip\CHINATRIP CODES"
C:\Users\91454\AppData\Local\Programs\Python\Python312\python.exe -m app.jobs.refresh_trains >> D:\chinatrip\trains_refresh.log 2>&1
