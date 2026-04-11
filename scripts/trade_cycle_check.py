#!/usr/bin/env python3
"""
One-shot trading cycle diagnostic for Windows tomokx skill.
Does NOT place/cancel orders; only validates decision logic and outputs the plan.
"""
import json
import subprocess
import time
import os
import math

ENV_FILE = os.path.expanduser("~/.openclaw/workspace/.env.trading")
WORKSPACE = os.path.expanduser("~/.openclaw/workspace")

def run_analyzer():
    result = subprocess.run(
        ["python", os.path.join(WORKSPACE, "scripts", "eth_market_analyzer.py")],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return {"error": result.stderr or "analyzer failed"}
    return json.loads(result.stdout)

def run_bills():
    result = subprocess.run(
        ["python", os.path.join(WORKSPACE, "scripts", "get_bills.py"), "--today"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return {"error": result.stderr or "bills failed"}
    return json.loads(result.stdout)

def check_trading_stopped():
    path = os.path.join(WORKSPACE, ".trading_stopped")
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        return int(content)
    except:
        return 0

def calc_daily_loss(bills_data):
    if not isinstance(bills_data, dict) or bills_data.get("code") != "0":
        return None, "bills API error"
    records = bills_data.get("data", [])
    total = 0.0
    matched = 0
    for r in records:
        if r.get("instId") != "ETH-USDT-SWAP":
            continue
        sub = int(r.get("subType", -1))
        if sub not in {4, 6, 110, 111, 112}:
            continue
        pnl = float(r.get("pnl", "0") or "0")
        total += pnl
        matched += 1
    return total, f"matched {matched} records"

def classify_orders(orders):
    short_orders = []
    long_orders = []
    for o in orders:
        if o.get("instId") != "ETH-USDT-SWAP":
            continue
        if o.get("state") != "live":
            continue
        if o.get("ordType") != "limit":
            continue
        sz = o.get("sz", "0")
        try:
            sz_f = float(sz)
        except:
            continue
        side = o.get("side")
        pos_side = o.get("posSide")
        if side == "sell" and pos_side == "short":
            short_orders.append(o)
        elif side == "buy" and pos_side == "long":
            long_orders.append(o)
    return short_orders, long_orders

def classify_positions(positions):
    short_pos = 0.0
    long_pos = 0.0
    for p in positions:
        if p.get("instId") != "ETH-USDT-SWAP":
            continue
        if str(p.get("lever")) != "10":
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
    print("=" * 50)
    print("ETH Trader Cycle Check (Windows)")
    print("=" * 50)

    # Step 1: trading stopped
    stopped = check_trading_stopped()
    print(f"\n[Step 1] Trading stopped count: {stopped}")
    if stopped >= 3:
        print("🛑 STOP: consecutive stop-loss limit reached.")
        return

    # Step 1.2: daily loss
    bills = run_bills()
    daily_pnl, info = calc_daily_loss(bills)
    print(f"\n[Step 1.2] Daily net realized P&L: {daily_pnl} USDT ({info})")
    if daily_pnl is not None and daily_pnl < -40:
        print("🛑 STOP: daily loss limit exceeded.")
        return

    # Step 1.5: market snapshot
    data = run_analyzer()
    if "error" in data:
        print(f"\n[Step 1.5] Analyzer error: {data['error']}")
        return

    market = data.get("market", {})
    stats = data.get("hourly_stats", {})
    orders = data.get("orders", [])
    positions = data.get("positions", [])
    balance = data.get("balance", [])

    last_px = market.get("last", 0)
    change24h = market.get("change24h_pct", 0)
    trend = stats.get("trend_1h", "sideways")
    volatility = stats.get("volatility_1h", 0)

    print(f"\n[Step 1.5] Market snapshot:")
    print(f"  Price: {last_px} | 24h change: {change24h}% | Trend(1h): {trend} | Volatility(1h): {volatility}")

    # Step 3/4: orders & positions
    short_orders, long_orders = classify_orders(orders)
    short_pos, long_pos = classify_positions(positions)

    short_orders_count = len(short_orders)
    long_orders_count = len(long_orders)
    orders_count = short_orders_count + long_orders_count

    short_pos_units = short_pos / 0.1
    long_pos_units = long_pos / 0.1
    positions_count = short_pos_units + long_pos_units

    total = orders_count + positions_count
    remaining_capacity = math.floor(20 - total)

    print(f"\n[Step 3/4/5] Orders & Positions:")
    print(f"  Short orders: {short_orders_count} | Long orders: {long_orders_count}")
    print(f"  Short pos: {short_pos} ({short_pos_units} units) | Long pos: {long_pos} ({long_pos_units} units)")
    print(f"  Total exposure: {total}/20  -> remaining_capacity = {remaining_capacity}")

    # Step 6: cancel far orders
    far_orders = []
    for o in orders:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        px = float(o.get("px", "0") or "0")
        if abs(px - last_px) > 100:
            far_orders.append(o)
    print(f"\n[Step 6] Far orders (>100 USDT away): {len(far_orders)}")
    for o in far_orders:
        print(f"  -> Would cancel ordId={o.get('ordId')} px={o.get('px')}")

    # Step 7/8: order placement logic
    print(f"\n[Step 7/8] Decision:")
    if remaining_capacity <= 0:
        print("  -> NO new orders placed (remaining capacity = 0).")
    else:
        print(f"  -> Could place up to {remaining_capacity} new orders (not implemented in this check script).")

    # Step 8.5: stop-loss counter (simplified: check today's bills for SL subtype with pnl<0)
    sl_count_today = 0
    if isinstance(bills, dict) and bills.get("code") == "0":
        for r in bills.get("data", []):
            if r.get("instId") != "ETH-USDT-SWAP":
                continue
            sub = int(r.get("subType", -1))
            if sub in {4, 6, 110, 111, 112}:
                pnl = float(r.get("pnl", "0") or "0")
                if pnl < 0:
                    sl_count_today += 1
    print(f"\n[Step 8.5] Losing close records today: {sl_count_today}")

    print(f"\n[Step 10] Log: OK | Cycle complete. No action taken.")
    print("=" * 50)

if __name__ == "__main__":
    main()
