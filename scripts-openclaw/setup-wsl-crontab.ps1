# One-click deploy tomokx scheduler into WSL from Windows side.
# Run this in PowerShell (no admin required).

$ErrorActionPreference = "Stop"

$wslScript = "/mnt/d/02_project/00-部门建设/07-部门任务2026/tomokx/scripts-openclaw/setup-wsl.sh"

# Robustly detect available WSL distros, skipping docker-desktop
$raw = wsl -l --quiet 2>&1
$distros = @()
foreach ($line in $raw) {
    $name = $line.Trim() -replace "^\*\s*",""
    if ($name -and ($name -notmatch "(?i)docker")) {
        $distros += $name
    }
}

$targetDistro = $distros | Select-Object -First 1

if (-not $targetDistro) {
    Write-Host "ERROR: No suitable Linux WSL distro found. 'wsl -l --quiet' output:" -ForegroundColor Red
    foreach ($line in $raw) { Write-Host "  [$line]" -ForegroundColor DarkGray }
    exit 1
}

Write-Host "==> Detected WSL distro: $targetDistro" -ForegroundColor Cyan
Write-Host "==> Deploying tomokx scheduler into WSL ($targetDistro)..." -ForegroundColor Cyan

# Run deployment inside the chosen distro
wsl -d $targetDistro bash "$wslScript"

Write-Host "`n==> Deployment complete." -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "   1. Ensure WSL cron is running:" -ForegroundColor Yellow
Write-Host "      wsl -d $targetDistro sudo service cron start" -ForegroundColor Cyan
Write-Host "   2. (Optional) Enable systemd for persistent cron:" -ForegroundColor Yellow
Write-Host "      wsl -d $targetDistro sudo systemctl enable cron --now" -ForegroundColor Cyan
Write-Host "   3. Test a manual cycle:" -ForegroundColor Yellow
Write-Host "      wsl -d $targetDistro bash /root/.openclaw/workspace/scripts/trade-cycle.sh" -ForegroundColor Cyan
Write-Host "   4. View live logs:" -ForegroundColor Yellow
Write-Host "      wsl -d $targetDistro tail -f /root/.openclaw/workspace/logs/trading/cycle_`$(date +\%Y\%m\%d).log" -ForegroundColor Cyan
Write-Host "`nTIP: To avoid typing '-d $targetDistro' every time, set it as default:" -ForegroundColor Magenta
Write-Host "   wsl --set-default $targetDistro" -ForegroundColor Magenta
