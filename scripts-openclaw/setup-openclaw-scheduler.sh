#!/bin/bash
set -e

# Deploy ONLY the P3 trailing stop cron job.
# The main trading cycle is handled by openclaw itself via heartbeat/skill.
# Run this inside WSL (e.g. wsl -d Ubuntu bash /mnt/d/.../scripts-openclaw/setup-openclaw-scheduler.sh)

WIN_REPO="/mnt/d/02_project/00-部门建设/07-部门任务2026/tomokx"
WSL_WORKSPACE="$HOME/.openclaw/workspace"
SCRIPT_DIR="$WSL_WORKSPACE/scripts"

echo "==> Creating WSL workspace directories..."
mkdir -p "$SCRIPT_DIR"
mkdir -p "$WSL_WORKSPACE/logs/trading"

echo "==> Syncing scripts from Windows repo ($WIN_REPO)..."
cp -r "$WIN_REPO/scripts-openclaw/"* "$SCRIPT_DIR/"
cp "$WIN_REPO/run_trade_cycle.py" "$SCRIPT_DIR/"
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

echo "==> Installing crontab (P3 trailing stop only)..."

# Remove old tomokx crontab entries if any
crontab -l 2>/dev/null | grep -v "TomoKX" | grep -v "trailing_stop_manager" | grep -v "trade-cycle.sh" | grep -v "trigger-openclaw" > /tmp/crontab.bak || true

cat > /tmp/tomokx-crontab << EOF
# TomoKX WSL Scheduler
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# P3: Trailing stop / breakeven check every 5 minutes
*/5 * * * * cd $WSL_WORKSPACE && source .env.trading && python3 scripts/trailing_stop_manager.py >> logs/trading/trailing_stop_\$(date +\%Y\%m\%d).log 2>&1
EOF

# Merge and install
cat /tmp/crontab.bak /tmp/tomokx-crontab | crontab -

echo "==> Crontab installed. Current jobs:"
crontab -l

echo ""
echo "==> IMPORTANT: Make sure the cron service is running inside WSL."
echo "   Quick start:  sudo service cron start"
echo "   Enable systemd (recommended):"
echo "      sudo systemctl enable cron --now"
echo ""
echo "==> Next step: configure openclaw's main trading cycle trigger."
echo "   Edit: $SCRIPT_DIR/trigger-openclaw.sh"
echo "   Replace the placeholder with your actual openclaw trigger command."
echo ""
echo "   If openclaw can be triggered via cron, add this line to crontab:"
echo "      */20 * * * * bash $SCRIPT_DIR/trigger-openclaw.sh >> $WSL_WORKSPACE/logs/trading/openclaw_trigger_\$(date +\%Y\%m\%d).log 2>&1"
