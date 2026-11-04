# Returns exit 1 when an enrich_llm_web process is already running (skip this round).
$procs = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match 'app\.jobs\.enrich_llm_web' }
if ($procs) { exit 1 } else { exit 0 }
