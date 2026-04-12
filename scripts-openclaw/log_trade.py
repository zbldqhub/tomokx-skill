#!/usr/bin/env python3
"""
Trade execution logger for openclaw (Linux).
Appends a structured summary line to auto_trade.log and auto_trade.jsonl.
"""
import os
import sys
import argparse
import json
from datetime import datetime, timezone

from config import LOG_PATH, JSONL_PATH


def main():
    parser = argparse.ArgumentParser(description="Log trading cycle summary")
    parser.add_argument("--trend", required=True, help="Market trend")
    parser.add_argument("--price", required=True, help="Current price")
    parser.add_argument("--orders", required=True, help="Live orders count")
    parser.add_argument("--positions", required=True, help="Open positions count")
    parser.add_argument("--total", required=True, help="Total exposure")
    parser.add_argument("--actions", required=True, help="Executed actions")
    parser.add_argument("--gap", default="", help="Gap used (optional)")
    parser.add_argument("--high24h", default="", help="24h high (optional)")
    parser.add_argument("--low24h", default="", help="24h low (optional)")
    parser.add_argument("--short_orders", default="", help="Short orders count (optional)")
    parser.add_argument("--long_orders", default="", help="Long orders count (optional)")
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Text log
    line = (
        f"[{timestamp}] | tomokx-openclaw | Trading Cycle Summary\n"
        f"- Market Trend: {args.trend}\n"
        f"- Current Price: {args.price} USDT\n"
        f"- Orders: {args.orders} live\n"
        f"- Positions: {args.positions} open\n"
        f"- Total Exposure: {args.total}/20\n"
        f"- Actions: {args.actions}\n"
    )

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    # JSONL log
    jsonl_entry = {
        "timestamp": timestamp,
        "source": "tomokx-openclaw",
        "trend": args.trend,
        "price": args.price,
        "orders": args.orders,
        "positions": args.positions,
        "total": args.total,
        "actions": args.actions,
    }
    if args.gap:
        jsonl_entry["gap"] = args.gap
    if args.high24h:
        jsonl_entry["high24h"] = args.high24h
    if args.low24h:
        jsonl_entry["low24h"] = args.low24h
    if args.short_orders:
        jsonl_entry["short_orders"] = args.short_orders
    if args.long_orders:
        jsonl_entry["long_orders"] = args.long_orders

    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(jsonl_entry, ensure_ascii=False) + "\n")

    print(f"Logged to {LOG_PATH} and {JSONL_PATH}")


if __name__ == "__main__":
    main()
