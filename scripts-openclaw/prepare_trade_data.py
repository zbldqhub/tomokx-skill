#!/usr/bin/env python3
"""
Prepare all pre-trade data in one shot for openclaw (Linux).
Outputs a JSON decision payload so AI only needs to analyze & decide.
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
        pnl = float(r.get("pnl", "0") or "0")
        total += pnl
        matched += 1
    return total, matched


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
        try:
            float(o.get("sz", "0"))
        except:
            continue
        side = o.get("side")
        pos_side = o.get("posSide")
        if side == "sell" and pos_side == "short":
            short_orders.append({"ordId": o.get("ordId"), "px": float(o.get("px", 0)), "tp": o.get("attachAlgoOrds", [{}])[0].get("tpTriggerPx", ""), "sl": o.get("attachAlgoOrds", [{}])[0].get("slTriggerPx", "")})
        elif side == "buy" and pos_side == "long":
            long_orders.append({"ordId": o.get("ordId"), "px": float(o.get("px", 0)), "tp": o.get("attachAlgoOrds", [{}])[0].get("tpTriggerPx", ""), "sl": o.get("attachAlgoOrds", [{}])[0].get("slTriggerPx", "")})
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


def base_gap(total):
    if total <= 0:
        return 5
    elif total == 1:
        return 6
    elif total == 2:
        return 7
    elif total == 3:
        return 8
    elif total == 4:
        return 9
    elif total <= 6:
        return 10
    elif total <= 10:
        return 11
    elif total <= 15:
        return 12
    else:
        return 14


def main():
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "env_loaded": bool(API_KEY and SECRET and PASSPHRASE),
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
        payload["stop_reason"] = "Missing API credentials in ~/.openclaw/workspace/.env.trading"
        print(json.dumps(payload, indent=2))
        return

    stopped = check_trading_stopped()
    payload["risk"]["stopped_count"] = stopped
    if stopped >= 3:
        payload["should_stop"] = True
        payload["stop_reason"] = f"Consecutive stop-loss limit reached ({stopped} >= 3)"
        print(json.dumps(payload, indent=2))
        return

    bills = get_bills()
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

    market_raw = get_market()
    orders_raw = get_orders()
    positions_raw = get_positions()

    ticker_data = market_raw.get("ticker", {}).get("data", [{}])[0]
    last = float(ticker_data.get("last", 0))
    open24h = float(ticker_data.get("open24h", 0))
    change24h_pct = ((last - open24h) / open24h) * 100 if open24h else 0
    stats = analyze_1h(market_raw.get("candle_1h", {}))

    payload["market"] = {
        "last": last,
        "open24h": open24h,
        "change24h_pct": round(change24h_pct, 2),
        "trend_1h": stats["trend_1h"],
        "volatility_1h": stats["volatility_1h"],
        "recent_change_1h_pct": stats["recent_change_1h_pct"],
    }

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
    gap = base_gap(total)

    # volatility adjustment hint
    if stats["volatility_1h"] > 25:
        gap += 4
    elif stats["volatility_1h"] > 15:
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
        "short_orders_count": short_orders_count,
        "long_orders_count": long_orders_count,
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
