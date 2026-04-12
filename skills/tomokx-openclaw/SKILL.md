---
name: tomokx-openclaw
description: "Automated ETH-USDT-SWAP grid trading on OKX. Triggers: start trading, run trading check, trading status, generate daily report, reset stop counter."
metadata:
  {"openclaw": {"emoji": "📈"}}
---

# 策略名称
ETH-USDT-SWAP 纯开仓网格交易策略 V1.0

# 执行节奏
每 30 分钟触发一次

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

# Step 1 · 行情数据采集

调用 `fetch_market.py` 获取 ETH-USDT-SWAP 市场行情：
```bash
python3 ~/.openclaw/workspace/scripts/fetch_market.py
```

**输出字段：**
- `last`: 当前价格
- `bidPx` / `askPx`: 买一/卖一价
- `spread`: 买卖价差（askPx - bidPx）
- `change24h_pct`: 24h 涨跌幅
- `trend_1h`: 1h 趋势（bullish / bearish / sideways）
- `volatility_1h`: 1h 波动率

---

# Step 2 · 风险与仓位数据采集

调用 `check_risk.py` 获取风控状态：
```bash
python3 ~/.openclaw/workspace/scripts/check_risk.py
```
**输出字段：** `stopped_count`、`daily_pnl`、`sl_count_today`。  
**硬规则**：若 `stopped_count >= 3` 或 `daily_pnl < -40`，立即停止并通知用户。

调用 `fetch_orders.py` 和 `fetch_positions.py` 获取原始挂单与持仓：
```bash
python3 ~/.openclaw/workspace/scripts/fetch_orders.py
python3 ~/.openclaw/workspace/scripts/fetch_positions.py
```

调用 `calc_exposure.py` 计算汇总数据：
```bash
python3 ~/.openclaw/workspace/scripts/calc_exposure.py <orders.json> <positions.json>
```
**输出字段：** `short_orders`、`long_orders`、`orders_count`、`positions_count`、`total`、`remaining_capacity`。

调用 `calc_strategy.py` 计算策略建议：
```bash
python3 ~/.openclaw/workspace/scripts/calc_strategy.py <market.json> <total>
```
**输出字段：** `trend`、`target_long`、`target_short`、`adjusted_gap`。

调用 `filter_far_orders.py` 筛选远离订单：
```bash
python3 ~/.openclaw/workspace/scripts/filter_far_orders.py <orders.json> <last_price>
```
**输出字段：** `far_orders`（偏离 >100 USDT 的订单列表）。

调用 `analyze_history.py` 分析近期历史盈亏：
```bash
python3 ~/.openclaw/workspace/scripts/analyze_history.py
```
**输出字段：**
- `total_pnl_7d` / `total_pnl_30d`: 近 7/30 天总盈亏
- `win_days_7d` / `loss_days_7d`: 近 7 天盈利/亏损天数
- `avg_daily_pnl_7d`: 近 7 天日均盈亏
- `max_daily_loss_7d`: 近 7 天最大单日亏损
- `trend_performance_7d`: 不同趋势下的盈亏表现
- `recommendation`: 策略优化建议

> **脚本失败处理**：若 Step 1~2 中任一脚本输出包含 `error` 或执行超时，AI 应先尝试**重跑一次该脚本**（最多 2 次，间隔 2 秒）。若仍失败，本次跳过并通知用户具体异常。

---

# Step 3 · AI 综合判断（核心）

基于以上数据，你作为交易 AI 需要推理：

1. **趋势确认**：优先采用 `trend_1h`。当 `trend_1h` 与 `change24h_pct` 冲突时，以 `trend_1h` 为准。若 `volatility_1h > 25`，决定是否暂停或加大 gap；若 `< 5`，判断是否机会不足。
2. **目标与失衡**：当前挂单/持仓分布是否与 `target_long` / `target_short` 匹配？是否存在单侧严重失衡需要优先补单？
3. **异常判断**：是否存在价格跳空、spread > 2 USDT 等市场异常？是否应整体重建网格而非简单补单？
4. **撤单决策**：`far_orders` 中偏离 >100 USDT 的订单，原则上全部撤销。
5. **历史盈亏优化**：参考 `analyze_history.py` 输出的 `trend_performance_7d` 和 `recommendation`。若某类趋势近期持续亏损，AI 可决定降低该类行情下的开仓数量、加大 gap 或直接跳过。
6. **最终决策**：综合以上五点，给出最终结论：**执行补单 / 仅撤销远单 / 本次跳过**，并说明理由。

若决策为 **执行补单**，先调用 `calc_plan.py` 生成**建议草案**：
```bash
python3 ~/.openclaw/workspace/scripts/calc_plan.py \
  <market.json> <exposure.json> <strategy.json> <far_orders.json> <orders.json>
```

AI 必须基于以下数据对草案进行**审核、修改或否决**：

1. **价格布局是否合理**
   - `calc_plan.py` 已自动生成**内扩**和**外扩**候选方案，并优先选择离当前价最近的有效位置。
   - AI 检查：当价格明显 moved inside grid 时，草案是否在内侧生成了补单？若布局仍不符合当前市场结构，AI 可直接修改 `px`。

2. **gap 是否需要动态调整**
   - 单侧严重失衡或市场异常时，AI 可增大/减小特定订单的间距。

3. **TP/SL 是否合理**
   - `volatility_1h` 处于边界值或存在特殊风险时，AI 可调整 `tpTriggerPx` 和 `slTriggerPx`。

4. **数量是否正确**
   - per-side 是否超过 4？总暴露是否会超过 20？剩余容量是否足够？
   - 若草案计算有误，AI 可直接删减订单。

5. **前置验证（逐单检查）**
   - Long 单必须 `tpTriggerPx > px` 且 `slTriggerPx < px`
   - Short 单必须 `tpTriggerPx < px` 且 `slTriggerPx > px`
   - 未通过验证的订单必须修改参数或删除。

AI 修改完成后，将最终计划保存为 `plan.json`（路径 `/tmp/tomokx_plan.json`）：
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
  ],
  "summary": {
    "trend": "bullish",
    "price": "2217.03",
    "orders": "8",
    "positions": "6.4",
    "total": "14.4",
    "actions": "Cancelled 1 far order, placed 1 sell+short @ 2301.75"
  }
}
```

---

# Step 4 · 执行交易计划

调用 `execute_orders.py` 执行 AI 审核通过的 `plan.json`：
```bash
python3 ~/.openclaw/workspace/scripts/execute_orders.py /tmp/tomokx_plan.json
```

**执行失败处理**：
- 若输出中出现 **余额不足 / 价格已失效** 等错误：从失败订单开始，重新调用 `calc_plan.py` 生成修正计划（减少数量或调整价格），再次执行。
- 若出现 **Rate limit (429)**：等待 10 秒后整体重试一次。
- 若出现 **其他错误**：跳过该单，记录原因到日志，继续执行剩余订单。

调用 `update_stop_counter.py` 更新止损计数器：
```bash
python3 ~/.openclaw/workspace/scripts/update_stop_counter.py
```
若输出 `should_stop` 为 true，立即停止并通知用户。

调用 `log_trade.py` 记录日志：
```bash
python3 ~/.openclaw/workspace/scripts/log_trade.py \
  --trend "<trend>" \
  --price "<price>" \
  --orders "<orders>" \
  --positions "<positions>" \
  --total "<total>" \
  --actions "<actions>"
```

最后通知用户执行摘要：
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
