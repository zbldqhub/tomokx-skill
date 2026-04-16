#!/usr/bin/env pwsh
# Install Windows Scheduled Task for fully-automated tomokx trading with AI review.
param(
    [string]$IntervalHours = 4,
    [string]$TaskName = "tomokx-auto-trading-ai"
)

$Workspace = [Environment]::GetFolderPath("UserProfile") + "\.openclaw\workspace"
$PythonExe = (Get-Command python).Source
$ScriptPath = "$Workspace\run_trade_cycle.py"
$LogDir = "$Workspace\logs\trading"
$BatPath = "$Workspace\scripts\_trading_cycle_runner.bat"

if (!(Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Create a simple .bat wrapper so Task Scheduler doesn't need complex quoting
$timestampExpr = "%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%"
$batContent = @"
@echo off
setlocal
set "WORKSPACE=$Workspace"
set "PYTHON=$PythonExe"
set "SCRIPT=$ScriptPath"
set "LOGDIR=$LogDir"
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-3 delims=: " %%a in ('time /t') do (set mytime=%%a%%b%%c)
set "LOG=%LOGDIR%\cycle_%mydate%_%mytime%.log"
powershell -NoProfile -Command "& { cd '%WORKSPACE%'; & '%PYTHON%' '%SCRIPT%' }" > "%LOG%" 2>&1
"@
$batContent | Out-File -FilePath $BatPath -Encoding ASCII

$Action = New-ScheduledTaskAction -Execute $BatPath
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
    Write-Host "✅ Scheduled task '$TaskName' installed successfully."
    Write-Host "   Runner: $BatPath"
    Write-Host "   Script: $ScriptPath"
    Write-Host "   Logs:   $LogDir"
    Write-Host "   Frequency: every $IntervalHours hours"
    Write-Host ""
    Write-Host "To test immediately: Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "To uninstall:        powershell -File `"$Workspace\scripts\uninstall_trading_task.ps1`""
} catch {
    Write-Host "❌ Failed to install scheduled task. Error: $_"
    Write-Host ""
    Write-Host "👉 This script requires Administrator privileges."
    Write-Host "   Please right-click 'install_trading_task_admin.bat' and select 'Run as administrator'."
    exit 1
}
