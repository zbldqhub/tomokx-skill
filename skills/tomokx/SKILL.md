---
name: tomokx
description: "Automated ETH-USDT-SWAP grid trading on OKX. Triggers: start trading, run trading check, trading status, generate daily report, reset stop counter."
---

# 策略名称
ETH-USDT-SWAP 纯开仓网格交易策略 V2.0

# 执行节奏
手动触发

---

## Core Strategy

- **Pure opening grid**: Only `buy+long` and `sell+short`. Closing is handled by per-order TP/SL.
- **Max exposure**: 30 units total (`orders + positions`).
- **Per-side max**: 6 live orders per side.
- **Cancel threshold**: Orders > 100 USDT from current price are cancelled.
- **Daily loss limit**: Net realized P&L < -40 USDT for ETH-USDT-SWAP → stop.

`$WORKSPACE` = `C:\Users\ldq\.openclaw\workspace`

---

## AI 决策边界（必读）

### AI 的任务
AI **不是交易员**，而是**审核员与仲裁者**：
1. 读取脚本的量化建议；
2. 检查是否触发下文的"默认决策"或"禁止事项"；
3. 若脚本建议与默认决策冲突，**优先执行默认决策**；
4. 仅在没有现成规则覆盖的边缘 case 中，AI 才可自主判断，且必须在最终输出中写明理由。

### AI 禁止事项
- **禁止**在 `recommendation = pause` 时未经说明理由就强行开仓。
- **禁止**增加重侧（暴露多的一侧）的外扩订单，除非 `trend_alignment = strong` 且 funding 同向。
- **禁止**把 TP 设在当前价 ±3 USDT 以内（高波动下会被噪音扫掉）。
- **禁止**让 AI 修改 `max_total`、`daily_loss_limit`、`per-side max`、`cancel_threshold` 等硬风控参数。

---

## 趋势判定

由 **4h 主趋势 + 1h 确认 + 15m 共振** 决定：

| 4h | 1h | 15m | 对齐度 | 最终趋势 | Long | Short |
|----|----|-----|--------|----------|------|-------|
| bullish | bullish | bullish | strong | Bullish | 2 | 1 |
| bearish | bearish | bearish | strong | Bearish | 1 | 2 |
| bullish | bullish | 任意 | moderate | Bullish | 2 | 1 |
| bearish | bearish | 任意 | moderate | Bearish | 1 | 2 |
| 其他组合 | - | - | mixed/weak | Sideways | 1 | 1 |

- `strong` / `moderate`：正常执行对应 target
- `mixed` / `weak`：**两侧 target 各 -1**（最低为 0），降低暴露，等待方向明确

### Funding Rate 纠偏
- `funding_rate > 0.01%` → `short_favored` → short target +1，long target -1（如有空间）
- `funding_rate < -0.01%` → `long_favored` → long target +1，short target -1（如有空间）
- `-0.01% ~ +0.01%` → `neutral`，不影响 target

---

## Dynamic Gap

| Total Positions | Gap |
| --------------- | --- |
| 0 | 3 |
| 1 | 4 |
| 2 | 5 |
| 3 | 6 |
| 4 | 7 |
| 5-6 | 8 |
| 7-10 | 9 |
| 11-15 | 10 |
| 16-30 | 12 |

**Gap adjustments:**
- `volatility_1h > 15` → +2~4
- `volatility_1h > 25` → +4~6 **或 pause**
- `spread > 0.5` → +1

---

## Step 1~2 · 数据采集

统一调用 `fetch_all_data.py` 一次性并发拉取所有数据：
```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\fetch_all_data.py"
```

**失败处理**：若输出包含 `error`，先查看 `diagnostics` 定位失败子任务，再整体重跑一次（最多 2 次，间隔 2 秒）。若仍失败，本次跳过并通知用户具体异常。

---

## Step 3 · AI 综合判断（核心）

### Step 3a · 典型场景默认决策（最高优先级）
以下规则**优先于 `calc_plan.py` 的草案**，AI 必须逐条核对：

1. **重侧内扩 + 轻侧内扩** → 两单都保留（结构合理）
2. **重侧外扩 + 轻侧内扩** → **删除重侧外扩**，保留轻侧内扩
3. **两侧均为外扩** → 保留更靠近 `current_price` 的一侧内层单，删除远端外扩；若两侧对齐度 `mixed`/`weak`，两侧外扩均可删除
4. **`trend_alignment` 为 `mixed`/`weak`** → 重侧外扩 **必须删除**；轻侧内扩可保留但需说明理由
5. **`imbalance_score >= 3` 且是重侧外扩** → **必须删除**
6. **`recommendation = pause / cancel_only`** → 原则上服从；若你判断可以执行，必须在最终决策中**明确说明理由**
7. **远单（>100 USDT）** → 原则上全部撤销

