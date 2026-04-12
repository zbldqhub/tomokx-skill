---
name: tomokx-openclaw
description: "Automated ETH-USDT-SWAP grid trading on OKX. Triggers: start trading, run trading check, trading status, generate daily report, reset stop counter."
metadata:
  {"openclaw": {"emoji": "📈"}}
---

## Core Strategy

- **Pure opening grid**: Only `buy+long` and `sell+short`. Closing is handled by per-order TP/SL.
- **Max exposure**: 20 units total (`orders + positions`).
- **Per-side max**: 4 live orders per side.
- **Cancel threshold**: Orders > 100 USDT from current price are cancelled.
- **Daily loss limit**: Net realized P&L < -40 USDT for ETH-USDT-SWAP → stop.
- **Stop-loss counter**: 3 consecutive losing closes (subType 4/6/110/111/112 with pnl<0) → stop.

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

**Step 0:** Source env before any command:
```bash
source ~/.openclaw/workspace/.env.trading
```

**Step 1:** Check `.trading_stopped`. If ≥ 3 → stop. If date < today → reset to 0.

**Step 1.2:** Check daily loss:
```bash
python3 ~/.openclaw/workspace/scripts/get_bills.py --today
```
Filter `instId=ETH-USDT-SWAP` and `subType ∈ {4,6,110,111,112}`. Sum all `pnl`. If net < -40 → stop.

**Step 1.5:** Fetch snapshot:
```bash
python3 ~/.openclaw/workspace/scripts/eth_market_analyzer.py
```
Extract: `market.last`, `market.change24h_pct`, `hourly_stats.trend_1h`, `hourly_stats.volatility_1h`, `orders`, `positions`, `balance`.

**Step 2:** Determine trend. Prefer 1h trend over 24h when they conflict.

**Step 3:** Count live `sell+short` and `buy+long` orders (`limit`, `sz=0.1`).

**Step 4:** Count 10x isolated ETH-USDT-SWAP positions.

**Step 5:** Calculate totals.
- `total = orders_count + positions_count`
- `remaining_capacity = floor(20 - total)`

**Step 6:** Cancel live orders where `|price - current| > 100`.
```bash
okx swap cancel --instId ETH-USDT-SWAP --ordId <id>
```

**Step 7:** Determine target distribution from the trend table.

**Step 8:** Place/replenish orders.
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
- Place command:
```bash
okx swap place --instId ETH-USDT-SWAP --tdMode isolated --side <sell|buy> --ordType limit --sz 0.1 --px=<px> --posSide <short|long> --tpTriggerPx=<tp> --tpOrdPx=-1 --slTriggerPx=<sl> --slOrdPx=-1
```

**Step 8.5:** Run `get_bills.py --today`. Filter `subType ∈ {4,6,110,111,112}` and `pnl < 0`. Increment `.trading_stopped` for each. If count reaches ≥ 3 → stop.

**Step 10:** Log and notify.
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

## Error Handling

- **Network/timeout:** Retry up to 3 times with 2s sleep. If all fail, stop and notify.
- **Rate limit (429):** Wait 10s, then retry.
- **Insufficient balance:** Skip order, log warning.
- **Order rejection:** Adjust price ±1 USDT and retry (max 2 retries).
- **Market anomaly:** Pause if price moves > 10% in 1 min or spread > 2 USDT.

## Quick Commands

- **Reset stop counter:** `echo 0 > ~/.openclaw/workspace/.trading_stopped`
- **Env check:** `bash ~/.openclaw/workspace/scripts/env-check.sh`
- **Cycle diagnostic:** `python3 ~/.openclaw/workspace/scripts/trade_cycle_check.py`

## Risk Warning

Leveraged trading carries significant risk. Monitor positions regularly. Only trade with funds you can afford to lose.
