$existing = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*enrich_llm_web*' }
if ($existing) { exit 0 }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$log = "D:\CHINATRIP\CHINATRIP CODES\ops\enrich_llm_web_wd_$stamp.log"
Start-Process -FilePath "D:\CHINATRIP\CHINATRIP CODES\.venv\Scripts\python.exe" -ArgumentList '-m','app.jobs.enrich_llm_web','--limit','5000','--concurrency','2' -WorkingDirectory "D:\CHINATRIP\CHINATRIP CODES" -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "$log.err"
