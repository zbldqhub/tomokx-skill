# TOMOKX AI Execution Protocol

This document defines how any AI agent should execute the `tomokx` ETH-USDT-SWAP grid trading skill.

## Core Principle

**The AI is the arbiter, not the trader.** Scripts are only "hands" for data collection and execution. All trading decisions must be made by the AI after reading `skills/tomokx/SKILL.md` and applying `rules.json`.

## Workflow References

- **Manual execution**: Follow `workflows/tomokx-manual.md` step by step.
- **Fully automated scheduling**: See `workflows/tomokx-auto.md`.
- **Strategy rules & decision boundaries**: See `skills/tomokx/SKILL.md`.

## Forbidden Behaviors

1. **Never** call `run_trade_cycle.py` as a single black-box step when manually executing via this protocol. It is reserved for the auto workflow.
2. **Never** place an order when `recommendation = pause` without explicitly stating the justification in the final output.
3. **Never** add heavy-side outer expansion unless `trend_alignment = strong` **AND** funding rate aligns with the position side.
4. **Never** place TP within `tp_forbidden_zone` USDT of the current price (default: 3.0).
5. **Never** modify hard risk parameters (`max_total`, `daily_loss_limit`, `per-side max`, `cancel_threshold`).
