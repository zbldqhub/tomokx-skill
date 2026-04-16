---
name: tomokx
description: "ETH-USDT-SWAP grid trading strategy core rules and AI decision boundaries."
---

# ETH-USDT-SWAP 纯开仓网格交易策略 V2.0

## Core Strategy

- **Pure opening grid**: Only `buy+long` and `sell+short`. Closing is handled by per-order TP/SL.
- **Max exposure**: 30 units total (`orders + positions`).
- **Per-side max**: 6 live orders per side.
- **Cancel threshold**: Orders > 100 USDT from current price are cancelled.
- **Daily loss limit**: Net realized P&L < -40 USDT for ETH-USDT-SWAP → stop.

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
| bullish | bullish | bullish | strong | Bullish | 4 | 1 |
| bearish | bearish | bearish | strong | Bearish | 1 | 4 |
| bullish | bullish | 任意 | moderate | Bullish | 3 | 1 |
| bearish | bearish | 任意 | moderate | Bearish | 1 | 3 |
| 其他组合 | - | - | mixed/weak | Sideways | 0 | 0 |

- `strong` / `moderate`：正常执行对应 target
- `mixed` / `weak`：**两侧 target 各 -1**（最低为 0），降低暴露，等待方向明确
  - **若同时处于 `sideways`**：两侧 target 强制归零，禁止任何 outer expansion

### Funding Rate 纠偏
- `funding_rate > 0.01%` → `short_favored` → short target +1，long target -1（如有空间）
- `funding_rate < -0.01%` → `long_favored` → long target +1，short target -1（如有空间）
- `-0.01% ~ +0.01%` → `neutral`，不影响 target

---

## Dynamic Gap

### Base Gap Table (hard floor when ATR is low)

| Total Positions | Gap |
| --------------- | --- |
| 0 | 5 |
| 1 | 6 |
| 2 | 7 |
| 3 | 8 |
| 4 | 9 |
| 5-6 | 10 |
| 7-10 | 11 |
| 11-15 | 12 |
| 16-30 | 14 |

**ATR 动态主导:**
- `adjusted_gap = max(base_gap, round(ATR(14) × 0.8))`
  - Low volatility → gap shrinks back to base table (more trades)
  - High volatility → gap widens automatically to protect capital
  - Soft cap: `adjusted_gap ≤ base_gap + 6` to prevent runaway gaps

**Gap adjustments:**
- `volatility_1h > 15` → +2
- `volatility_1h > 25` → +4
- `spread > 0.5` → +1

---

## TP / SL 规则

- **TP**: `max(12, int(gap × 1.5))`
- **SL**: `max(20, int(gap × 2.5))`
- 波动率加成:
  - `volatility_1h > 25`: TP +5, SL +8
  - `volatility_1h > 15`: TP +3, SL +5
  - `volatility_1h > 10`: TP +1, SL +3

---

## 默认决策规则（最高优先级）

以下规则**优先于 `calc_plan.py` 的草案**，AI 必须逐条核对：

1. **重侧内扩 + 轻侧内扩** → 两单都保留（结构合理）
2. **重侧外扩 + 轻侧内扩** → **删除重侧外扩**，保留轻侧内扩
3. **两侧均为外扩** → 保留更靠近 `current_price` 的一侧内层单，删除远端外扩；若两侧对齐度 `mixed`/`weak`，两侧外扩均可删除
4. **`trend_alignment` 为 `mixed`/`weak`** → 重侧外扩 **必须删除**；轻侧内扩可保留但需说明理由
5. **`imbalance_score >= 3` 且是重侧外扩** → **必须删除**
6. **`recommendation = pause / cancel_only`** → 原则上服从；若你判断可以执行，必须在最终决策中**明确说明理由**
7. **远单（>100 USDT）** → 原则上全部撤销

### 逐单复核 Checklist

- [ ] **趋势对齐度**：`mixed`/`weak` 时重侧外扩 → **删除**
- [ ] **内扩/外扩**：`inner` 优先保留；`outer` 且重侧失衡/对齐度弱 → **删除**
- [ ] **是否加剧 imbalance**：`imbalance_score >= 3` 且重侧新增 → **删除**
- [ ] **target 偏离度**：`existing_count > target` 且新增为外扩 → **删除**
- [ ] **有效覆盖距离**：理想 placement 应落在 `current_price ± gap*2` 范围内；超出且为外扩 → **删除**
- [ ] **TP 合理性**：TP 与当前价的距离 **不应 < gap**，尤其在高波动时
- [ ] **前置验证**：Long `tp > px && sl < px`；Short `tp < px && sl > px`
- [ ] **总暴露上限**：补单后 `total <= 30`，per-side <= 6

---

## 离线分析与参数优化

每周运行一次分析脚本生成周报，**由 AI 阅读并决定是否微调 `config.py`**：

### AI 调参安全边界
1. **可调参数**：`base_gap_table`、`volatility_*_boost` 阈值、`trend_targets`（Long/Short 分配）
2. **禁止触碰**：`max_total`、`daily_loss_limit`、`per-side max`、`cancel_threshold`
3. **调整幅度**：单次变动 **≤ ±2**（如 gap 不能从 8 跳到 15）
4. **调参频率**：**≥ 7 天一次**，禁止每次交易后都改
5. **必须记录**：任何修改都要写入 `~/.openclaw/workspace/tuning_log.jsonl`，包含修改原因、旧值、新值、报告摘要

AI 在阅读周报后，若某参数的胜率/盈亏数据呈现一致性规律（至少 10+ 条闭合记录），可在上述边界内直接修改 `config.py`。

---

## Risk Warning

Leveraged trading carries significant risk. Monitor positions regularly. Only trade with funds you can afford to lose.
