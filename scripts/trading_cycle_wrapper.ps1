# tomokx trading cycle wrapper for Windows Task Scheduler
# Usage:
#   .\trading_cycle_wrapper.ps1              -> full auto cycle
#   .\trading_cycle_wrapper.ps1 -NotifyOnly  -> generate report only, no execution
param(
    [switch]$NotifyOnly
)

$ErrorActionPreference = "Stop"
$Workspace = [Environment]::GetFolderPath("UserProfile") + "\.openclaw\workspace"
$Scripts = "$Workspace\scripts"
$LogDir = "$Workspace\logs\scheduled"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = "$LogDir\cycle_$Timestamp.log"
$ReportFile = "$LogDir\latest_report.md"

# Ensure log directory exists
if (!(Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

# Change to workspace so Python imports and relative paths work
Set-Location $Workspace

if ($NotifyOnly) {
    Write-Log "MODE: Notify Only (no execution)"

    # Step 1+2: fetch data
    Write-Log "Fetching market data..."
    $data = & python "$Scripts\fetch_all_data.py" 2>&1
    $fetch = $data | Out-String
    Add-Content -Path $LogFile -Value $fetch -Encoding UTF8

    # Parse JSON from last line that starts with {
    $jsonLine = $data | Where-Object { $_.Trim().StartsWith("{") } | Select-Object -Last 1
    $marketState = @{}
    if ($jsonLine) {
        try {
            $parsed = $jsonLine | ConvertFrom-Json
            $m = $parsed.market
            $s = $parsed.strategy
            $r = $parsed.risk
            $e = $parsed.exposure
            $marketState = @{
                Price = $m.last
                Trend = $s.trend
                Alignment = $s.trend_alignment
                Gap = $s.adjusted_gap
                Total = $e.total
                DailyPnL = $r.daily_pnl
                ShouldStop = $r.should_stop
            }
        } catch {
            Write-Log "WARN: failed to parse market JSON: $_"
        }
    }

    # Build report
    $report = @"
# tomokx 交易提醒 - $(Get-Date -Format "yyyy-MM-dd HH:mm")

- **价格**: $($marketState.Price)
- **趋势**: $($marketState.Trend) ($($marketState.Alignment))
- **Gap**: $($marketState.Gap)
- **总暴露**: $($marketState.Total) / 30
- **今日盈亏**: $($marketState.DailyPnL) USDT
- **风控停止**: $($marketState.ShouldStop)

$(if ($marketState.ShouldStop -eq $true) { "`n**⚠️ 风控已触发，今日停止交易！**`n" } else { "`n**请手动执行一次交易 cycle。**`n`n右键 PowerShell 运行：`n```powershell`npython $Scripts\..\run_trade_cycle.py`n```" })

详细日志: $LogFile
"@

    $report | Out-File -FilePath $ReportFile -Encoding utf8
    Write-Log "Report written to $ReportFile"

    # Try Windows toast notification via BurntToast, fallback to simple message
    try {
        Import-Module BurntToast -ErrorAction Stop
        $title = "tomokx 交易提醒"
        $msg = "价格: $($marketState.Price), 趋势: $($marketState.Trend), 今日盈亏: $($marketState.DailyPnL) USDT"
        New-BurntToastNotification -Text $title, $msg -AppLogo ""
        Write-Log "Toast notification sent."
    } catch {
        Write-Log "Toast notification skipped (BurntToast not installed)."
        # Fallback: write a Desktop shortcut text
        $desktop = [Environment]::GetFolderPath("Desktop")
        Copy-Item -Path $ReportFile -Destination "$desktop\tomokx_alert_$Timestamp.md" -Force | Out-Null
        Write-Log "Alert copied to Desktop: $desktop\tomokx_alert_$Timestamp.md"
    }

} else {
    Write-Log "MODE: Full Auto Cycle"
    & python "$Scripts\..\run_trade_cycle.py" 2>&1 | Tee-Object -FilePath $LogFile -Append
    Write-Log "Cycle finished. Log: $LogFile"
}
