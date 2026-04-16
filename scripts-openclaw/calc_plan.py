#!/usr/bin/env python3
"""Generate a trading plan based on market, exposure, strategy and far orders data."""
import json
import sys


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def calc_tp_sl_offset(volatility_1h, gap):
    tp = max(12, int(gap * 1.5))
    sl = max(20, int(gap * 2.5))
    if volatility_1h > 25:
        tp += 5
        sl += 8
    elif volatility_1h > 15:
        tp += 3
        sl += 5
    elif volatility_1h > 10:
        tp += 1
        sl += 3
    return tp, sl


def get_existing_prices(orders_data, side, pos_side, far_ord_ids):
    prices = []
    orders_list = orders_data.get("data", []) if isinstance(orders_data, dict) else []
    for o in orders_list:
        inst_id = o.get("instId")
        if inst_id is None:
            # fallback for incomplete manual test data
            inst_id = "ETH-USDT-SWAP"
        if inst_id != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        if o.get("ordId") in far_ord_ids:
            continue
        if o.get("side") == side and o.get("posSide") == pos_side:
            try:
                prices.append(float(o.get("px", 0)))
            except Exception:
                continue
    return sorted(prices)


def pick_best_long_px(current_price, existing, gap, chosen, allow_outer=True):
    """Generate candidates (inner + outer) and pick the best valid long price."""
    candidates = []
    mode = ""
    if existing:
        # Inner replenish candidates
        for k in range(1, 6):
            c = current_price - gap * k
            if c >= max(existing) + gap:
                candidates.append(c)
        # Outer replenish candidates
        if allow_outer:
            for k in range(1, 6):
                c = min(existing) - gap * k
                candidates.append(c)
        mode = "replenish"
    else:
        # Build from scratch
        for k in range(5):
            c = current_price * 0.998 - gap * k
            candidates.append(c)
        mode = "scratch"

    # Filter valid candidates
    valid = []
    rejected = []
    for c in candidates:
        if c >= current_price:
            rejected.append((c, "above_current_price"))
            continue
        if abs(c - current_price) >= 80:
            rejected.append((c, "distance_cap_80"))
            continue
        # Gap check with existing
        ok = True
        for p in existing:
            if abs(c - p) < gap - 0.001:
                ok = False
                rejected.append((c, f"gap_conflict_with_existing_{p}"))
                break
        if not ok:
            continue
        # Gap check with already chosen
        for p in chosen:
            if abs(c - p) < gap - 0.001:
                ok = False
                rejected.append((c, f"gap_conflict_with_chosen_{p}"))
                break
        if ok:
            valid.append(c)

    if not valid:
        return None, mode, rejected
    # Pick closest to current_price
    return max(valid), mode, rejected


