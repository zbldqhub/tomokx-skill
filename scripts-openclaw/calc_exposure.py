#!/usr/bin/env python3
"""Calculate total exposure from orders and positions JSON files."""
import json
import sys
import math

from config import MAX_TOTAL, ORDER_SIZE, LEVERAGE


def classify_orders(orders):
    short, long = 0, 0
    for o in orders:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        if o.get("ordType") != "limit":
            continue
        side = o.get("side")
        pos_side = o.get("posSide")
        if side == "sell" and pos_side == "short":
            short += 1
        elif side == "buy" and pos_side == "long":
            long += 1
    return short, long


def classify_positions(positions):
    short_pos, long_pos = 0.0, 0.0
    for p in positions:
        if p.get("instId") != "ETH-USDT-SWAP":
            continue
        if str(p.get("lever")) != str(LEVERAGE):
            continue
        if p.get("mgnMode") != "isolated":
            continue
        sz = float(p.get("pos", "0") or "0")
        if p.get("posSide") == "short":
            short_pos += sz
        elif p.get("posSide") == "long":
            long_pos += sz
    return short_pos, long_pos


def main():
    orders_path = sys.argv[1] if len(sys.argv) > 1 else None
    positions_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not orders_path or not positions_path:
        print("Usage: python3 calc_exposure.py <orders.json> <positions.json>")
        sys.exit(1)

    with open(orders_path, "r", encoding="utf-8") as f:
        orders_data = json.load(f)
    with open(positions_path, "r", encoding="utf-8") as f:
        positions_data = json.load(f)

    orders_list = orders_data.get("data", []) if isinstance(orders_data, dict) else []
    positions_list = positions_data.get("data", []) if isinstance(positions_data, dict) else []

    short_orders, long_orders = classify_orders(orders_list)
    short_pos, long_pos = classify_positions(positions_list)

    short_pos_units = round(short_pos / ORDER_SIZE, 1)
    long_pos_units = round(long_pos / ORDER_SIZE, 1)
    orders_count = short_orders + long_orders
    positions_count = round(short_pos_units + long_pos_units, 1)
    total = round(orders_count + positions_count, 1)
    remaining = math.floor(MAX_TOTAL - total)

    result = {
        "short_orders": short_orders,
        "long_orders": long_orders,
        "orders_count": orders_count,
        "short_pos": short_pos,
        "long_pos": long_pos,
        "short_pos_units": short_pos_units,
        "long_pos_units": long_pos_units,
        "positions_count": positions_count,
        "total": total,
        "remaining_capacity": remaining,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
