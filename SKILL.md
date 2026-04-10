---
name: tomokx
description: |
  Automated trading system for ETH-USDT-SWAP perpetual contracts on OKX.
  Triggers on: "start trading", "run trading check", "check ETH positions", 
  "place OKX orders", "show trading status", "generate trading report".
  Use for: executing grid trading strategy, managing open orders, 
  monitoring positions, risk control, daily reporting.
---

## Overview

Direct agent-driven automated trading for ETH perpetual swaps on OKX.

## Triggers

This skill activates when you say:
- "开始交易" / "start trading"
- "运行交易检查" / "run trading check"  
- "查看ETH仓位" / "check ETH positions"
- "下单" / "place orders"
- "交易状态" / "trading status"
- "生成日报" / "generate daily report"
- "重置止损计数" / "reset stop counter"

## Trading Strategy

### Trend Detection

| 24h Change | Trend    | Long Orders | Short Orders |
| ---------- | -------- | ----------- | ------------ |
| > +2%      | Bullish  | 2           | 1            |
| < -2%      | Bearish  | 1           | 2            |
| -2% to +2% | Sideways | 1           | 2            |

**Additional Confirmation (Optional):**
- Check 1h trend for short-term confirmation
- Check 4h trend for medium-term direction
- Volume increase > 20% avg confirms trend strength

<br />

### Dynamic Price Gap

| Total Positions | Gap (USDT) |
| --------------- | ---------- |
| 0               | 8          |
| 1               | 10         |
| 2               | 12         |
| 3               | 15         |
| 4               | 20         |
| 5               | 25         |
| 6               | 28         |
| 7               | 32         |
| 8               | 35         |
| 9               | 38         |
| 10              | 40         |
| 11-15           | 42         |
| 16-20           | 45         |

**Note:** Maximum gap (45 USDT) must be less than cancellation threshold (50 USDT) to avoid immediate order cancellation.

**Gap Adjustment Factors:**
- High volatility (ATR > 5): increase gap by 20%
- Wide spread (> 0.5 USDT): increase gap by 10%
- Strong trend (|change| > 5%): increase gap by 15%

<br />

### Risk Controls

- Max Orders: 5 open orders
- Max Total: 20 total positions (orders + holdings)
- Price Threshold: Cancel orders >50 USDT away from current price
- Stop Protection: Pause trading after 3 consecutive stop-losses
- Per-Order TP/SL: Each order has built-in take-profit and stop-loss
- Order Size: 0.1 contracts
- Leverage: 10x isolated margin
- Daily Loss Limit: Stop trading if daily loss > 40 USDT
- Max Consecutive Orders: Max 3 new orders per cycle

## Execution Workflow

### Step 0: Environment Setup

Run these commands before any OKX CLI operations:

```bash
# Source environment variables
source ~/.openclaw/workspace/.env.trading

# Verify proxy and API connectivity (with retry)
proxychains4 okx account balance || (sleep 2 && proxychains4 okx account balance)
```

**Important:** proxychains4 spawns a new process and does NOT automatically inherit unsourced env vars. Always source .env.trading first.

### Step 1: Check Trading Status

**1.1 Check Stop Protection:**

Read ~/.openclaw/workspace/.trading_stopped. If it exists and contains a number ≥ 3:

- Notify the user: 🛑 交易已暂停 / 连续止损次数: X / 已达到最大允许次数，交易自动暂停
- STOP execution

To reset: `echo 0 > ~/.openclaw/workspace/.trading_stopped`

**1.2 Check Daily Loss Limit:**

Calculate today's realized P&L from positions closed today. If daily loss > 40 USDT:

- Notify the user: ⚠️ 日亏损限制触发 / 今日亏损: X USDT / 已停止交易
- STOP execution
- Log: `[timestamp] Daily loss limit reached: X USDT, trading stopped`

### Step 2: Get Market Data

Use the OKX CLI to fetch ETH-USDT-SWAP ticker data:

```bash
proxychains4 okx market ticker ETH-USDT-SWAP
```

Parse the response and determine trend:
- CHANGE_PCT > 2 → Bullish
- CHANGE_PCT < -2 → Bearish
- Otherwise → Sideways

### Step 3: Check Current Orders

Count only live ETH-USDT-SWAP orders with size 0.1:

```bash
proxychains4 okx trade orders --inst-id ETH-USDT-SWAP --state live
```

Filter: ordType = "limit" AND sz = "0.1"

### Step 4: Check Current Positions

Count only 10x isolated ETH-USDT-SWAP positions:

```bash
proxychains4 okx trade positions --inst-type SWAP
```

Filter: instId = "ETH-USDT-SWAP" AND mgnMode = "isolated" AND lever = "10"

### Step 5: Calculate Totals

```
orders_count + positions_count = total
```

