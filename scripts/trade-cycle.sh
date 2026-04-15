#!/bin/bash
set -e

# WSL trade cycle runner for tomokx.
# Syncs latest scripts from Windows-mounted Git repo before each execution.

WIN_REPO="/mnt/d/02_project/00-部门建设/07-部门任务2026/tomokx"
WSL_WORKSPACE="$HOME/.openclaw/workspace"
SCRIPT_DIR="$WSL_WORKSPACE/scripts"

# Auto-sync latest scripts from Windows repo
mkdir -p "$SCRIPT_DIR"
cp -r "$WIN_REPO/scripts-openclaw/"* "$SCRIPT_DIR/"
cp "$WIN_REPO/run_trade_cycle.py" "$SCRIPT_DIR/"
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

# Ensure log directory exists
mkdir -p "$WSL_WORKSPACE/logs/trading"

# Source trading env
cd "$WSL_WORKSPACE"
source .env.trading

LOG_FILE="$WSL_WORKSPACE/logs/trading/cycle_$(date +%Y%m%d).log"

echo "===== $(date -Iseconds) Trade Cycle Start =====" >> "$LOG_FILE"
python3 "$SCRIPT_DIR/run_trade_cycle.py" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "===== $(date -Iseconds) Trade Cycle End (exit=$EXIT_CODE) =====" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

exit $EXIT_CODE
