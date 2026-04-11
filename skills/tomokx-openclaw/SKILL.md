---
name: tomokx-openclaw
description: |
  Automated trading system for ETH-USDT-SWAP perpetual contracts on OKX.
  Triggers on: "start trading", "run trading check", "check ETH positions",
  "place OKX orders", "show trading status", "generate trading report".
  Use for: executing grid trading strategy, managing open orders,
  monitoring positions, risk control, daily reporting.
---

## Overview

Direct agent-driven automated trading for ETH perpetual swaps on OKX. All core trading logic is executed step-by-step by the Agent. Auxiliary scripts exist for environment validation only and are never used for actual trade decisions.

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
| 0               | 5          |
| 1               | 6          |
| 2               | 7          |
| 3               | 8          |
| 4               | 9          |
| 5               | 10         |
| 6               | 10         |
| 7-10            | 11         |
| 11-15           | 12         |
| 16-20           | 14         |

**Note:** Maximum gap (14 USDT) and the dense grid ensure the farthest order (8th order from current price) stays within ~60 USDT.

**Gap Adjustment Factors:**
- High volatility (ATR > 5): increase gap by 20%
- Wide spread (> 0.5 USDT): increase gap by 10%
- Strong trend (|change| > 5%): increase gap by 15%

<br />

### Risk Controls

- Max Orders: 20 open orders
- Max Total: 20 total positions (orders + holdings)
- Price Threshold: Cancel orders >100 USDT away from current price
- Stop Protection: Pause trading after 3 consecutive stop-losses
- Per-Order TP/SL: Each order has built-in take-profit and stop-loss
- Order Size: 0.1 contracts (≈ 2 USDT margin @ 10x)
- Leverage: 10x isolated margin
- Daily Loss Limit: Stop trading if daily loss > 40 USDT
- Max Consecutive Orders: Max 5 new orders per cycle

## Execution Workflow

### Step 0: Environment Setup

Before any OKX CLI operation, always run:
```bash
source ~/.openclaw/workspace/.env.trading
```

**Verify API connectivity.** Execute this test command; if it does not return data containing "last", wait 2 seconds and retry up to 3 times:
```bash
source ~/.openclaw/workspace/.env.trading && curl -s --max-time 15 https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP 2>/dev/null | grep last
```

If all 3 retries fail, STOP execution and notify the user.

### Step 1: Check Trading Status

**1.1 Check Stop Protection:**

Read `~/.openclaw/workspace/.trading_stopped`. 
- If the file contains a date older than today, **reset it to `0`** and continue.
- If it exists and contains a number ≥ 3:
  - Notify the user: 🛑 交易已暂停 / 连续止损次数: X / 已达到最大允许次数，交易自动暂停
  - STOP execution

To reset: `echo 0 > ~/.openclaw/workspace/.trading_stopped`

**1.2 Check Daily Loss Limit:**

Calculate today's realized P&L for **ETH-USDT-SWAP only** from positions closed today. Run:
```bash
python3 ~/.openclaw/workspace/scripts/get_bills.py --today
```
Parse the JSON output. Filter:
- `instId = ETH-USDT-SWAP`
- `subType` is one of **4, 6, 110, 111, 112** (reduce/close/TP/SL/liquidation)
Sum **all** of those `pnl` values (both positive and negative) to get the **net realized P&L**. If the net total is **less than -40 USDT**:
- Notify the user: ⚠️ 日亏损限制触发 / 今日ETH亏损: X USDT / 已停止交易
- STOP execution
- Log: `[timestamp] Daily ETH loss limit reached: X USDT, trading stopped`

### Step 1.5: Fetch Market Snapshot

Run the data aggregator script to collect all market data, orders, positions, and balance in one shot:
```bash
python3 ~/.openclaw/workspace/scripts/eth_market_analyzer.py
```

Parse the JSON output. If the script fails (non-zero exit or no JSON), fall back to the individual CLI commands in Steps 2–4.

