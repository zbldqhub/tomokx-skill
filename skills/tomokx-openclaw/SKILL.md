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
- **Max exposure**: 30 units total (`orders + positions`).
- **Per-side max**: 6 live orders per side.
- **Cancel threshold**: Orders > 100 USDT from current price are cancelled.
- **Daily loss limit**: Net realized P&L < -40 USDT for ETH-USDT-SWAP → stop.

### Trend Targets

趋势由 **4h 主趋势 + 1h 确认 + 15m 共振** 决定，不再只看 24h 涨跌幅。

| 4h 趋势 | 1h 趋势 | 15m 趋势 | 对齐度 | 最终趋势 | Long | Short |
|---------|---------|----------|--------|----------|------|-------|
| bullish | bullish | bullish | strong | Bullish  | 2    | 1     |
| bearish | bearish | bearish | strong | Bearish  | 1    | 2     |
| bullish | bullish | 任意    | moderate | Bullish | 2    | 1     |
| bearish | bearish | 任意    | moderate | Bearish | 1    | 2     |
| bullish | sideways| bullish | mixed  | Sideways | 1    | 1     |
| bullish | bearish | bearish | weak   | Sideways | 1    | 1     |
| 任意     | 任意     | 任意     | mixed/weak | Sideways | 1    | 1     |

**时间框架冲突时的处理**：
- `strong` / `moderate`：正常执行对应 target
- `mixed` / `weak`：压缩 target（两侧各 -1），降低暴露，等待方向明确

### Funding Rate 纠偏

`fetch_all_data.py` 同时读取 ETH-USDT-SWAP 的 funding rate：
- `funding_rate > 0.01%` → `short_favored` → short target +1，long target -1（如有空间）
- `funding_rate < -0.01%` → `long_favored` → long target +1，short target -1（如有空间）
- 在 `-0.01% ~ +0.01%` 之间 → `neutral`，不影响 target

### Dynamic Gap

| Total Positions | Gap |
| --------------- | --- |
| 0               | 3   |
| 1               | 4   |
| 2               | 5   |
| 3               | 6   |
| 4               | 7   |
| 5-6             | 8   |
| 7-10            | 9   |
| 11-15           | 10  |
| 16-30           | 12  |

**Gap adjustments:** volatility > 15 → +2~4; > 25 → +4~6 or pause. Spread > 0.5 → +1.

---

# Step 1~2 · 数据采集

统一调用 `fetch_all_data.py` 一次性并发拉取 Step 1~2 的所有数据：
```bash
python3 ~/.openclaw/workspace/scripts/fetch_all_data.py
```

**输出顶层字段：**
- `market`: 行情数据（`last`, `bidPx`, `askPx`, `spread`, `bidSz`, `askSz`, `change24h_pct`）
  - 多时间框架趋势：`trend_4h`, `trend_1h`, `trend_15m`, `trend_alignment`, `primary_trend`
  - 波动率：`volatility_1h`（下单和 gap 调整主要依据）
  - 资金费率：`funding_rate`, `funding_bias`
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
```bash
python3 ~/.openclaw/workspace/scripts/calc_recommendation.py /tmp/market.json /tmp/exposure.json /tmp/strategy.json /tmp/history.json
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
> 2. 阅读 `calc_plan.py` 生成的草案及其 `reasoning`；
> 3. 结合两者判断：同意、修改或否决；
> 4. 若脚本建议 `pause` 或 `cancel_only` 但你认为可以执行，必须在最终决策中**明确说明理由**。
>
> `calc_plan.py` 基于原始 `strategy.json` 生成草案，AI 应在 Step 3a 与 3b 之间做出最终策略决策，必要时直接修改 `strategy.json` 或最终 `plan.json`。

### AI 自主检查清单（复核用）
1. **趋势确认**：优先采用 `trend_1h`。当 `trend_1h` 与 `change24h_pct` 冲突时，以 `trend_1h` 为准。若 `volatility_1h > 25`，决定是否暂停或加大 gap；若 `< 5`，判断是否机会不足。
2. **流动性检查**：若 `spread > 2` 且 `bidSz < 10` 与 `askSz < 10` 同时成立，说明流动性枯竭，应直接暂停交易并通知用户。
3. **撤单决策**：`far_orders` 中偏离 >100 USDT 的订单，原则上全部撤销。
4. **最终决策**：综合脚本建议与以上检查，给出结论：**执行补单 / 仅撤销远单 / 本次跳过 / 降低仓位**，并说明理由。

若决策为 **执行补单**，调用 `calc_plan.py` 生成**建议草案**：
```bash
python3 ~/.openclaw/workspace/scripts/calc_plan.py \
  <market.json> <exposure.json> <strategy.json> <far_orders.json> <orders.json>
