#!/usr/bin/env python3
"""Fetch ETH-USDT-SWAP market data (ticker + 1h candles)."""
import json
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.okx.com"


def fetch_public(path):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
        ticker = fetch_public("/api/v5/market/ticker?instId=ETH-USDT-SWAP")
        candle_1h = fetch_public("/api/v5/market/candles?instId=ETH-USDT-SWAP&bar=1H&limit=24")
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return

    ticker_data = ticker.get("data", [{}])[0]
    last = float(ticker_data.get("last", 0))
    bid_px = float(ticker_data.get("bidPx", last))
    ask_px = float(ticker_data.get("askPx", last))
    spread = round(ask_px - bid_px, 2)
    bid_sz = float(ticker_data.get("bidSz", 0))
    ask_sz = float(ticker_data.get("askSz", 0))
    open24h = float(ticker_data.get("open24h", 0))
    change24h_pct = ((last - open24h) / open24h) * 100 if open24h else 0
    stats = analyze_1h(candle_1h)

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last": last,
        "bidPx": bid_px,
        "askPx": ask_px,
        "spread": spread,
        "bidSz": bid_sz,
        "askSz": ask_sz,
        "open24h": open24h,
        "high24h": float(ticker_data.get("high24h", 0)),
        "low24h": float(ticker_data.get("low24h", 0)),
        "change24h_pct": round(change24h_pct, 2),
        "trend_1h": stats["trend_1h"],
        "volatility_1h": stats["volatility_1h"],
        "recent_change_1h_pct": stats["recent_change_1h_pct"],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