**Key fields to extract:**
- `market.last` → current price
- `market.change24h_pct` → 24h change
- `hourly_stats.volatility_1h` → 1h average range
- `hourly_stats.trend_1h` → bullish / bearish / sideways
- `hourly_stats.recent_change_1h_pct` → recent 1–3h change
- `orders` → live orders list
- `positions` → current positions list
- `balance` → account balance list

### Step 2: Get Market Data

Use the OKX CLI to fetch ETH-USDT-SWAP ticker data. **Prefer using the JSON output from Step 1.5.** If Step 1.5 failed, run:
```bash
source ~/.openclaw/workspace/.env.trading
okx market ticker ETH-USDT-SWAP
```

Parse the response and determine trend. Use both **1h stats** (`hourly_stats`) and **24h change** (`market.change24h_pct`) for a combined decision:
- If `recent_change_1h_pct` strongly disagrees with `change24h_pct`, trust the 1h trend (shorter-term momentum matters more for grid placement).
- Default rules:
  - `change24h_pct` > +2 **and** 1h trend bullish → **Bullish**
  - `change24h_pct` < -2 **and** 1h trend bearish → **Bearish**
  - Otherwise → **Sideways**
- In ambiguous cases (e.g. 24h bullish but 1h bearish), lean **Sideways** or slightly reduce directional bias.

### Step 3: Check Current Orders

Count only live ETH-USDT-SWAP **opening-direction** orders with size 0.1. **Prefer using `orders` from Step 1.5.** If unavailable, run:
```bash
source ~/.openclaw/workspace/.env.trading
okx swap orders
```
**Strict counting rule:** Only include orders where:
- `instId = ETH-USDT-SWAP`
- `type = limit`
- `sz = 0.1`
- `state = live`
- **AND** (`side = sell` AND `posSide = short`) **OR** (`side = buy` AND `posSide = long`)

**Do NOT count** closing-direction orders (`sell+long` or `buy+short`).

### Step 4: Check Current Positions

Count only 10x isolated ETH-USDT-SWAP positions. **Prefer using `positions` from Step 1.5.** If unavailable, run:
```bash
source ~/.openclaw/workspace/.env.trading
okx swap positions
```
Filter: instId = ETH-USDT-SWAP AND lever = 10.

### Step 5: Calculate Totals

- short_orders_count = number of live sell/short 0.1 orders
- long_orders_count = number of live buy/long 0.1 orders
- short_pos_units = total short position size / 0.1
- long_pos_units = total long position size / 0.1
- orders_count = short_orders_count + long_orders_count
- positions_count = short_pos_units + long_pos_units
- total = orders_count + positions_count

### Step 6: Cancel Far Orders

If Step 1.5 succeeded, use `market.last` as current price. Then for each live 0.1 order:
If |order_price - current_price| > 100 USDT, cancel it:
```bash
source ~/.openclaw/workspace/.env.trading
okx swap cancel --instId ETH-USDT-SWAP --ordId <order_id>
```

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
- Condition: orders_count < 20 AND total < 20
- Calculate: `remaining_capacity = floor(20 - total)`; `need_orders = min(20 - orders_count, remaining_capacity, 5)`

**Replenish Orders (if below minimum):**
- Condition: orders_count < 10 AND total < 20
- Calculate: `replenish_count = min(10 - orders_count, remaining_capacity, 5)`

**Per-Side Maximum:**
- Maximum **4 live orders** on each side (long or short) to ensure the farthest order stays within ~100 USDT.
- If one side already has ≥4 live orders, do NOT place additional opening orders on that side in this cycle.

**Order Placement Steps:**
1. Start with the base dynamic gap from the table above (`0–20` positions mapped to 5–14 USDT).
2. **Adjust gap based on 1h volatility (from Step 1.5):**
   - `volatility_1h` < 8 → gap can decrease by 1–2 (denser grid)
   - `volatility_1h` 8–15 → use base gap
   - `volatility_1h` > 15 → gap can increase by 2–4 (wider grid)
   - `volatility_1h` > 25 → further increase gap or pause new orders
   - **AI discretion:** you may vary the exact adjustment within ±3 USDT based on the full context.
