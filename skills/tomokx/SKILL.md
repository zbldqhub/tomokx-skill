---
name: tomokx
description: "Automated ETH-USDT-SWAP grid trading on OKX. Triggers: start trading, run trading check, trading status, generate daily report, reset stop counter."
---

## Core Strategy

- **Pure opening grid**: Only `buy+long` and `sell+short`. Closing is handled by per-order TP/SL.
- **Max exposure**: 20 units total (`orders + positions`).
- **Per-side max**: 4 live orders per side.
- **Cancel threshold**: Orders > 100 USDT from current price are cancelled.
- **Daily loss limit**: Net realized P&L < -40 USDT for ETH-USDT-SWAP → stop.
- **Stop-loss counter**: 3 consecutive losing closes (subType 4/6/110/111/112 with pnl<0) → stop.

`$WORKSPACE` = `C:\Users\ldq\.openclaw\workspace`

### Trend Targets

| 24h Change | Trend    | Long | Short |
| ---------- | -------- | ---- | ----- |
| > +2%      | Bullish  | 2    | 1     |
| < -2%      | Bearish  | 1    | 2     |
| -2% to +2% | Sideways | 1    | 2     |

### Dynamic Gap

| Total Positions | Gap |
| --------------- | --- |
| 0               | 5   |
| 1               | 6   |
| 2               | 7   |
| 3               | 8   |
| 4               | 9   |
| 5-6             | 10  |
| 7-10            | 11  |
| 11-15           | 12  |
| 16-20           | 14  |

**Gap adjustments:** volatility > 15 → +2~4; > 25 → +4~6 or pause. Spread > 0.5 → +1.

---

## Execution Steps

### Phase 1: Data Preparation (Scripted)

Run the prepared data script. It loads env, checks risk, fetches market/orders/positions, and outputs a JSON payload.

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\prepare_trade_data.py"
```

**What it does (non-AI):**
- Loads API credentials
- Checks `.trading_stopped` count
- Checks daily P&L limit
- Fetches market ticker + 1h candles
- Classifies live `sell+short` and `buy+long` orders
- Counts 10x isolated positions
- Calculates `total` and `remaining_capacity`
- Identifies far orders (>100 USDT away)
- Computes suggested `gap`
- Counts today's losing closes

If `should_stop` is true in the JSON output, stop immediately and notify the user with the `stop_reason`.

---

### Phase 2: AI Analysis & Decision

Read the JSON output from Phase 1. AI performs the following steps:

**Step 2:** Determine trend. Prefer `trend_1h` over `change24h_pct` when they conflict.

**Step 7:** Determine target distribution from the trend table.

**Step 8:** Plan orders.
- Conditions: `total < 20`, `remaining_capacity > 0`, per-side ≤ 4.
- `replenish_count = min(10 - orders_count, remaining_capacity, 5)`.
- **Absolute distance cap:** Do NOT place orders ≥ 80 USDT from current price.
- **Outer replenish:** `new_short = max_short_px + gap`; `new_long = min_long_px - gap`.
- **Inner replenish (allowed when price moved inside the grid):**
  - Short: `new_short = min(current_price + gap, innermost_short_px - gap)` (must be > `current_price + gap`)
  - Long: `new_long = max(current_price - gap, innermost_long_px + gap)` (must be < `current_price - gap`)
- **Build from scratch (0 live orders):**
  - Short #1 = `current_price × 1.002`, then +gap outward.
  - Long #1 = `current_price × 0.998`, then -gap outward.
- **Intra-cycle gap check:** All planned orders on the same side must be ≥ `gap` apart.
- **TP/SL:**
  - `volatility_1h` < 5 → TP 8-15, SL 80-90
  - 5-10 → TP 15-25, SL 85-95
  - 10-15 → TP 20-35, SL 90-105
  - 15-25 → TP 30-45, SL 100-115
  - > 25 → TP 40-50, SL 110-120
  - Long: TP = px + offset, SL = px - offset
  - Short: TP = px - offset, SL = px + offset
- **Pre-placement validation (MUST check before every order):**
  - Long order: `tpTriggerPx > px` AND `slTriggerPx < px`
  - Short order: `tpTriggerPx < px` AND `slTriggerPx > px`
  - If this check fails, **DO NOT place the order**. Recalculate TP/SL and re-check. If still invalid, skip this order and log the error.

AI must produce a `plan.json` file describing cancellations and placements:

```json
{
  "cancellations": [
    {"instId": "ETH-USDT-SWAP", "ordId": "123456"}
  ],
  "placements": [
    {
      "instId": "ETH-USDT-SWAP",
      "tdMode": "isolated",
      "side": "sell",
      "ordType": "limit",
      "sz": "0.1",
      "px": "2301.75",
      "posSide": "short",
      "tpTriggerPx": "2263.75",
      "slTriggerPx": "2411.75"
    }
  ]
}
```

Save it to:
```powershell
$env:TEMP + "\tomokx_plan.json"
```

---

### Phase 3: Execution (Scripted)

Execute the AI-generated plan:

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\execute_orders.py" ($env:TEMP + "\tomokx_plan.json")
```

Then update the stop-loss counter:

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\update_stop_counter.py"
```

Finally, write the log:

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\log_trade.py" `
  --trend "<trend>" `
  --price "<price>" `
  --orders "<orders>" `
  --positions "<positions>" `
  --total "<total>" `
  --actions "<actions>"
```

Notify with:
```
📊 ETH Trader 执行完成
趋势: <trend> | 价格: <price> | 挂单: <orders>/20 | 持仓: <positions> | 总暴露: <total>/20
操作: <actions>
```

---

## CLI Reference (v1.3.0)

```bash
okx market ticker ETH-USDT-SWAP --json
okx swap orders --json
okx swap positions --json
okx account balance --json
okx swap cancel --instId ETH-USDT-SWAP --ordId <id>
okx swap place --instId ETH-USDT-SWAP --tdMode isolated --side <sell|buy> --ordType limit --sz 0.1 --px=<px> --posSide <short|long> --tpTriggerPx=<tp> --tpOrdPx=-1 --slTriggerPx=<sl> --slOrdPx=-1
```

If using Clash/V2Ray proxy on Windows and OKX CLI TLS fails, run:
```bash
node $WORKSPACE/scripts/patch-okx-cli.js
```

## Error Handling

- **Network/timeout:** Retry up to 3 times with 2s sleep. If all fail, stop and notify.
- **Rate limit (429):** Wait 10s, then retry.
- **Insufficient balance:** Skip order, log warning.
- **Order rejection:** Adjust price ±1 USDT and retry (max 2 retries).
- **Market anomaly:** Pause if price moves > 10% in 1 min or spread > 2 USDT.

## Quick Commands

- **Reset stop counter:** `echo 0 > $WORKSPACE/.trading_stopped`
- **Env check (PowerShell):** `$WORKSPACE/scripts/env-check.ps1`
- **Env check (Git Bash):** `bash $WORKSPACE/scripts/env-check.sh`
- **Cycle diagnostic:** `python $WORKSPACE/scripts/trade_cycle_check.py`

## Risk Warning

Leveraged trading carries significant risk. Monitor positions regularly. Only trade with funds you can afford to lose.
