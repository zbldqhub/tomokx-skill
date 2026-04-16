# tomokx 全自动定时 Workflow

本文件定义 tomokx 在 Windows / Linux 环境下无人值守自动运行的部署方式。
策略规则参见 `skills/tomokx/SKILL.md`。

---

## 核心入口

全自动模式直接调用 `run_trade_cycle.py`，它内部会串行执行：

1. `fetch_all_data.py`
2. `calc_recommendation.py`
3. `calc_plan.py`
4. `ai_review.py`（自动检测 openclaw gateway → fallback 到本地 `kimi.exe`）
5. `execute_and_finalize.py`

```powershell
python "$env:USERPROFILE\.openclaw\workspace\run_trade_cycle.py"
```

> 注意：`run_trade_cycle.py` 仅在全自动模式下使用。手动执行时 AI 必须遵循 `workflows/tomokx-manual.md` 的逐步协议。

---

## Windows · 任务计划程序

### 安装定时任务

右键以管理员身份运行：

```powershell
# 每 4 小时执行一次
"$env:USERPROFILE\.openclaw\workspace\scripts\install_trading_task_admin.bat"
```

或直接通过管理员 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File `
  "$env:USERPROFILE\.openclaw\workspace\scripts\install_trading_task.ps1" -IntervalHours 4
```

### 立即测试

```powershell
Start-ScheduledTask -TaskName "tomokx-auto-trading-ai"
```

### 查看日志

```powershell
Get-ChildItem "$env:USERPROFILE\.openclaw\workspace\logs\trading" `
  | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content
```

### 卸载定时任务

```powershell
powershell -ExecutionPolicy Bypass -File `
  "$env:USERPROFILE\.openclaw\workspace\scripts\uninstall_trading_task.ps1"
```

---

## Linux / openclaw · crontab

WSL 或 Linux 服务器使用 `scripts-openclaw/trade-cycle.sh`：

```bash
# 编辑 crontab
crontab -e

# 每 30 分钟执行一次
*/30 * * * * bash ~/.openclaw/workspace/scripts/trade-cycle.sh
```

`trade-cycle.sh` 会先从 Git 仓库同步最新脚本，再执行 `run_trade_cycle.py`。

---

## 故障排查

### 定时任务不执行
- Windows：检查任务计划程序中 `tomokx-auto-trading-ai` 的状态和上次运行时间
- Linux：检查 `~/.openclaw/workspace/logs/trading/` 下的日志文件

### AI 审核未触发
- 确认 `kimi.exe` 路径正确：`~/AppData/Roaming/Code/User/globalStorage/moonshot-ai.kimi-code/bin/kimi/kimi.exe`
- `ai_review.py` 会自动 fallback，无需 openclaw gateway 常驻

### 网络/SSL 错误
- 若使用 Clash/V2Ray，确保代理环境变量已设置
- 或运行 `node ~/.openclaw/workspace/scripts/patch-okx-cli.js` 修复 OKX CLI TLS