3. Check spread (`askPx - bidPx`). If > 0.5 USDT, add 1 to gap.
4. **Decide side:**
   - **First**, ensure the target distribution from Step 7 is met (e.g., Bullish needs at least 2 long for every 1 short). 
   - **Only if** the target ratio is already satisfied, prefer the side with fewer total positions.
   - Respect the per-side maximum of 4 live orders.
5. **Grid order placement rule:** All new orders must be **opening-direction only** and placed **outside** the current live grid (away from the market price). Do NOT place closing orders (`sell+long` or `buy+short`). Position reduction is handled exclusively by per-order TP/SL.

   **Two scenarios:**

   **A. Replenishing a partially filled side (1 or 2 missing orders):**
   - Calculate the price from the **farthest existing live order** on that side, extending outward by exactly one gap:
     - New short = **max_short_px + gap**
     - New long = **min_long_px - gap**
   - **NEVER** replenish on the inside (between the market price and the nearest live order). An inside order would be immediately filled or worse-than-market, defeating the purpose of a limit grid.

   **B. Building a side from scratch (0 live orders on that side):**
   - Short #1 = current_price × 1.002
   - Short #2 = Short #1 + gap
   - Short #3 = Short #2 + gap
   - Short #4 = Short #3 + gap
   - Long #1 = current_price × 0.998
   - Long #2 = Long #1 - gap
   - Long #3 = Long #2 - gap
   - Long #4 = Long #3 - gap
7. Round price to 2 decimal places before placing.
8. **Critical intra-cycle conflict check:** Before finalizing each newly planned order, compare its price against **all other newly planned orders in this same cycle** (as well as existing live orders on the same side). If any two planned orders are **< gap** apart, move the conflicting order outward by **exactly one additional gap** and re-check. Repeat until all intra-cycle and live-order conflicts are resolved. **Never place two orders within the same cycle at prices that differ by less than the gap.**
9. Calculate TP/SL:
   - **TP** = entry_price ± a dynamic offset chosen by the Agent based on current `volatility_1h`. Use this mapping:
     | `volatility_1h` | TP Offset Range | Recommendation |
     |-----------------|-----------------|----------------|
     | < 5             | **8–15 USDT**   | Low volatility → tight TP for frequent fills |
     | 5–10            | **15–25 USDT**  | Moderate low vol → balanced |
     | 10–15           | **20–35 USDT**  | Normal vol → default range |
     | 15–25           | **30–45 USDT**  | Elevated vol → wider TP |
     | > 25            | **40–50 USDT**  | High vol → maximum width |
   - **SL** = entry_price ∓ a dynamic offset in the range **80–120 USDT**, chosen by the Agent based on current market conditions. In low volatility (`volatility_1h` < 8), lean toward the lower end (80–90); in high volatility, lean toward the upper end (110–120).
     - Long: TP = entry + offset_tp, SL = entry - offset_sl
     - Short: TP = entry - offset_tp, SL = entry + offset_sl
   - Round TP and SL to 2 decimals.
10. Place order with TP/SL attached:
```bash
source ~/.openclaw/workspace/.env.trading
okx swap place --instId ETH-USDT-SWAP --tdMode isolated --side <sell|buy> --ordType limit --sz 0.1 --px=<px> --posSide <short|long> --tpTriggerPx=<tp> --tpOrdPx=-1 --slTriggerPx=<sl> --slOrdPx=-1
```

After each placement, update counters and re-check limits before placing the next order.

### Step 8.5: Update Stop-Loss Counter

After placing orders, check whether any previously placed ETH-USDT-SWAP orders with attached SL were triggered and closed at a loss since the last trading cycle.

**Detection method:**
```bash
python3 ~/.openclaw/workspace/scripts/get_bills.py --today
```
Filter for:
- `instId = ETH-USDT-SWAP`
- `subType` is one of **4, 6, 110, 111, 112** (reduce/close/TP/SL/liquidation)
- `pnl < 0`
- `ts` is newer than the timestamp of the last trading check