### Step 6: Cancel Far Orders

Get current ETH price from Step 2, then for each live order:

```bash
# Cancel order if price deviation > 50 USDT
proxychains4 okx trade cancel-order --inst-id ETH-USDT-SWAP --ord-id <order_id>
```

If |order_price - current_price| > 50 USDT, cancel the order.

**Log cancelled orders:**
```
[timestamp] Cancelled order <ord-id>: price <order_price> too far from current <current_price>
```

### Step 7: Determine Target Order Distribution

| Trend    | target_long | target_short |
| -------- | ----------- | ------------ |
| Bullish  | 2           | 1            |
| Bearish  | 1           | 2            |
| Sideways | 1           | 2            |

### Step 8: Manage Orders

**Open New Orders:**
- Condition: orders_count < 5 AND total < 20
- Calculate: need_orders = min(5 - orders_count, 20 - total, 3)

**Replenish Orders (if below minimum):**
- Condition: orders_count < 3 AND total < 20  
- Calculate: replenish_count = min(3 - orders_count, 20 - total, 2)

**Order Placement Steps:**
1. Calculate dynamic gap based on total positions (see table above)
2. Adjust gap for volatility/spread if needed
3. Decide side: Prefer the side with fewer total positions
4. Calculate price: current_price ± gap (round to 2 decimals)
5. Check price conflicts: ensure ≥ 8 USDT apart from existing orders
   - If conflict detected (price too close to existing order), **SKIP this order** and continue to next
6. Calculate TP/SL (see formula below)
7. Place order with TP/SL attached

### Step 9: Calculate TP/SL

For each new order:

```
Take Profit: entry_price ± (gap × 3)
  - Long: entry + (gap × 3)
  - Short: entry - (gap × 3)

Stop Loss: entry_price ∓ (gap × 1.5)
  - Long: entry - (gap × 1.5)
  - Short: entry + (gap × 1.5)
```

Round all prices to 2 decimals.

### Step 10: Log and Notify

**1. Append to Log File:**

```bash
cat >> ~/.openclaw/workspace/auto_trade.log << EOF
[$(date '+%Y-%m-%d %H:%M:%S')] Trading Cycle Summary
- Market Trend: <Bullish/Bearish/Sideways>
- Current Price: <price> USDT
- Orders: <count> live, <count> new placed
- Positions: <count> open
- Total Exposure: <count>/20
- Actions: <list of actions taken>
EOF
```

**2. Send Notification to User:**

After completing all trading actions, format and display a summary notification:

```
📊 ETH Trader 执行完成
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ 时间: $(date '+%Y-%m-%d %H:%M:%S')
📈 趋势: <Bullish/Bearish/Sideways>
💰 价格: <price> USDT
📋 挂单: <orders_count>/5
💼 持仓: <positions_count>
📊 总暴露: <total>/20
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 操作记录:
• <action 1>
• <action 2>
• ...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Notification Rules:**
- Always notify after completing Step 10
- Include key metrics (trend, price, orders, positions)
- List all actions taken in this cycle
- Highlight important events (orders placed, cancelled, errors)
- Use emoji for better readability

**Special Notifications:**

If trading was paused (Step 1 stop triggered):
```
🛑 交易已暂停
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 连续止损次数: <count>
⏸️ 交易已自动暂停，请检查策略
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

If daily loss limit reached:
```
⚠️ 日亏损限制触发
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📉 今日亏损: <loss> USDT
🚫 已停止交易，明日自动恢复
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 11: Daily Report (Optional)

Query and summarize:

```bash
# Get positions
proxychains4 okx trade positions --inst-type SWAP

# Get orders
proxychains4 okx trade orders --inst-id ETH-USDT-SWAP --state live

# Get balance
proxychains4 okx account balance

# Read recent logs
tail -n 50 ~/.openclaw/workspace/auto_trade.log
```

Generate summary report with P&L analysis.

## OKX CLI Commands Reference

### Get Market Data
```bash
proxychains4 okx market ticker ETH-USDT-SWAP
```

### List Orders
```bash
proxychains4 okx trade orders --inst-id ETH-USDT-SWAP --state live
```

### Place Order with TP/SL
```bash
proxychains4 okx trade place-order \
  --inst-id ETH-USDT-SWAP \
  --td-mode isolated \
  --side <buy|sell> \
  --ord-type limit \
  --sz 0.1 \
  --px <entry_price> \
  --tp-trigger-px <tp_price> \
  --tp-ord-px -1 \
  --sl-trigger-px <sl_price> \
  --sl-ord-px -1
