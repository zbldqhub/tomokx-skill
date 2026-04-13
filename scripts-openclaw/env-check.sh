#!/usr/bin/env bash
# env-check.sh - 快速验证 ETH Trader 交易环境 (Linux/macOS)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

WORKSPACE="${HOME}/.openclaw/workspace"
ENV_FILE="${WORKSPACE}/.env.trading"

echo "======================================"
echo "     ETH Trader 环境检查"
echo "======================================"

# 1. 检查必要命令
MISSING=0
for cmd in okx curl python3 bc; do
    if command -v "$cmd" >&/dev/null; then
        echo -e "${GREEN}✓${NC} $cmd 已安装"
    else
        echo -e "${RED}✗${NC} $cmd 未安装"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo -e "${RED}环境不完整，请先安装缺失的依赖${NC}"
    exit 1
fi

# 2. 检查环境变量文件
if [ -f "$ENV_FILE" ]; then
    echo -e "${GREEN}✓${NC} 环境文件存在: $ENV_FILE"
else
    echo -e "${RED}✗${NC} 环境文件不存在: $ENV_FILE"
    exit 1
fi

# 3. 加载环境变量并检查
source "$ENV_FILE"
if [ -n "${OKX_API_KEY:-}" ] && [ -n "${OKX_SECRET_KEY:-}" ] && [ -n "${OKX_PASSPHRASE:-}" ]; then
    echo -e "${GREEN}✓${NC} API 密钥已配置"
else
    echo -e "${RED}✗${NC} API 密钥未完整配置"
    exit 1
fi

# 4. API 连通性检查
echo ""
echo "正在测试 OKX API 连接..."
for i in 1 2 3; do
    if curl -s --max-time 15 "https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP" 2>/dev/null | grep -q '"last":"'; then
        LAST=$(curl -s --max-time 15 "https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP" 2>/dev/null | grep -o '"last":"[0-9.]*"' | head -1 | cut -d'"' -f4)
        echo -e "${GREEN}✓${NC} OKX API 连接正常，ETH-USDT-SWAP 最新价格: $LAST"
        break
    fi
    if [ "$i" -eq 3 ]; then
        echo -e "${RED}✗${NC} OKX API 连接失败"
        exit 1
    fi
    sleep 2
done

# 5. OKX CLI 认证检查
echo ""
echo "正在测试 OKX CLI 认证..."
if okx swap orders >&1 2>&1 | grep -q "Error: Private endpoint requires API credentials"; then
    echo -e "${RED}✗${NC} OKX CLI 认证失败"
    echo -e "${YELLOW}!${NC} 提示: 确保 okx config 中配置了正确的 API 密钥"
    exit 1
else
    echo -e "${GREEN}✓${NC} OKX CLI 认证正常"
fi

echo ""
echo "======================================"
echo -e "${GREEN}全部检查通过，环境就绪${NC}"
echo "======================================"
