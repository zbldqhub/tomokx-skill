#!/usr/bin/env python3
"""
One-shot trading cycle diagnostic for openclaw (Linux).
Uses pure REST API (no CLI). Does NOT place/cancel orders.
"""
import os
import sys
import json
import base64
import hmac
import hashlib
import urllib.request
import math
from datetime import datetime, timezone, timedelta


def _load_env_file():
    env_path = os.path.expanduser("~/.openclaw/workspace/.env.trading")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = val


_load_env_file()
API_KEY = os.environ.get("OKX_API_KEY", "")
SECRET = os.environ.get("OKX_SECRET_KEY", "")
PASSPHRASE = os.environ.get("OKX_PASSPHRASE", "")
BASE = os.environ.get("OKX_BASE_URL", "https://www.okx.com")


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sign(timestamp, method, request_path, body=""):
    if body and isinstance(body, (dict, list)):
        body = json.dumps(body)
    message = timestamp + method.upper() + request_path + (body or "")
    mac = hmac.new(SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def fetch(path):
    timestamp = iso_now()
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign(timestamp, "GET", path),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
    }
    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(BASE + path, headers=headers)
        with opener.open(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        req = urllib.request.Request(BASE + path, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))


def fetch_public(path):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_market():
    ticker = fetch_public("/api/v5/market/ticker?instId=ETH-USDT-SWAP")
    candle_1h = fetch_public("/api/v5/market/candles?instId=ETH-USDT-SWAP&bar=1H&limit=24")
    return {"ticker": ticker, "candle_1h": candle_1h}


def get_orders():
    return fetch("/api/v5/trade/orders-pending?instType=SWAP&instId=ETH-USDT-SWAP&limit=100")


def get_positions():
    return fetch("/api/v5/account/positions?instType=SWAP&instId=ETH-USDT-SWAP")


def get_balance():
    return fetch("/api/v5/account/balance?ccy=USDT")


def get_bills():
    today = datetime.now(timezone.utc).date()
    begin = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = begin + timedelta(days=1)
    begin_ms = int(begin.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    path = f"/api/v5/account/bills?instType=SWAP&instId=ETH-USDT-SWAP&begin={begin_ms}&end={end_ms}&limit=100"
    return fetch(path)


def analyze_1h(candle_1h):
    data = candle_1h.get("data", [])
    if not data:
        return {"volatility_1h": 0, "trend_1h": "sideways", "recent_change_1h_pct": 0}
    highs = [float(x[2]) for x in data]
    lows = [float(x[3]) for x in data]
    opens = [float(x[1]) for x in data]
    closes = [float(x[4]) for x in data]
    recent = closes[-1]
    past = closes[0] if len(closes) >= 24 else opens[0]
    avg_range = sum(h - l for h, l in zip(highs, lows)) / len(data)
    change_pct = ((recent - past) / past) * 100 if past else 0
    if change_pct > 0.5:
        trend = "bullish"
    elif change_pct < -0.5:
        trend = "bearish"
    else:
        trend = "sideways"
    return {
        "volatility_1h": round(avg_range, 2),
        "trend_1h": trend,
        "recent_change_1h_pct": round(change_pct, 2),
    }


def check_trading_stopped():
    path = os.path.expanduser("~/.openclaw/workspace/.trading_stopped")
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
    print("ETH Trader Cycle Check (openclaw / REST API)")
    print("=" * 50)

    stopped = check_trading_stopped()
    print(f"\n[Step 1] Trading stopped count: {stopped}")
    if stopped >= 3:
        print("🛑 STOP: consecutive stop-loss limit reached.")
        return

    bills = get_bills()
    daily_pnl, info = calc_daily_loss(bills)
    print(f"\n[Step 1.2] Daily net realized P&L: {daily_pnl} USDT ({info})")
    if daily_pnl is not None and daily_pnl < -40:
        print("🛑 STOP: daily loss limit exceeded.")
        return

    market_raw = get_market()
    orders_raw = get_orders()
    positions_raw = get_positions()
    balance_raw = get_balance()

    ticker_data = market_raw.get("ticker", {}).get("data", [{}])[0]
    last = float(ticker_data.get("last", 0))
    open24h = float(ticker_data.get("open24h", 0))
    change24h_pct = ((last - open24h) / open24h) * 100 if open24h else 0
    stats = analyze_1h(market_raw.get("candle_1h", {}))

    print(f"\n[Step 1.5] Market snapshot:")
    print(f"  Price: {last} | 24h change: {round(change24h_pct, 2)}% | Trend(1h): {stats['trend_1h']} | Volatility(1h): {stats['volatility_1h']}")

    orders_list = orders_raw.get("data", []) if isinstance(orders_raw, dict) else []
    positions_list = positions_raw.get("data", []) if isinstance(positions_raw, dict) else []

    short_orders, long_orders = classify_orders(orders_list)
    short_pos, long_pos = classify_positions(positions_list)

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

    far_orders = []
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        px = float(o.get("px", "0") or "0")
        if abs(px - last) > 100:
            far_orders.append(o)
    print(f"\n[Step 6] Far orders (>100 USDT away): {len(far_orders)}")
    for o in far_orders:
        print(f"  -> Would cancel ordId={o.get('ordId')} px={o.get('px')}")

    print(f"\n[Step 7/8] Decision:")
    if remaining_capacity <= 0:
        print("  -> NO new orders placed (remaining capacity = 0).")
    else:
        print(f"  -> Could place up to {remaining_capacity} new orders (dry-run, no action).")

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

    print(f"\n[Step 10] Log: OK | Cycle check complete. No action taken.")
    print("=" * 50)


if __name__ == "__main__":
    main()
