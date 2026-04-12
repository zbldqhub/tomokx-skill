#!/usr/bin/env python3
"""
Trade execution logger for Windows tomokx skill.
Appends a structured summary line to auto_trade.log.
"""
import os
import sys
import argparse
from datetime import datetime

LOG_PATH = os.path.expanduser(r"~\.openclaw\workspace\auto_trade.log")

def main():
    parser = argparse.ArgumentParser(description="Log trading cycle summary")
    parser.add_argument("--trend", required=True, help="Market trend")
    parser.add_argument("--price", required=True, help="Current price")
    parser.add_argument("--orders", required=True, help="Live orders count")
    parser.add_argument("--positions", required=True, help="Open positions count")
    parser.add_argument("--total", required=True, help="Total exposure")
    parser.add_argument("--actions", required=True, help="Executed actions")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = (
        f"[{timestamp}] | tomokx | Trading Cycle Summary\n"
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

    print(f"Logged to {LOG_PATH}")

if __name__ == "__main__":
    main()
