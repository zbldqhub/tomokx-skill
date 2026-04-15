#!/bin/bash
set -e

# Sync latest tomokx scripts from Windows Git repo to WSL workspace.
# Call this before openclaw executes the skill (e.g. in HEARTBEAT Step 0).

WIN_REPO="/mnt/d/02_project/00-部门建设/07-部门任务2026/tomokx"
WSL_WORKSPACE="$HOME/.openclaw/workspace"
SCRIPT_DIR="$WSL_WORKSPACE/scripts"

mkdir -p "$SCRIPT_DIR"
mkdir -p "$WSL_WORKSPACE/logs/trading"

cp -r "$WIN_REPO/scripts-openclaw/"* "$SCRIPT_DIR/"
cp "$WIN_REPO/run_trade_cycle.py" "$SCRIPT_DIR/"
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

echo "Scripts synced from $WIN_REPO to $SCRIPT_DIR"
