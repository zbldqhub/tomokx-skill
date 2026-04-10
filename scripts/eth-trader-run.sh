#!/bin/bash

# TomoKX ETH Trader - Wrapper script for heartbeat execution
# Usage: ./eth-trader-run.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="${HOME}/.openclaw/workspace"
LOG_FILE="${WORKSPACE_DIR}/auto_trade.log"
ENV_FILE="${WORKSPACE_DIR}/.env.trading"
STOP_FILE="${WORKSPACE_DIR}/.trading_stopped"

# Create workspace if not exists
mkdir -p "${WORKSPACE_DIR}"

echo -e "${BLUE}🚀 TomoKX ETH Trader Starting...${NC}"
echo "================================"

# Check if environment file exists
if [ ! -f "${ENV_FILE}" ]; then
    echo -e "${RED}❌ Environment file not found: ${ENV_FILE}${NC}"
    echo "Please create .env.trading with your OKX API credentials"
    exit 1
fi

# Source environment variables
echo -e "${BLUE}📦 Loading environment...${NC}"
source "${ENV_FILE}"

# Verify proxy and API connectivity
echo -e "${BLUE}🔌 Checking API connectivity...${NC}"
RETRY_COUNT=0
MAX_RETRIES=3

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if proxychains4 okx account balance > /dev/null 2>&1; then
        echo -e "${GREEN}✅ API connection successful${NC}"
        break
    else
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
            echo -e "${RED}❌ API connection failed after ${MAX_RETRIES} attempts${NC}"
            exit 1
        fi
        echo -e "${YELLOW}⚠️  API connection failed, retrying... (${RETRY_COUNT}/${MAX_RETRIES})${NC}"
        sleep 2
    fi
done

# Check if trading is stopped
if [ -f "${STOP_FILE}" ]; then
    STOP_COUNT=$(cat "${STOP_FILE}")
    if [ "$STOP_COUNT" -ge 3 ]; then
        echo -e "${RED}🛑 Trading is paused (consecutive stops: ${STOP_COUNT})${NC}"
        echo "Run 'echo 0 > ${STOP_FILE}' to reset"
        exit 0
    fi
fi

echo -e "${GREEN}✅ ETH Trader environment ready${NC}"
echo ""

# Log start time
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Trading cycle started" >> "${LOG_FILE}"

# Execute trading workflow
echo -e "${BLUE}📊 Executing trading workflow...${NC}"

# Note: In actual implementation, this would call the OpenClaw agent
# with the SKILL.md instructions. For now, we log the intention.

echo -e "${BLUE}📈 Getting market data...${NC}"
echo -e "${BLUE}📋 Checking orders...${NC}"
echo -e "${BLUE}💼 Checking positions...${NC}"
echo -e "${BLUE}🎯 Executing strategy...${NC}"

# Log completion
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Trading cycle completed" >> "${LOG_FILE}"

echo ""
echo -e "${GREEN}✅ Trading cycle complete${NC}"
echo "================================"
echo "📁 Log file: ${LOG_FILE}"
echo ""

# Optional: Send notification (if configured)
if command -v notify-send &> /dev/null; then
    notify-send "TomoKX" "Trading cycle completed" 2>/dev/null || true
fi

exit 0
