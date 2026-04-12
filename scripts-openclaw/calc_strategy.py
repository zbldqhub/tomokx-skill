#!/usr/bin/env python3
"""Calculate strategy suggestion: trend, targets, and gap."""
import json
import sys

from config import base_gap


def trend_from_data(change24h_pct, trend_1h):
    # Prefer 1h trend when they conflict
    if trend_1h in ("bullish", "bearish", "sideways"):
        return trend_1h
    if change24h_pct > 2:
        return "bullish"
    elif change24h_pct < -2:
        return "bearish"
    return "sideways"


def targets(trend):
    if trend == "bullish":
        return 2, 1
    elif trend == "bearish":
        return 1, 2
    return 1, 2


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

    with open(market_path, "r", encoding="utf-8") as f:
        market = json.load(f)

    total_i = int(float(total))
    change24h = market.get("change24h_pct", 0)
    trend_1h = market.get("trend_1h", "sideways")
    vol = market.get("volatility_1h", 0)
    spread = market.get("spread", 0)

    trend = trend_from_data(change24h, trend_1h)
    target_long, target_short = targets(trend)
    gap = base_gap(total_i)

    if vol > 25:
        gap += 4
    elif vol > 15:
        gap += 2

    if spread > 0.5:
        gap += 1

    imbalance = 0
    if exposure_path:
        try:
            with open(exposure_path, "r", encoding="utf-8") as f:
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
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
