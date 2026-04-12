#!/usr/bin/env python3
"""Filter orders that are >100 USDT away from current price."""
import json
import sys


def main():
    orders_path = sys.argv[1] if len(sys.argv) > 1 else None
    current_price = sys.argv[2] if len(sys.argv) > 2 else None

    if not orders_path or current_price is None:
        print("Usage: python3 filter_far_orders.py <orders.json> <current_price>")
        sys.exit(1)

    price = float(current_price)
    with open(orders_path, "r", encoding="utf-8") as f:
        orders_data = json.load(f)

    orders_list = orders_data.get("data", []) if isinstance(orders_data, dict) else []
    far_orders = []
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        px = float(o.get("px", "0") or "0")
        if abs(px - price) > 100:
            far_orders.append({
                "instId": "ETH-USDT-SWAP",
                "ordId": o.get("ordId"),
                "px": px,
                "side": o.get("side"),
                "posSide": o.get("posSide"),
            })

    print(json.dumps({"far_orders": far_orders, "threshold": 100, "current_price": price}, indent=2))


if __name__ == "__main__":
    main()
