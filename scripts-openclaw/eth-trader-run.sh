#!/usr/bin/env bash
# eth-trader-run.sh - Wrapper script for heartbeat execution (openclaw)
# Ensures env is sourced and API creds are available for okx CLI

set -euo pipefail

# Source environment
source "${HOME}/.openclaw/workspace/.env.trading"

# API connectivity check with retry
API_OK=0
for i in 1 2 3; do
    if curl -s --max-time 15 \
        "https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP" 2>/dev/null | grep -q '"last":"'; then
        API_OK=1
        break
    fi
    sleep 2
done

if [ "$API_OK" -ne 1 ]; then
    echo "⚠️ API 连接检查失败，无法连接 OKX API"
    exit 1
fi

# The actual trading logic is agent-native; this script is a minimal env-wrapper
# for heartbeat to call via exec if needed. For agent-native execution, the agent
# sources .env.trading before each okx command block.
echo "✅ ETH Trader 环境已就绪，API 正常"
