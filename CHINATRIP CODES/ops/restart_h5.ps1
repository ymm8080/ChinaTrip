# restart_h5.ps1 - canonical restart for the chinatrip H5 dual-port services.
# Created 2026-11-03 after the http_500 incident: 8000 was started bare by hand
# (18:50, no log redirection) while the tree sat in a mid-merge broken state -
# every /plan message lane 500'd although /health stayed 200.
#
# Usage (from anywhere):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\CHINATRIP\CHINATRIP CODES\ops\restart_h5.ps1"
#   ... -Tests        additionally run the test_plan_api + test_plan_agent pytest gate before killing
#   ... -FullSmoke    after boot also probe a real plan/start + message turn (~1 min, one throwaway session)
#   ... -Force        allow restart although CHINATRIP CODES has modified .py files (loads UNVERIFIED code)
#
# The gates are the point:
#   * never restart a user-facing service from a mid-merge / WIP tree;
#   * never start uvicorn bare - always via schtasks so both cmds append to
#     D:\chinatrip\uvicorn_h5_1018e*.log and tracebacks land somewhere.

param(
    [switch]$Force,
    [switch]$Tests,
    [switch]$FullSmoke
)
$ErrorActionPreference = 'Stop'
$repo  = 'D:\CHINATRIP'
$codes = Join-Path $repo 'CHINATRIP CODES'
$smoke = Join-Path $codes 'ops\smoke_h5.py'
$uvPy  = 'C:\Users\91454\AppData\Local\Programs\Python\Python312\python.exe'
$tasks = @('chinatrip_h5_8000', 'chinatrip_h5_tls')
$ports = 8000, 8443

function Fail($msg) {
    Write-Host "ABORT: $msg"
    exit 1
}

# --- gate 1: no modified .py files under CHINATRIP CODES (mid-merge/WIP guard)
$sha = (git -C $repo rev-parse --short HEAD).Trim()
$dirty = git -C $repo status --porcelain |
    Where-Object { $_ -match '\.py\s*$' -and $_ -match 'CHINATRIP CODES' -and $_ -match '^ ?[MA]' }
if ($dirty) {
    Write-Host "HEAD = $sha ; modified .py files under CHINATRIP CODES:"
    $dirty | ForEach-Object { Write-Host "  $_" }
    if (-not $Force) {
        Fail 'tree has modified .py files (mid-merge/WIP?) - commit first or pass -Force'
    }
    Write-Host '-Force given: proceeding with a dirty tree (this loads UNVERIFIED code)'
}

# --- gate 2 (optional): targeted pytest before killing the running server
if ($Tests) {
    Write-Host 'pytest gate: tests/test_plan_api.py + tests/test_plan_agent.py ...'
    cmd /c 'cd /d "D:\CHINATRIP\CHINATRIP CODES"&& .venv\Scripts\python.exe -m pytest tests/test_plan_api.py tests/test_plan_agent.py -q --no-header'
    if ($LASTEXITCODE -ne 0) { Fail 'pytest gate failed' }
}

# --- kill current listeners (creation time is echoed for the audit trail)
$conns = Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in ($conns | Sort-Object LocalPort -Unique)) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        Write-Host ("killing port {0} pid {1} start {2}" -f $c.LocalPort, $c.OwningProcess, $p.StartTime)
        cmd /c ("taskkill /T /F /PID {0}" -f $c.OwningProcess) | Out-Null
    }
    Start-Sleep -Seconds 2
} else {
    Write-Host 'no current listeners on 8000/8443'
}

# --- restart through schtasks (log redirection lives in the cmd files)
foreach ($t in $tasks) {
    $r = (schtasks /run /tn $t 2>&1 | Out-String).Trim()
    Write-Host "schtasks /run ${t}: $r"
}

# --- wait for health on both ports
$up = @{}
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    foreach ($port in $ports) {
        if (-not $up.ContainsKey($port)) {
            $code = if ($port -eq 8443) {
                curl.exe -sk -m 3 -o NUL -w '%{http_code}' "https://127.0.0.1:$port/health"
            } else {
                curl.exe -s -m 3 -o NUL -w '%{http_code}' "http://127.0.0.1:$port/health"
            }
            if ("$code" -eq '200') { $up[$port] = $true; Write-Host "port $port health 200" }
        }
    }
    if ($up.Count -ge $ports.Count) { break }
    Start-Sleep -Seconds 2
}
$down = $ports | Where-Object { -not $up.ContainsKey($_) }
if ($down) { Fail "health not up for ports: $($down -join ',') - check D:\chinatrip\uvicorn_h5_1018e*.log" }

Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    Write-Host ("listening {0} pid {1} start {2}" -f $_.LocalPort, $_.OwningProcess, $p.StartTime)
}

# --- smoke
$extra = @(); if ($FullSmoke) { $extra = @('--full') }
& $uvPy $smoke --ports @($ports) @extra
if ($LASTEXITCODE -ne 0) { Fail 'smoke failed - read the traceback in D:\chinatrip\uvicorn_h5_1018e*.log' }

Write-Host "DONE restart from HEAD $sha ; smoke PASS"
