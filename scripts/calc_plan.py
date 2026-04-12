#!/usr/bin/env python3
"""Generate a trading plan based on market, exposure, strategy and far orders data."""
import json
import sys


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def calc_tp_sl_offset(volatility_1h):
    if volatility_1h < 5:
        return 12, 85
    elif volatility_1h < 10:
        return 20, 90
    elif volatility_1h < 15:
        return 28, 98
    elif volatility_1h < 25:
        return 38, 108
    else:
        return 45, 115


def get_existing_prices(orders_data, side, pos_side, far_ord_ids):
    prices = []
    orders_list = orders_data.get("data", []) if isinstance(orders_data, dict) else []
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        if o.get("ordId") in far_ord_ids:
            continue
        if o.get("side") == side and o.get("posSide") == pos_side:
            try:
                prices.append(float(o.get("px", 0)))
            except:
                continue
    return sorted(prices)


def pick_best_long_px(current_price, existing, gap, chosen):
    """Generate candidates (inner + outer) and pick the best valid long price."""
    candidates = []
    if existing:
        # Inner replenish candidates
        for k in range(1, 6):
            c = current_price - gap * k
            if c >= max(existing) + gap:
                candidates.append(c)
        # Outer replenish candidates
        for k in range(1, 6):
            c = min(existing) - gap * k
            candidates.append(c)
    else:
        # Build from scratch
        for k in range(5):
            c = current_price * 0.998 - gap * k
            candidates.append(c)

    # Filter valid candidates
    valid = []
    for c in candidates:
        if c >= current_price:
            continue
        if abs(c - current_price) >= 80:
            continue
        # Gap check with existing
        ok = True
        for p in existing:
            if abs(c - p) < gap - 0.001:
                ok = False
                break
        if not ok:
            continue
        # Gap check with already chosen
        for p in chosen:
            if abs(c - p) < gap - 0.001:
                ok = False
                break
        if ok:
            valid.append(c)

    if not valid:
        return None
    # Pick closest to current_price
    return max(valid)


def pick_best_short_px(current_price, existing, gap, chosen):
    """Generate candidates (inner + outer) and pick the best valid short price."""
    candidates = []
    if existing:
        # Inner replenish candidates
        for k in range(1, 6):
            c = current_price + gap * k
            if c <= min(existing) - gap:
                candidates.append(c)
        # Outer replenish candidates
        for k in range(1, 6):
            c = max(existing) + gap * k
            candidates.append(c)
    else:
        # Build from scratch
        for k in range(5):
            c = current_price * 1.002 + gap * k
            candidates.append(c)

    valid = []
    for c in candidates:
        if c <= current_price:
            continue
        if abs(c - current_price) >= 80:
            continue
        ok = True
        for p in existing:
            if abs(c - p) < gap - 0.001:
                ok = False
                break
        if not ok:
            continue
        for p in chosen:
            if abs(c - p) < gap - 0.001:
                ok = False
                break
        if ok:
            valid.append(c)

    if not valid:
        return None
    # Pick closest to current_price
    return min(valid)


def main():
    if len(sys.argv) < 5:
        print("Usage: python3 calc_plan.py <market.json> <exposure.json> <strategy.json> <far_orders.json> [orders.json]")
        sys.exit(1)

    market = load_json(sys.argv[1])
    exposure = load_json(sys.argv[2])
    strategy = load_json(sys.argv[3])
    far_orders = load_json(sys.argv[4])
    orders = load_json(sys.argv[5]) if len(sys.argv) > 5 else {}

    current_price = float(market.get("last", 0))
    vol = float(market.get("volatility_1h", 0))
    trend = strategy.get("trend", "sideways")
    gap = float(strategy.get("adjusted_gap", 10))

    target_long = min(int(strategy.get("target_long", 1)), 4)
    target_short = min(int(strategy.get("target_short", 1)), 4)
    long_orders_count = int(exposure.get("long_orders", 0))
    short_orders_count = int(exposure.get("short_orders", 0))
    remaining_capacity = int(exposure.get("remaining_capacity", 0))

    tp_offset, sl_offset = calc_tp_sl_offset(vol)

    long_needed = max(0, target_long - long_orders_count)
    short_needed = max(0, target_short - short_orders_count)

    if long_needed + short_needed > remaining_capacity:
        if trend == "bullish":
            long_needed = min(long_needed, remaining_capacity)
            short_needed = min(short_needed, remaining_capacity - long_needed)
        elif trend == "bearish":
            short_needed = min(short_needed, remaining_capacity)
            long_needed = min(long_needed, remaining_capacity - short_needed)
        else:
            each = remaining_capacity // 2
            long_needed = min(long_needed, each)
            short_needed = min(short_needed, remaining_capacity - long_needed)

    cancellations = far_orders.get("far_orders", [])
    far_ord_ids = {o.get("ordId") for o in cancellations}
    placements = []

    existing_long = get_existing_prices(orders, "buy", "long", far_ord_ids)
    chosen_long = []
    for _ in range(long_needed):
        px = pick_best_long_px(current_price, existing_long, gap, chosen_long)
        if px is None:
            continue
        chosen_long.append(px)
        tp = round(px + tp_offset, 2)
        sl = round(px - sl_offset, 2)
        if tp <= px or sl >= px:
            continue
        placements.append({
            "instId": "ETH-USDT-SWAP",
            "tdMode": "isolated",
            "side": "buy",
            "ordType": "limit",
            "sz": "0.1",
            "px": str(round(px, 2)),
            "posSide": "long",
            "tpTriggerPx": str(tp),
            "slTriggerPx": str(sl)
        })

    existing_short = get_existing_prices(orders, "sell", "short", far_ord_ids)
    chosen_short = []
    for _ in range(short_needed):
        px = pick_best_short_px(current_price, existing_short, gap, chosen_short)
        if px is None:
            continue
        chosen_short.append(px)
        tp = round(px - tp_offset, 2)
        sl = round(px + sl_offset, 2)
        if tp >= px or sl <= px:
            continue
        placements.append({
            "instId": "ETH-USDT-SWAP",
            "tdMode": "isolated",
            "side": "sell",
            "ordType": "limit",
            "sz": "0.1",
            "px": str(round(px, 2)),
            "posSide": "short",
            "tpTriggerPx": str(tp),
            "slTriggerPx": str(sl)
        })

    actions = []
    if cancellations:
        actions.append(f"Cancel {len(cancellations)} far order(s)")
    if placements:
        actions.append(f"Place {len(placements)} order(s)")
    if not actions:
        actions.append("No action needed")

    plan = {
        "cancellations": cancellations,
        "placements": placements,
        "summary": {
            "trend": trend,
            "price": str(current_price),
            "orders": str(exposure.get("orders_count", 0)),
            "positions": str(exposure.get("positions_count", 0)),
            "total": str(exposure.get("total", 0)),
            "actions": "; ".join(actions)
        }
    }
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
