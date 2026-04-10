#!/bin/bash

# TomoKX Environment Check Script
# Usage: ./env-check.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
WORKSPACE_DIR="${HOME}/.openclaw/workspace"
ENV_FILE="${WORKSPACE_DIR}/.env.trading"

# Counters
CHECKS_PASSED=0
CHECKS_TOTAL=0

check_pass() {
    echo -e "${GREEN}✅${NC} $1"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
}

check_fail() {
    echo -e "${RED}❌${NC} $1"
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
}

check_warn() {
    echo -e "${YELLOW}⚠️${NC}  $1"
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
}

echo -e "${BLUE}🔍 TomoKX Environment Check${NC}"
echo "================================"
echo ""

# 1. Check Environment Variables
echo -e "${BLUE}1. Environment Variables${NC}"
if [ -f "${ENV_FILE}" ]; then
    check_pass "Environment file exists"
    source "${ENV_FILE}"
    
    if [ -n "$OKX_API_KEY" ]; then
        check_pass "OKX_API_KEY is set"
    else
        check_fail "OKX_API_KEY is not set"
    fi
    
    if [ -n "$OKX_SECRET_KEY" ]; then
        check_pass "OKX_SECRET_KEY is set"
    else
        check_fail "OKX_SECRET_KEY is not set"
    fi
    
    if [ -n "$OKX_PASSPHRASE" ]; then
        check_pass "OKX_PASSPHRASE is set"
    else
        check_fail "OKX_PASSPHRASE is not set"
    fi
else
    check_fail "Environment file not found: ${ENV_FILE}"
fi
echo ""

# 2. Check Dependencies
echo -e "${BLUE}2. Dependencies${NC}"
if command -v git &> /dev/null; then
    check_pass "git is installed ($(git --version | head -1))"
else
    check_fail "git is not installed"
fi

if command -v proxychains4 &> /dev/null; then
    check_pass "proxychains4 is installed"
else
    check_fail "proxychains4 is not installed"
fi

if command -v okx &> /dev/null; then
    check_pass "okx CLI is installed"
else
    check_fail "okx CLI is not installed"
fi
echo ""

# 3. Check API Connectivity
echo -e "${BLUE}3. API Connectivity${NC}"
if [ -f "${ENV_FILE}" ]; then
    source "${ENV_FILE}"
    if proxychains4 okx account balance > /dev/null 2>&1; then
        check_pass "OKX API connection successful"
        
        # Get account info
        BALANCE=$(proxychains4 okx account balance 2>/dev/null | grep -o '"availEq":"[^"]*"' | head -1 | cut -d'"' -f4)
        if [ -n "$BALANCE" ]; then
            echo -e "   ${BLUE}💰 Available Balance: ${BALANCE} USDT${NC}"
        fi
    else
        check_fail "OKX API connection failed"
        echo -e "   ${YELLOW}   Check your API credentials and proxy settings${NC}"
    fi
else
    check_warn "Skipping API check (no env file)"
fi
echo ""

# 4. Check Workspace
echo -e "${BLUE}4. Workspace${NC}"
if [ -d "${WORKSPACE_DIR}" ]; then
    check_pass "Workspace directory exists"
else
    check_warn "Workspace directory does not exist (will be created)"
fi

if [ -w "${WORKSPACE_DIR}" ] || [ -w "$(dirname "${WORKSPACE_DIR}")" ]; then
    check_pass "Workspace directory is writable"
else
    check_fail "Workspace directory is not writable"
fi
echo ""

# 5. Check Trading Status
echo -e "${BLUE}5. Trading Status${NC}"
STOP_FILE="${WORKSPACE_DIR}/.trading_stopped"
if [ -f "${STOP_FILE}" ]; then
    STOP_COUNT=$(cat "${STOP_FILE}")
    if [ "$STOP_COUNT" -ge 3 ]; then
        check_warn "Trading is paused (consecutive stops: ${STOP_COUNT})"
        echo -e "   ${YELLOW}   Run: echo 0 > ${STOP_FILE} to reset${NC}"
    else
        check_pass "Trading is active (consecutive stops: ${STOP_COUNT})"
    fi
else
    check_pass "Trading is active (no stop file)"
fi
echo ""

# Summary
echo "================================"
if [ $CHECKS_PASSED -eq $CHECKS_TOTAL ]; then
    echo -e "${GREEN}🎉 All checks passed! (${CHECKS_PASSED}/${CHECKS_TOTAL})${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Some checks failed (${CHECKS_PASSED}/${CHECKS_TOTAL})${NC}"
    exit 1
fi