```

AI 必须基于以下数据对草案进行**审核、修改或否决**：

`calc_plan.py` 输出的 `reasoning` 字段会解释每侧的价格是如何选出的（内扩/外扩/从零建仓、哪些候选因何被拒绝），AI 应优先阅读该字段以理解草案意图，再进行以下复核：

### AI 决策权重（优先级从高到低）
1. **趋势对齐与 funding 纠偏** > **暴露失衡控制** > **网格结构完整性** > **target 数量匹配**
   - 当 `trend_alignment` 为 `mixed` 或 `weak` 时，脚本已经自动压缩了 target，AI 应更加谨慎，除非有强烈的内扩机会。
   - 若 `funding_bias` 与当前 primary_trend 方向相反（如 4h bullish 但 funding 强烈 short_favored），优先服从 funding 信号，减少逆势侧的 target。
2. **暴露失衡控制**
   - 当 `imbalance_score >= 3` 或单侧总暴露（orders + positions）显著高于另一侧时，**谨慎增加重侧的订单**，即使 boost 触发了补单建议。
3. **内扩补单优先于外扩**
   - 内扩（`expansion_type=inner`）填补当前价与最近网格之间的空洞，战术价值高，优先保留。
   - 外扩（`expansion_type=outer`）只是拉长网格尾巴，若重侧已失衡或趋势对齐度弱，**可直接删除**。
4. **有效覆盖距离**
   - 理想的 placement 应落在 `current_price ± gap*2` 范围内。超出此范围的外扩单，在 imbalance 或 weak alignment 场景下价值较低。

### 逐单复核 Checklist
对 `reasoning` 中每侧的每一单，依次检查：

| 检查项 | 通过标准 | 未通过时的处理 |
|--------|----------|----------------|
| **趋势对齐度** | `trend_alignment` 为 `strong` 或 `moderate` | `mixed`/`weak` 时，重侧外扩 → **删除**；轻侧内扩可保留但需说明理由 |
| **funding 方向** | 新增订单方向与 `funding_bias` 不严重冲突 | 若 funding 强烈指向另一侧，逆势外扩 → **删除** |
| **内扩还是外扩？** | `expansion_type=inner` 优先 | `outer` 且重侧失衡或对齐度弱 → **删除** |
| **是否加剧 imbalance？** | 重侧（暴露多的一侧）新增订单需谨慎 | imbalance >= 3 且是重侧外扩 → **删除** |
| **target 偏离度** | `target_deviation <= 0` 最佳 | `target_deviation > 0`（已有订单超过 target）且新增为外扩 → **删除** |
| **hole 大小** | `hole_to_current` 在 `gap` 到 `gap*2` 之间最理想 | `hole_to_current > gap*3` 说明价格已远离该侧网格，此时外扩意义有限 |
| **gap 是否需要动态调整** | 单侧严重失衡或市场异常时，AI 可增大/减小特定订单的间距 | 直接修改 `px` |
| **TP/SL 是否合理** | `volatility_1h` 边界或特殊风险时调整 | 直接修改 `tpTriggerPx` / `slTriggerPx` |
| **前置验证** | Long: `tp > px`, `sl < px`<br>Short: `tp < px`, `sl > px` | 未通过则修改参数或 **删除** |
| **总暴露上限** | 补单后 `total <= 30`，per-side <= 6 | 删减订单 |

### 典型场景的默认决策
- **重侧内扩 + 轻侧内扩** → 两单都保留（结构合理）
- **重侧外扩 + 轻侧内扩** → 保留轻侧内扩，删除重侧外扩
- **两侧均为外扩** → 保留更靠近 current_price 的一侧内层单，删除远端外扩；或视 imbalance 决定
- **calc_recommendation 建议 pause / cancel_only** → 原则上服从；若你判断可以执行，必须在最终决策中**明确说明理由**

AI 修改完成后，将最终计划保存为 `plan.json`（路径 `/tmp/tomokx_plan.json`）。

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
```bash
python3 ~/.openclaw/workspace/scripts/execute_and_finalize.py /tmp/tomokx_plan.json
```

**执行失败处理**（已由脚本内部处理）：
- 若输出中出现 **余额不足 / 价格已失效** 等错误：从失败订单开始，重新调用 `calc_plan.py` 生成修正计划（减少数量或调整价格），再次执行 `execute_and_finalize.py`。
- 若出现 **Rate limit (429)**：脚本内部等待 10 秒后自动重试一次。
- 若出现 **其他错误**：脚本内部跳过该单，记录原因到日志，继续执行剩余订单。


---

## Learning & Optimization

### Decision Log

每次执行 `execute_and_finalize.py` 后，系统会自动在 `~/.openclaw/workspace/decisions.jsonl` 写入一条决策记录，包含：
- `market_state`: 趋势、价格、波动率
- `strategy_params`: gap、target_long、target_short
- `actual_actions`: 实际撤销/新建数量、long/short 价格、expansion_type
- `baseline_pnl`: 决策时刻的当日已实现盈亏
- `outcome_pnl`: 下次执行时回填的盈亏 delta（当前 daily_pnl - baseline_pnl）

### 分析历史决策

每周（或积累 20+ 条闭合记录后）运行一次：
```bash
python3 ~/.openclaw/workspace/scripts/analyze_decisions.py
```

输出示例：
```json
{
  "total_decisions": 42,
  "closed_decisions": 38,
  "top_performers": [
    {
      "trend": "bullish",
      "gap": "14",
      "target_long": 0,
      "target_short": 1,
      "long_expansion": "",
      "short_expansion": "inner",
      "count": 5,
      "avg_pnl": 0.89,
      "win_rate": 0.8
    }
  ],
  "gap_comparison": {
    "14": {"count": 15, "avg_pnl": 0.42, "win_rate": 0.67},
    "12": {"count": 12, "avg_pnl": -0.18, "win_rate": 0.42}
  },
  "recommendations": [
    "Best performing setup: trend=bullish gap=14 targets=(0,1) avg_pnl=0.89 win_rate=0.8",
    "Best gap value so far: 14 (avg_pnl=0.42, n=15)"
  ]
}
```

AI 应阅读该报告并结合最新市场状态，判断是否调整 `config.py` 中的 gap 表或默认 target 分配。

### 订单生命周期跟踪

每次成功下单后，系统会在 `~/.openclaw/workspace/order_tracking.jsonl` 记录该订单的元数据（价格、TP/SL、expansion_type、趋势、gap）。

每周运行一次 `analyze_trades.py`，通过 OKX bills API 匹配每个订单的实际平仓盈亏：
```bash
python3 ~/.openclaw/workspace/scripts/analyze_trades.py
```

输出示例：
```json
{
  "tracking_total": 28,
  "closed_count": 22,
  "open_or_unfilled_count": 6,
  "top_setups": [
    {
      "trend": "bullish",
      "gap": "14",
      "expansion_type": "inner",
      "posSide": "short",
      "count": 5,
      "avg_pnl": 0.92,
      "win_rate": 0.8
    }
  ],
  "bottom_setups": [
    {
      "trend": "bullish",
      "gap": "14",
      "expansion_type": "outer",
      "posSide": "long",
      "count": 4,
      "avg_pnl": -0.34,
      "win_rate": 0.25
    }
  ],
  "recommendations": [
    "Best setup: short inner in bullish with gap=14 -> avg_pnl=0.92 win_rate=0.8 (n=5)",
    "Worst setup: long outer in bullish with gap=14 -> avg_pnl=-0.34 win_rate=0.25 (n=4); consider avoiding"
  ]
}
```

**优化闭环**：
1. 阅读 `analyze_trades.py` 的 per-order 盈亏数据，找出高胜率/正期望的 `(trend, gap, expansion_type, posSide)` 组合
2. 对比 `analyze_decisions.py` 的粗粒度归因，确认方向
3. AI 结合当前市场状态，决定是否微调 `config.py` 的 gap 表或 SKILL.md 的默认 target 分配
4. 继续执行，积累更多订单数据，验证调整效果

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


- **Env check:** `bash ~/.openclaw/workspace/scripts/env-check.sh`
- **Cycle diagnostic:** `python3 ~/.openclaw/workspace/scripts/trade_cycle_check.py`

## Risk Warning

Leveraged trading carries significant risk. Monitor positions regularly. Only trade with funds you can afford to lose.
