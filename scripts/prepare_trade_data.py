#!/usr/bin/env python3
"""
Prepare all pre-trade data in one shot for Windows tomokx skill.
Outputs a JSON decision payload so AI only needs to analyze & decide.
"""
import os
import sys
import json
import subprocess
import math
from datetime import datetime, timezone

WORKSPACE = os.path.expanduser(r"~\.openclaw\workspace")
ENV_FILE = os.path.join(WORKSPACE, ".env.trading")

def load_env():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    os.environ[k] = v

def run_script(name, *args):
    env = os.environ.copy()
    cmd = [sys.executable, os.path.join(WORKSPACE, "scripts", name)] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    if r.returncode != 0:
        return {"error": r.stderr or f"{name} failed"}
    return json.loads(r.stdout)

def check_trading_stopped():
    path = os.path.join(WORKSPACE, ".trading_stopped")
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return int(f.read().strip())
    except:
        return 0

def calc_sl_count(bills_data):
    count = 0
    if isinstance(bills_data, dict) and bills_data.get("code") == "0":
        for r in bills_data.get("data", []):
            if r.get("instId") != "ETH-USDT-SWAP":
                continue
            sub = int(r.get("subType", -1))
            if sub in {4, 6, 110, 111, 112}:
                pnl = float(r.get("pnl", "0") or "0")
                if pnl < 0:
                    count += 1
    return count

def calc_daily_loss(bills_data):
    if not isinstance(bills_data, dict) or bills_data.get("code") != "0":
        return None, 0
    records = bills_data.get("data", [])
    total = 0.0
    matched = 0
    for r in records:
        if r.get("instId") != "ETH-USDT-SWAP":
            continue
        sub = int(r.get("subType", -1))
        if sub not in {4, 6, 110, 111, 112}:
            continue
        total += float(r.get("pnl", "0") or "0")
        matched += 1
    return total, matched

def base_gap(total):
    if total <= 0: return 5
    elif total == 1: return 6
    elif total == 2: return 7
    elif total == 3: return 8
    elif total == 4: return 9
    elif total <= 6: return 10
    elif total <= 10: return 11
    elif total <= 15: return 12
    else: return 14

def main():
    load_env()
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "env_loaded": bool(os.environ.get("OKX_API_KEY")),
        "should_stop": False,
        "stop_reason": "",
        "risk": {},
        "market": {},
        "orders": {},
        "positions": {},
        "totals": {},
        "suggested_gap": 5,
        "recommendation": "",
    }

    if not payload["env_loaded"]:
        payload["should_stop"] = True
        payload["stop_reason"] = "Missing API credentials"
        print(json.dumps(payload, indent=2))
        return

    stopped = check_trading_stopped()
    payload["risk"]["stopped_count"] = stopped
    if stopped >= 3:
        payload["should_stop"] = True
        payload["stop_reason"] = f"Consecutive stop-loss limit reached ({stopped} >= 3)"
        print(json.dumps(payload, indent=2))
        return

    bills = run_script("get_bills.py", "--today")
    daily_pnl, matched = calc_daily_loss(bills)
    sl_count = calc_sl_count(bills)
    payload["risk"]["daily_pnl"] = round(daily_pnl, 4) if daily_pnl is not None else None
    payload["risk"]["daily_pnl_matched_records"] = matched
    payload["risk"]["sl_count_today"] = sl_count
    if daily_pnl is not None and daily_pnl < -40:
        payload["should_stop"] = True
        payload["stop_reason"] = f"Daily loss limit exceeded ({daily_pnl} USDT)"
        print(json.dumps(payload, indent=2))
        return

    analyzer = run_script("eth_market_analyzer.py")
    if "error" in analyzer:
        payload["should_stop"] = True
        payload["stop_reason"] = f"Market analyzer error: {analyzer['error']}"
        print(json.dumps(payload, indent=2))
        return

    market = analyzer.get("market", {})
    hourly = analyzer.get("hourly_stats", {})
    last = market.get("last", 0)
    change24h_pct = market.get("change24h_pct", 0)

    payload["market"] = {
        "last": last,
        "open24h": market.get("open24h", 0),
        "change24h_pct": change24h_pct,
        "trend_1h": hourly.get("trend_1h", "sideways"),
        "volatility_1h": hourly.get("volatility_1h", 0),
        "recent_change_1h_pct": hourly.get("recent_change_1h_pct", 0),
    }

    orders_list = analyzer.get("orders", [])
    positions_list = analyzer.get("positions", [])

    short_orders = []
    long_orders = []
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        if o.get("ordType") != "limit":
            continue
        side = o.get("side")
        pos_side = o.get("posSide")
        px = float(o.get("px", 0))
        attach = o.get("attachAlgoOrds", [{}])[0]
        entry = {"ordId": o.get("ordId"), "px": px, "tp": attach.get("tpTriggerPx", ""), "sl": attach.get("slTriggerPx", "")}
        if side == "sell" and pos_side == "short":
            short_orders.append(entry)
        elif side == "buy" and pos_side == "long":
            long_orders.append(entry)

    short_pos = 0.0
    long_pos = 0.0
    for p in positions_list:
        if p.get("instId") != "ETH-USDT-SWAP":
            continue
        if str(p.get("lever")) != "10" or p.get("mgnMode") != "isolated":
            continue
        sz = float(p.get("pos", "0") or "0")
        if p.get("posSide") == "short":
            short_pos += sz
        elif p.get("posSide") == "long":
            long_pos += sz

    short_pos_units = short_pos / 0.1
    long_pos_units = long_pos / 0.1
    orders_count = len(short_orders) + len(long_orders)
    positions_count = short_pos_units + long_pos_units
    total = orders_count + positions_count
    remaining_capacity = math.floor(20 - total)
    gap = base_gap(total)

    vol = payload["market"]["volatility_1h"]
    if vol > 25:
        gap += 4
    elif vol > 15:
        gap += 2

    far_orders = []
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        px = float(o.get("px", "0") or "0")
        if abs(px - last) > 100:
            far_orders.append({"ordId": o.get("ordId"), "px": px, "side": o.get("side"), "posSide": o.get("posSide")})

    payload["orders"] = {
        "short_orders": short_orders,
        "long_orders": long_orders,
        "far_orders_to_cancel": far_orders,
    }
    payload["positions"] = {
        "short_pos": short_pos,
        "long_pos": long_pos,
        "short_pos_units": short_pos_units,
        "long_pos_units": long_pos_units,
    }
    payload["totals"] = {
        "short_orders_count": len(short_orders),
        "long_orders_count": len(long_orders),
        "orders_count": orders_count,
        "positions_count": positions_count,
        "total": total,
        "remaining_capacity": remaining_capacity,
    }
    payload["suggested_gap"] = gap

    if remaining_capacity <= 0:
        payload["recommendation"] = "No new orders. Total exposure at limit."
    else:
        payload["recommendation"] = f"Could place up to {remaining_capacity} new orders. Gap base = {gap}. Review trend for target_long/target_short."

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
