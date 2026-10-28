$ErrorActionPreference = 'Stop'

function New-SrvTask($name, $scriptPath) {
  $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c ' + $scriptPath) -WorkingDirectory 'D:\chinatrip'
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
  Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
}

New-SrvTask 'chinatrip_h5_8000' 'D:\chinatrip\run_h5_server.cmd'
New-SrvTask 'chinatrip_h5_tls' 'D:\chinatrip\run_h5_server_tls.cmd'

$ka = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c D:\chinatrip\h5_keepalive.cmd' -WorkingDirectory 'D:\chinatrip'
$kaTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::FromDays(3650))
$kaSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::New(0, 2, 0))
Register-ScheduledTask -TaskName 'chinatrip_h5_keepalive' -Action $ka -Trigger $kaTrigger -Settings $kaSettings -Force | Out-Null

Start-ScheduledTask -TaskName 'chinatrip_h5_8000'
Start-ScheduledTask -TaskName 'chinatrip_h5_tls'
Write-Output 'REGISTERED_AND_STARTED'
