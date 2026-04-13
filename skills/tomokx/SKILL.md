---
name: tomokx
description: "Automated ETH-USDT-SWAP grid trading on OKX. Triggers: start trading, run trading check, trading status, generate daily report, reset stop counter."
---

# 策略名称
ETH-USDT-SWAP 纯开仓网格交易策略 V1.0

# 执行节奏
手动触发

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

# Step 1~2 · 数据采集

统一调用 `fetch_all_data.py` 一次性并发拉取 Step 1~2 的所有数据：
```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\fetch_all_data.py"
```

**输出顶层字段：**
- `market`: 行情数据（`last`, `bidPx`, `askPx`, `spread`, `bidSz`, `askSz`, `change24h_pct`, `trend_1h`, `volatility_1h`）
- `risk`: 风控状态（`should_stop`, `daily_pnl`, `stopped_count`, `sl_count_today`）
- `orders`: 原始挂单列表
- `positions`: 持仓列表
- `exposure`: 汇总暴露（`total`, `remaining_capacity`, `short_orders`, `long_orders` 等）
- `strategy`: 策略建议（`trend`, `target_long`, `target_short`, `adjusted_gap`, `imbalance_score`）
- `far_orders`: 远离订单列表（偏离 >100 USDT）
- `history`: 近期历史盈亏分析
- `diagnostics`: 各子任务耗时与错误摘要，便于排查

> **失败处理**：若 `fetch_all_data.py` 输出包含 `error`，AI 应先查看 `diagnostics` 定位失败子任务，再**整体重跑一次**（最多 2 次，间隔 2 秒）。若仍失败，本次跳过并通知用户具体异常。

### 独立脚本参考（调试时可选）
- `fetch_market.py`：仅获取市场行情
- `fetch_orders.py` / `fetch_positions.py`：分别获取挂单/持仓
- `filter_far_orders.py <orders.json> <last_price>`：筛选远单
- `analyze_history.py`：分析历史盈亏
- `calc_strategy.py <market.json> <total> [exposure.json]`：单独计算策略建议

---

# Step 3 · AI 综合判断（核心）

先调用 `calc_recommendation.py` 获取**量化决策参考**，作为 AI 推理的基线：
```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\calc_recommendation.py" `
  "$env:TEMP\market.json" `
  "$env:TEMP\exposure.json" `
  "$env:TEMP\strategy.json" `
  "$env:TEMP\history.json"
```

**输出字段：**
- `recommendation`: `proceed`（正常执行） / `pause`（暂停） / `cancel_only`（仅撤远单） / `reduce_exposure`（降低仓位） / `rebuild`（重建网格）
- `confidence`: 置信度（0.0~0.99）
- `reason`: 人类可读的理由汇总
- `suggested_targets`: 脚本建议的修正后 target_long / target_short
- `suggested_gap`: 脚本建议的 gap
- `risk_flags`: 触发的风险标记列表（如 `liquidity_crisis`、`extreme_volatility`、`bad_regime`、`severe_imbalance`）
- `historical_context`: 当前趋势的历史胜率、盈亏、回撤等

> **AI 的任务不是从零推理，而是审核并决策**：
> 1. 阅读 `calc_recommendation.py` 的建议；
> 2. 结合你自己的判断：同意、修改或否决；
> 3. 若脚本建议 `pause` 或 `cancel_only` 但你认为可以执行，必须在最终决策中**明确说明理由**。

### AI 自主检查清单（复核用）
1. **趋势确认**：优先采用 `trend_1h`。当 `trend_1h` 与 `change24h_pct` 冲突时，以 `trend_1h` 为准。若 `volatility_1h > 25`，决定是否暂停或加大 gap；若 `< 5`，判断是否机会不足。
2. **流动性检查**：若 `spread > 2` 且 `bidSz < 10` 与 `askSz < 10` 同时成立，说明流动性枯竭，应直接暂停交易并通知用户。
3. **撤单决策**：`far_orders` 中偏离 >100 USDT 的订单，原则上全部撤销。
4. **最终决策**：综合脚本建议与以上检查，给出结论：**执行补单 / 仅撤销远单 / 本次跳过 / 降低仓位**，并说明理由。

若决策为 **执行补单**，调用 `calc_plan.py` 生成**建议草案**：
```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\calc_plan.py" `
  "$env:TEMP\market.json" `
  "$env:TEMP\exposure.json" `
  "$env:TEMP\strategy.json" `
  "$env:TEMP\far_orders.json" `
  "$env:TEMP\orders.json"
```

AI 必须基于以下数据对草案进行**审核、修改或否决**：

`calc_plan.py` 输出的 `reasoning` 字段会解释每侧的价格是如何选出的（内扩/外扩/从零建仓、哪些候选因何被拒绝），AI 应优先阅读该字段以理解草案意图，再进行以下复核：

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

AI 修改完成后，将最终计划保存为 `plan.json`（路径 `$env:TEMP\tomokx_plan.json`）。

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

调用 `execute_and_finalize.py` 一步完成订单执行、止损计数器更新、日志记录和通知发送：
```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\execute_and_finalize.py" ($env:TEMP + "\tomokx_plan.json")
```

**执行失败处理**（已由脚本内部处理）：
- 若输出中出现 **余额不足 / 价格已失效** 等错误：从失败订单开始，重新调用 `calc_plan.py` 生成修正计划（减少数量或调整价格），再次执行 `execute_and_finalize.py`。
- 若出现 **Rate limit (429)**：脚本内部等待 10 秒后自动重试一次。
- 若出现 **其他错误**：脚本内部跳过该单，记录原因到日志，继续执行剩余订单。
- 若 `stop_counter` 输出 `should_stop` 为 true，脚本以退出码 2 结束，应立即停止并通知用户。

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
