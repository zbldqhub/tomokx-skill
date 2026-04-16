#!/usr/bin/env pwsh
# Uninstall the tomokx auto-trading scheduled task.
param(
    [string]$TaskName = "tomokx-auto-trading-ai"
)

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "✅ Scheduled task '$TaskName' has been uninstalled."
} else {
    Write-Host "⚠️ Task '$TaskName' not found. Nothing to uninstall."
}