### Step 3b · 量化决策基线
调用 `calc_recommendation.py`：
```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\calc_recommendation.py" `
  "$env:TEMP\market.json" "$env:TEMP\exposure.json" `
  "$env:TEMP\strategy.json" "$env:TEMP\history.json"
```

阅读其输出的 `recommendation`、`confidence`、`suggested_targets`、`suggested_gap`、`risk_flags`。

### Step 3c · 生成并审核草案
若默认决策允许开仓，调用 `calc_plan.py`：
```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\calc_plan.py" `
  "$env:TEMP\market.json" "$env:TEMP\exposure.json" `
  "$env:TEMP\strategy.json" "$env:TEMP\far_orders.json" `
  "$env:TEMP\orders.json"
```

### Step 3d · 逐单复核 Checklist
对 `calc_plan.py` 输出的每一单，依次检查：

- [ ] **趋势对齐度**：`mixed`/`weak` 时重侧外扩 → **删除**
- [ ] **内扩/外扩**：`inner` 优先保留；`outer` 且重侧失衡/对齐度弱 → **删除**
- [ ] **是否加剧 imbalance**：`imbalance_score >= 3` 且重侧新增 → **删除**
- [ ] **target 偏离度**：`existing_count > target` 且新增为外扩 → **删除**
- [ ] **有效覆盖距离**：理想 placement 应落在 `current_price ± gap*2` 范围内；超出且为外扩 → **删除**
- [ ] **TP 合理性**：TP 与当前价的距离 **不应 < gap**，尤其在高波动时
- [ ] **前置验证**：Long `tp > px && sl < px`；Short `tp < px && sl > px`
- [ ] **总暴露上限**：补单后 `total <= 30`，per-side <= 6

AI 修改完成后，将最终计划保存为 `$env:TEMP\tomokx_plan.json`。

```json
{
  "cancellations": [],
  "placements": [
    {
      "instId": "ETH-USDT-SWAP",
      "tdMode": "isolated",
      "side": "buy",
      "ordType": "limit",
      "sz": "0.1",
      "px": "2345.41",
      "posSide": "long",
      "tpTriggerPx": "2373.41",
      "slTriggerPx": "2230.41"
    }
  ],
  "summary": {
    "trend": "bearish",
    "price": "2350.11",
    "orders": "2",
    "positions": "6.4",
    "total": "8.4",
    "actions": "Placed 1 buy+long @ 2345.41. Deleted 1 short outer expansion due to weak alignment."
  }
}
```

---

## Step 4 · 执行交易计划

调用 `execute_and_finalize.py`：
```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\execute_and_finalize.py" `
  ("$env:TEMP" + "\tomokx_plan.json")
```

**执行失败处理**（脚本内部已处理部分）：
- **余额不足 / 价格已失效**：从失败订单开始，重新调用 `calc_plan.py` 生成修正计划，再次执行。
- **Rate limit (429)**：等待 10s 后自动重试一次。
- **其他错误**：跳过该单，记录原因到日志，继续执行剩余订单。

---

## 离线分析与参数优化

每周运行以下脚本生成周报，**由 AI 阅读并决定是否微调 `config.py`**：

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\analyze_decisions.py"
python "$env:USERPROFILE\.openclaw\workspace\scripts\analyze_trades.py"
```

### AI 调参安全边界
1. **可调参数**：`base_gap_table`、`volatility_*_boost` 阈值、`trend_targets`（Long/Short 分配）
2. **禁止触碰**：`max_total`、`daily_loss_limit`、`per-side max`、`cancel_threshold`
3. **调整幅度**：单次变动 **≤ ±2**（如 gap 不能从 8 跳到 15）
4. **调参频率**：**≥ 7 天一次**，禁止每次交易后都改
5. **必须记录**：任何修改都要写入 `~/.openclaw/workspace/tuning_log.jsonl`，包含修改原因、旧值、新值、报告摘要

AI 在阅读周报后，若某参数的胜率/盈亏数据呈现一致性规律（至少 10+ 条闭合记录），可在上述边界内直接修改 `config.py`。

---

## CLI Reference

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

- **Env check (PowerShell):** `$WORKSPACE/scripts/env-check.ps1`
- **Env check (Git Bash):** `bash $WORKSPACE/scripts/env-check.sh`
- **Cycle diagnostic:** `python $WORKSPACE/scripts/trade_cycle_check.py`

## Risk Warning

Leveraged trading carries significant risk. Monitor positions regularly. Only trade with funds you can afford to lose.