For each qualifying stop-loss event:
1. Read `~/.openclaw/workspace/.trading_stopped`
2. Increment the number by 1
3. Write it back to `~/.openclaw/workspace/.trading_stopped`
4. Log: `[timestamp] Stop-loss triggered: ordId=<id>, pnl=<pnl>. Consecutive count: X`

If the file contains a date older than today, reset it to `0` before counting.

If the updated count is **≥ 3**:
- STOP execution immediately
- Notify the user: 🛑 交易已暂停 / 连续止损次数: X / 已达到最大允许次数，交易自动暂停

If the file contains a date older than today, reset it to `0` before counting.

### Step 9: Calculate TP/SL

See Step 8 placement steps for exact formulas. TP uses a volatility-mapped dynamic offset (8–50 USDT) and SL uses a dynamic 80–120 USDT offset based on market conditions. Round all prices to 2 decimals.

### Step 10: Log and Notify

**Append to Log File:**
```
[timestamp] | tomokx | Trading Cycle Summary
- Market Trend: <Bullish/Bearish/Sideways>
- Current Price: <price> USDT
- Orders: <orders_count> live, <new_placed> new placed
- Positions: <positions_count> open
- Total Exposure: <total>/20
- Actions: <list of actions taken>
```

**Send Notification to User:**

After completing all trading actions, format and display a summary notification:

```
📊 ETH Trader 执行完成
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ 时间: <timestamp>
📈 趋势: <Bullish/Bearish/Sideways>
💰 价格: <price> USDT
📋 挂单: <orders_count>/20
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
source ~/.openclaw/workspace/.env.trading
okx swap positions
okx swap orders
okx account balance
tail -n 50 ~/.openclaw/workspace/auto_trade.log
```

Generate summary report with P&L analysis.

## OKX CLI Commands Reference (Current CLI 1.3.0)

> **Note on `--json` (v1.3.0 behavior change):** In CLI 1.3.0, `--json` returns **raw data** by default (arrays/objects). The old wrapper `{ code, data }` is only returned when using the new `--env` flag. The `eth_market_analyzer.py` script uses `--json` and handles both raw and wrapped formats for compatibility.

### Get Market Data
```bash
okx market ticker ETH-USDT-SWAP
# JSON output (script preferred)
okx market ticker ETH-USDT-SWAP --json
```

### List Orders
```bash
okx swap orders
# JSON output (script preferred)
okx swap orders --json
```

### Place Order with TP/SL
```bash
okx swap place --instId ETH-USDT-SWAP --tdMode isolated --side <sell|buy> --ordType limit --sz 0.1 --px=<px> --posSide <short|long> --tpTriggerPx=<tp> --tpOrdPx=-1 --slTriggerPx=<sl> --slOrdPx=-1
```

### Cancel Order
```bash
okx swap cancel --instId ETH-USDT-SWAP --ordId <order_id>
```

### Get Positions
```bash
okx swap positions
# JSON output (script preferred)
okx swap positions --json
```

### Get Account Balance
```bash
okx account balance
# JSON output (script preferred)
okx account balance --json
```

## Network Retry Rule

Any `okx` or `curl` call that fails with network/timeout errors must be retried up to 3 times with a 2-second sleep between attempts. If all retries fail, STOP execution and notify the user with the error details.

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

## 辅助脚本 (仅用于环境检查，不参与交易决策)

### 1. eth-trader-run.sh
Wrapper script for environment validation only. Does NOT execute trading decisions.

### 2. env-check.sh
快速验证 ETH Trader 交易环境（Linux/macOS）。
```bash
bash ~/.openclaw/workspace/scripts/env-check.sh
```

## Configuration

### Environment Variables (.env.trading)

```bash
# OKX API Credentials
export OKX_API_KEY="your-api-key"
export OKX_SECRET_KEY="your-secret-key"
export OKX_PASSPHRASE="your-passphrase"

# Trading Parameters
export MAX_ORDERS=20
export MAX_TOTAL=20
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
└── scripts/              # Trading scripts
    ├── eth_market_analyzer.py
    ├── env-check.sh
    └── eth-trader-run.sh
```
