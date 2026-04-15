#!/bin/bash
set -e

# Openclaw trigger wrapper for WSL.
# This script syncs the latest code and then triggers openclaw to execute
# the tomokx-trading-check skill. You MUST fill in the actual openclaw trigger command.

WIN_REPO="/mnt/d/02_project/00-部门建设/07-部门任务2026/tomokx"
WSL_WORKSPACE="$HOME/.openclaw/workspace"
SCRIPT_DIR="$WSL_WORKSPACE/scripts"

# 1. Sync latest scripts from Windows repo
mkdir -p "$SCRIPT_DIR"
mkdir -p "$WSL_WORKSPACE/logs/trading"
cp -r "$WIN_REPO/scripts-openclaw/"* "$SCRIPT_DIR/"
cp "$WIN_REPO/run_trade_cycle.py" "$SCRIPT_DIR/"
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

# 2. Source trading env
cd "$WSL_WORKSPACE"
source .env.trading

# 3. Trigger openclaw to execute tomokx-trading-check
#    ↓↓↓ REPLACE THE LINE BELOW WITH YOUR ACTUAL OPENCLAW TRIGGER COMMAND ↓↓↓
#    Common patterns:
#    - openclaw trigger tomokx-trading-check
#    - python3 /path/to/openclaw/cli.py --skill tomokx-openclaw --event tomokx-trading-check
#    - curl -X POST http://localhost:8080/event -d '{"type":"tomokx-trading-check"}'

echo "[$(date -Iseconds)] Scripts synced. Waiting for openclaw trigger command to be configured."
# openclaw trigger tomokx-trading-check
