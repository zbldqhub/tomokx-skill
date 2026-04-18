# TOMOKX AI Execution Protocol

This document defines how any AI agent (including openclaw) should execute the `tomokx` ETH-USDT-SWAP grid trading skill.

## Core Principle

**The AI is the arbiter, not the trader.** Scripts are only "hands" for data collection and execution. All trading decisions must be made by the AI after reading `SKILL.md` and applying `rules.json`.

**The AI must act autonomously.** Do not ask the user for confirmation on tactical decisions (e.g., whether to place/cancel an order, which order to keep, how to handle minor imbalance). Only stop and notify the user in extreme cases: system failure, missing critical data, unresolved rule conflicts, or hard stop limits triggered.

---

## Forbidden Behaviors

1. **Never** call `run_trade_cycle.py` as a single black-box step. It exists only for human convenience and legacy automation.
2. **Never** place an order when `recommendation = pause` without explicitly stating the justification in the final output.
3. **Never** add heavy-side outer expansion unless `trend_alignment = strong` **AND** funding rate aligns with the position side.
4. **Never** place TP within `tp_forbidden_zone` USDT of the current price (default: 3.0).
5. **Never** modify hard risk parameters (`max_total`, `daily_loss_limit`, `per-side max`, `cancel_threshold`).

---

## Available Tools

All tools reside in `$WORKSPACE/scripts/`.

### 1. Data Collection
```bash
python $WORKSPACE/scripts/fetch_all_data.py
```
**Output**: JSON with `market`, `exposure`, `strategy`, `far_orders`, `orders`, `positions`, `history`, `risk`.

**Failure handling**:
- If output contains `"error"`, inspect `diagnostics`.
- Retry the whole script up to 2 times with 2s sleep.
- If still failing, stop and notify the user.

### 2. Quantitative Recommendation
```bash
python $WORKSPACE/scripts/calc_recommendation.py <market.json> <exposure.json> <strategy.json> <history.json>
```
**Output**: `recommendation`, `confidence`, `suggested_targets`, `suggested_gap`, `risk_flags`.

### 3. Draft Plan Generation
```bash
python $WORKSPACE/scripts/calc_plan.py <market.json> <exposure.json> <strategy.json> <far_orders.json> <orders.json>
```
**Output**: `cancellations`, `placements`, `reasoning`, `summary`.

### 4. Rule-Based AI Review (Optional but recommended)
```bash
python $WORKSPACE/scripts/ai_review.py <plan.json> <market.json> <exposure.json> <strategy.json> <rec.json>
```
This script applies hard rules from `rules.json` and auto-detects the LLM backend (openclaw gateway or local kimi CLI). It can be used as a **first-pass filter**, but the AI must still independently verify the result against `SKILL.md`.

### 5. Execution
```bash
python $WORKSPACE/scripts/execute_and_finalize.py <plan.json>
```
**Input**: Final reviewed plan JSON file path.

---

## Execution Sequence

### Step 1: Fetch Data
Call `fetch_all_data.py`. Extract:
- `market.last` (current price)
- `strategy.trend`, `strategy.trend_alignment`, `strategy.adjusted_gap`
- `exposure.total`, `exposure.remaining_capacity`, `exposure.long_orders`, `exposure.short_orders`
- `risk.should_stop`, `risk.daily_pnl`

If `risk.should_stop == true`, **halt immediately** and notify the user.

### Step 2: Quantitative Baseline
Call `calc_recommendation.py`. Read `recommendation` and `confidence`.

### Step 3: Generate Draft
Call `calc_plan.py`. Save the output as the **draft plan**.

### Step 4: AI Review (MANDATORY)
For every placement in the draft plan, run the **Step 3d Checklist** from `SKILL.md`:

- [ ] **Trend alignment**: `mixed`/`weak` + heavy-side outer → DELETE
- [ ] **Inner/Outer**: `inner` preferred; `outer` on heavy side with imbalance/weak alignment → DELETE
- [ ] **Imbalance**: `imbalance_score >= 3` + heavy-side new order → DELETE
- [ ] **Target deviation**: `existing_count > target` + outer → DELETE
- [ ] **Coverage distance**: placement should be within `current_price ± gap*2`; outer beyond this → DELETE
- [ ] **TP sanity**: TP distance from current price >= `tp_forbidden_zone` (3.0)
- [ ] **TP/SL validation**: Long `tp > px && sl < px`; Short `tp < px && sl > px`
- [ ] **Exposure limits**: `total <= 30`, per-side <= 6

If any hard rule triggers, **delete the order**.

If an order is in a **gray zone** (yellow rule), the AI may either:
1. Use `ai_review.py` to get an LLM judgment, **or**
2. Make the judgment directly and **state the explicit reason** in the final output.

### Step 5: Finalize Plan
Write the final plan to a temporary JSON file (`tomokx_plan_final.json`).

### Step 6: Execute
Call `execute_and_finalize.py` with the final plan file path.

### Step 7: Report
Print a human-readable summary including:
- Price, trend, alignment
- Orders placed / cancelled
- AI decisions and justifications
- Any errors or warnings

---

## Rules Configuration

`$WORKSPACE/scripts/rules.json` contains the machine-readable rule parameters. If you need to adjust thresholds (e.g., make `tp_forbidden_zone` stricter), edit `rules.json` rather than Python source code.

Key sections:
- `hard_rules`: thresholds for automatic deletion
- `yellow_rules`: edge-case conditions that require judgment
- `dynamic_sizing`: automatic `sz` adjustments based on market regime

---

## Environment Variables

- `TOMOKX_LLM_BACKEND` (optional): force LLM backend
  - `"openclaw"` → use local openclaw gateway at `127.0.0.1:18789`
  - `"kimi"` → use local `kimi.exe` CLI
  - If unset, `ai_review.py` auto-detects by probing the gateway health endpoint.

---

## Last-Cycle State

After each successful execution, `execute_and_finalize.py` writes `$WORKSPACE/last_cycle_report.json`. The AI may read this at the start of the next cycle to maintain continuity.