def pick_best_short_px(current_price, existing, gap, chosen, allow_outer=True):
    """Generate candidates (inner + outer) and pick the best valid short price."""
    candidates = []
    mode = ""
    if existing:
        # Inner replenish candidates
        for k in range(1, 6):
            c = current_price + gap * k
            if c <= min(existing) - gap:
                candidates.append(c)
        # Outer replenish candidates
        if allow_outer:
            for k in range(1, 6):
                c = max(existing) + gap * k
                candidates.append(c)
        mode = "replenish"
    else:
        # Build from scratch
        for k in range(5):
            c = current_price * 1.002 + gap * k
            candidates.append(c)
        mode = "scratch"

    valid = []
    rejected = []
    for c in candidates:
        if c <= current_price:
            rejected.append((c, "below_current_price"))
            continue
        if abs(c - current_price) >= 80:
            rejected.append((c, "distance_cap_80"))
            continue
        ok = True
        for p in existing:
            if abs(c - p) < gap - 0.001:
                ok = False
                rejected.append((c, f"gap_conflict_with_existing_{p}"))
                break
        if not ok:
            continue
        for p in chosen:
            if abs(c - p) < gap - 0.001:
                ok = False
                rejected.append((c, f"gap_conflict_with_chosen_{p}"))
                break
        if ok:
            valid.append(c)

    if not valid:
        return None, mode, rejected
    # Pick closest to current_price
    return min(valid), mode, rejected


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
    remaining_capacity = int(exposure.get("remaining_capacity", 0))

    alignment = strategy.get("trend_alignment", "weak")
    imbalance = strategy.get("imbalance_score", 0)
    long_total = exposure.get("long_orders", 0) + exposure.get("long_pos_units", 0)
    short_total = exposure.get("short_orders", 0) + exposure.get("short_pos_units", 0)

    # Outer expansion permissions
    allow_outer_long = True
    allow_outer_short = True
    if trend == "bullish":
        allow_outer_short = False
    elif trend == "bearish":
        allow_outer_long = False
    if alignment in ("mixed", "weak"):
        allow_outer_long = False
        allow_outer_short = False
        # Aggressive: in mixed/weak, drastically reduce targets to avoid chop
        target_long = min(target_long, 1)
        target_short = min(target_short, 1)
        # If sideways with mixed/weak, prefer only inner side (no new outer)
        if trend == "sideways":
            target_long = min(target_long, 0)
            target_short = min(target_short, 0)
    if imbalance >= 2:
        if long_total > short_total:
            allow_outer_long = False
        elif short_total > long_total:
            allow_outer_short = False

    tp_offset, sl_offset = calc_tp_sl_offset(vol, gap)

    cancellations = far_orders.get("far_orders", [])
    far_ord_ids = {o.get("ordId") for o in cancellations}

    existing_long = get_existing_prices(orders, "buy", "long", far_ord_ids)
    existing_short = get_existing_prices(orders, "sell", "short", far_ord_ids)

    # 用过滤掉 far orders 后的实际数量计算 needed，避免 exposure 与 existing 不一致
    long_orders_count = len(existing_long)
    short_orders_count = len(existing_short)

    long_needed = max(0, target_long - long_orders_count)
    short_needed = max(0, target_short - short_orders_count)

    # Inner replenish boost: price moved inside grid, need to fill the gap
    long_boost_reason = ""
    short_boost_reason = ""
    if existing_long and current_price > max(existing_long) + gap:
        inner_long = [current_price - gap * k for k in range(1, 6) if current_price - gap * k >= max(existing_long) + gap]
        if inner_long:
            long_needed = max(long_needed, 1)
            long_boost_reason = f"Price moved above all long orders (max={max(existing_long)}), inner replenish available, boost needed=1"
        elif len(existing_long) <= target_long:
            long_needed = max(long_needed, 1)
            long_boost_reason = f"Price moved above all long orders (max={max(existing_long)}), no inner candidate but existing_count({len(existing_long)}) <= target({target_long}), outer boost needed=1"
        else:
            long_boost_reason = f"Price moved above all long orders (max={max(existing_long)}), but no inner candidate and existing_count({len(existing_long)}) > target({target_long}); skip boost"
    if existing_short and current_price < min(existing_short) - gap:
        inner_short = [current_price + gap * k for k in range(1, 6) if current_price + gap * k <= min(existing_short) - gap]
        if inner_short:
            short_needed = max(short_needed, 1)
            short_boost_reason = f"Price moved below all short orders (min={min(existing_short)}), inner replenish available, boost needed=1"
        elif len(existing_short) <= target_short:
            short_needed = max(short_needed, 1)
            short_boost_reason = f"Price moved below all short orders (min={min(existing_short)}), no inner candidate but existing_count({len(existing_short)}) <= target({target_short}), outer boost needed=1"
        else:
            short_boost_reason = f"Price moved below all short orders (min={min(existing_short)}), but no inner candidate and existing_count({len(existing_short)}) > target({target_short}); skip boost"

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

    placements = []

    reasoning = {
        "long": {
            "existing": existing_long,
            "target": target_long,
            "existing_count": len(existing_long),
            "target_deviation": len(existing_long) - target_long,
            "needed": long_needed,
            "mode": "",
            "expansion_type": "",
            "hole_to_current": round(current_price - max(existing_long), 2) if existing_long else None,
            "selected": [],
            "rejected": [],
            "notes": [long_boost_reason] if long_boost_reason else [],
        },
        "short": {
            "existing": existing_short,
            "target": target_short,
            "existing_count": len(existing_short),
            "target_deviation": len(existing_short) - target_short,
            "needed": short_needed,
            "mode": "",
            "expansion_type": "",
            "hole_to_current": round(min(existing_short) - current_price, 2) if existing_short else None,
            "selected": [],
            "rejected": [],
            "notes": [short_boost_reason] if short_boost_reason else [],
        },
    }

    chosen_long = []
    for i in range(long_needed):
        px, mode, rejected = pick_best_long_px(current_price, existing_long + chosen_long, gap, chosen_long, allow_outer_long)
        if i == 0:
            reasoning["long"]["mode"] = mode
            reasoning["long"]["rejected"] = [[round(r[0], 2), r[1]] for r in rejected[:5]]
        if px is None:
            reasoning["long"]["notes"].append(f"Attempt {i+1}: no valid candidate found")
            continue
        chosen_long.append(px)
        reasoning["long"]["selected"].append(round(px, 2))
        # Determine expansion type for transparency
        if existing_long:
            if px > max(existing_long):
                reasoning["long"]["expansion_type"] = "inner"
                reasoning["long"]["notes"].append(f"Selected {px} as inner replenish (between current price and max existing {max(existing_long)})")
            else:
                reasoning["long"]["expansion_type"] = "outer"
                reasoning["long"]["notes"].append(f"Selected {px} as outer expansion (below max existing {max(existing_long)}); does not fill gap near current price")
        tp = round(px + tp_offset, 2)
        sl = round(px - sl_offset, 2)
        if tp <= px or sl >= px:
            reasoning["long"]["notes"].append(f"Price {px} failed TP/SL validation (tp={tp}, sl={sl})")
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

    chosen_short = []
    for i in range(short_needed):
        px, mode, rejected = pick_best_short_px(current_price, existing_short + chosen_short, gap, chosen_short, allow_outer_short)
        if i == 0:
            reasoning["short"]["mode"] = mode
            reasoning["short"]["rejected"] = [[round(r[0], 2), r[1]] for r in rejected[:5]]
        if px is None:
            reasoning["short"]["notes"].append(f"Attempt {i+1}: no valid candidate found")
            continue
        chosen_short.append(px)
        reasoning["short"]["selected"].append(round(px, 2))
        # Determine expansion type for transparency
        if existing_short:
            if px < min(existing_short):
                reasoning["short"]["expansion_type"] = "inner"
                reasoning["short"]["notes"].append(f"Selected {px} as inner replenish (between current price and min existing {min(existing_short)})")
            else:
                reasoning["short"]["expansion_type"] = "outer"
                reasoning["short"]["notes"].append(f"Selected {px} as outer expansion (above min existing {min(existing_short)}); does not fill gap near current price")
        tp = round(px - tp_offset, 2)
        sl = round(px + sl_offset, 2)
        if tp >= px or sl <= px:
            reasoning["short"]["notes"].append(f"Price {px} failed TP/SL validation (tp={tp}, sl={sl})")
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
        "reasoning": reasoning,
        "summary": {
            "trend": trend,
            "price": str(current_price),
            "gap": str(gap),
            "volatility_1h": str(vol),
            "orders": str(exposure.get("orders_count", 0)),
            "positions": str(exposure.get("positions_count", 0)),
            "total": str(exposure.get("total", 0)),
            "actions": "; ".join(actions)
        }
    }
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
