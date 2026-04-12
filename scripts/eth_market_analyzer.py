#!/usr/bin/env python3
"""Collect OKX ETH-USDT-SWAP market snapshot, orders, positions, balance."""
import os
import sys
import json
import base64
import hmac
import hashlib
import urllib.request
from datetime import datetime, timezone

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
    return fetch("/api/v5/asset/balances?ccy=USDT")


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


def main():
    try:
        market_raw = get_market()
        orders_raw = get_orders()
        positions_raw = get_positions()
        balance_raw = get_balance()
        ticker_data = market_raw.get("ticker", {}).get("data", [{}])[0]
        last = float(ticker_data.get("last", 0))
        open24h = float(ticker_data.get("open24h", 0))
        change24h_pct = ((last - open24h) / open24h) * 100 if open24h else 0
        stats = analyze_1h(market_raw.get("candle_1h", {}))
        result = {
            "market": {
                "last": round(last, 2),
                "askPx": float(ticker_data.get("askPx", 0)),
                "bidPx": float(ticker_data.get("bidPx", 0)),
                "open24h": float(ticker_data.get("open24h", 0)),
                "change24h_pct": round(change24h_pct, 2),
            },
            "hourly_stats": stats,
            "orders": orders_raw,
            "positions": positions_raw,
            "balance": balance_raw,
        }
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()
