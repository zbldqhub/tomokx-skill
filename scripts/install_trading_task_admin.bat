@echo off
:: Right-click -> Run as administrator
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_trading_task.ps1" -IntervalHours 4
pause
