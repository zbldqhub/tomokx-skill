#!/usr/bin/env python3
"""Calculate strategy suggestion: trend, targets, and gap."""
import json
import sys

from config import base_gap, calc_atr


def targets(trend, alignment):
    # Align with SKILL.md target table
    if alignment == "strong":
        if trend == "bullish":
            return 2, 1
        elif trend == "bearish":
            return 1, 2
        else:
            return 1, 1
    elif alignment == "moderate":
        if trend == "bullish":
            return 2, 1
        elif trend == "bearish":
            return 1, 2
        else:
            return 1, 1
    else:
        # mixed / weak: base (1,1); resolve_trend subtracts 1 each → (0,0)
        # sideways branch in resolve_trend also forces both to 0
        return 1, 1


def resolve_trend(market):
    """Use 4h as primary, with alignment and funding bias adjustments."""
    trend_4h = market.get("trend_4h", "sideways")
    trend_1h = market.get("trend_1h", "sideways")
    trend_15m = market.get("trend_15m", "sideways")
    alignment = market.get("trend_alignment", "weak")
    funding_bias = market.get("funding_bias", "neutral")

    if trend_4h == trend_1h == trend_15m:
        alignment = "strong"
        trend = trend_4h
    elif trend_4h == trend_1h:
        alignment = "moderate"
        trend = trend_4h
    elif trend_4h == trend_15m:
        alignment = "mixed"
        trend = "sideways"
    else:
        alignment = "weak"
        trend = "sideways"

    target_long, target_short = targets(trend, alignment)

    if alignment in ("mixed", "weak"):
        target_long = max(0, target_long - 1)
        target_short = max(0, target_short - 1)
        # Aggressive: mixed/weak sideways → halt expansion
        if trend == "sideways":
            target_long = 0
            target_short = 0

    if funding_bias == "long_favored" and target_long < 2:
        target_long = min(2, target_long + 1)
        if target_short > 0:
            target_short = max(0, target_short - 1)
    elif funding_bias == "short_favored" and target_short < 2:
        target_short = min(2, target_short + 1)
        if target_long > 0:
            target_long = max(0, target_long - 1)

    return trend, target_long, target_short, alignment, funding_bias


def adjust_targets_for_imbalance(target_long, target_short, exposure):
    """Reduce target on the overweight side if imbalance is severe."""
    long_total = exposure.get("long_orders", 0) + exposure.get("long_pos_units", 0)
    short_total = exposure.get("short_orders", 0) + exposure.get("short_pos_units", 0)
    imbalance = abs(long_total - short_total)
    if imbalance >= 3:
        if long_total > short_total and target_long > 0:
            target_long = max(0, target_long - 1)
        elif short_total > long_total and target_short > 0:
            target_short = max(0, target_short - 1)
    return target_long, target_short, imbalance


def main():
    market_path = sys.argv[1] if len(sys.argv) > 1 else None
    total = sys.argv[2] if len(sys.argv) > 2 else None
    exposure_path = sys.argv[3] if len(sys.argv) > 3 else None

    if not market_path or total is None:
        print("Usage: python3 calc_strategy.py <market.json> <total> [exposure.json]")
        sys.exit(1)

    with open(market_path, "r", encoding="utf-8-sig") as f:
        market = json.load(f)

    total_i = int(float(total))
    change24h = market.get("change24h_pct", 0)
    vol = market.get("volatility_1h", 0)
    spread = market.get("spread", 0)

    trend, target_long, target_short, alignment, funding_bias = resolve_trend(market)
    gap = base_gap(total_i)

    # ATR-based dynamic gap (dominant, with soft cap)
    candles_1h = market.get("candle_1h", [])
    atr = calc_atr(candles_1h) if candles_1h else None
    if atr:
        atr_gap = int(round(atr * 0.8))
        gap = max(gap, atr_gap)
        gap = min(gap, base_gap(total_i) + 6)  # soft cap: max base+6

    if spread > 0.5:
        gap += 1

    imbalance = 0
    if exposure_path:
        try:
            with open(exposure_path, "r", encoding="utf-8-sig") as f:
                exposure = json.load(f)
            target_long, target_short, imbalance = adjust_targets_for_imbalance(
                target_long, target_short, exposure
            )
        except Exception:
            pass

    result = {
        "trend": trend,
        "target_long": target_long,
        "target_short": target_short,
        "base_gap": base_gap(total_i),
        "adjusted_gap": gap,
        "volatility_1h": vol,
        "spread": spread,
        "change24h_pct": change24h,
        "imbalance_score": imbalance,
        "trend_alignment": alignment,
        "funding_bias": funding_bias,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