```

### Cancel Order
```bash
proxychains4 okx trade cancel-order --inst-id ETH-USDT-SWAP --ord-id <order_id>
```

### Get Positions
```bash
proxychains4 okx trade positions --inst-type SWAP
```

### Get Account Balance
```bash
proxychains4 okx account balance
```

## Network Retry Rule

Any proxychains4 okx or proxychains4 curl call that fails with network/timeout errors must be retried up to 3 times with a 2-second sleep between attempts.

**Retry Pattern:**
```bash
for i in 1 2 3; do
  proxychains4 okx <command> && break
  sleep 2
done
```

## Error Handling

### API Rate Limit (429)
- Wait 10 seconds before retry
- Reduce command frequency
- Log rate limit event

### Insufficient Balance
- Skip order placement
- Log warning: "Insufficient margin, skipping order"
- Continue to next cycle
- Notify user if balance < 50 USDT

### Order Rejection
- Log rejection reason
- Check price is within valid range
- Retry with adjusted price (± 1 USDT) if needed
- Max 2 retries per order

### Network Timeout
- Apply retry rule (3 attempts with 2s delay)
- If all retries fail, log error and skip cycle
- Notify user after 3 consecutive network failures

### Market Anomaly Detection
Pause trading if:
- Price changes > 10% in 1 minute (flash crash/pump)
- Spread > 2 USDT (liquidity issue)
- No market data for > 30 seconds

## Quick Commands Reference

### Run Trading Check
Execute Steps 0-10 completely.

**Usage:** "开始交易" or "run trading check"

### Show Status
Execute Steps 0, 2, 3, 4 and report current state without placing orders.

**Usage:** "交易状态" or "show trading status"

### Reset Stop Counter
Reset the consecutive stop-loss counter to 0 and resume trading.

```bash
echo 0 > ~/.openclaw/workspace/.trading_stopped
```

**Usage:** "重置止损计数" or "reset stop counter"

**After reset, notify user:**
```
✅ 止损计数已重置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔢 连续止损次数: 0
▶️ 交易已恢复
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Generate Daily Report
Query positions, orders, balance, and summarize recent activity from logs.

**Usage:** "生成日报" or "generate daily report"

## Risk Warning

Trading involves significant risk of loss. This system uses leveraged trading which can amplify both gains and losses. Never trade with money you cannot afford to lose. Monitor positions regularly.

**Important Risk Disclosures:**
- 10x leverage means 10% price move = 100% position loss
- Stop-losses are not guaranteed to execute at exact price
- Market gaps can cause larger losses than expected
- Past performance does not guarantee future results

## 辅助脚本

### 1. eth-trader-run.sh

Wrapper script for heartbeat execution.

**Location:** `scripts/eth-trader-run.sh`

**Usage:**
```bash
./scripts/eth-trader-run.sh
```

**What it does:**
1. Sources environment variables from .env.trading
2. Validates proxy connection to OKX API
3. Checks if trading is paused
4. Executes complete trading workflow (Steps 0-10)
5. Logs all output to auto_trade.log with timestamps
6. Returns exit code 0 on success, 1 on failure

**Expected Output:**
```
✅ ETH Trader 环境已就绪，API 代理正常
📊 获取市场数据...
📋 检查当前订单...
💼 检查当前仓位...
🎯 执行交易策略...
✅ 交易循环完成
```

### 2. env-check.sh

快速验证 ETH Trader 交易环境。

**Location:** `scripts/env-check.sh`

**Usage:**
```bash
./scripts/env-check.sh
```

**Checks:**
- ✅ Environment variables loaded (OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE)
- ✅ OKX API connectivity (ping test)
- ✅ Proxy configuration (proxychains4 working)
- ✅ Account balance (shows USDT and ETH balance)
- ✅ Trading permissions (account status)
- ✅ Log directory writable

**Output Example:**
```
🔍 ETH Trader Environment Check
================================
✅ Environment variables: OK
✅ OKX API connectivity: OK
✅ Proxy configuration: OK
💰 Account Balance: 1234.56 USDT
✅ Trading permissions: Enabled
✅ Log directory: Writable
================================
🎉 All checks passed!
```

## Configuration

### Environment Variables (.env.trading)

```bash
# OKX API Credentials
export OKX_API_KEY="your-api-key"
export OKX_SECRET_KEY="your-secret-key"
export OKX_PASSPHRASE="your-passphrase"

# Proxy Settings
export PROXY_HOST="127.0.0.1"
export PROXY_PORT="7890"

# Trading Parameters (optional overrides)
export MAX_ORDERS=5
export MAX_POSITIONS=20
export ORDER_SIZE=0.1
export LEVERAGE=10
export DAILY_LOSS_LIMIT=40
```

### File Structure

```
~/.openclaw/workspace/
├── .env.trading          # API keys and config
├── .trading_stopped      # Stop counter (0-3+)
├── auto_trade.log        # Trading activity log
└── tomokx/
    ├── SKILL.md          # This file
    └── scripts/
        ├── eth-trader-run.sh
        └── env-check.sh
```
