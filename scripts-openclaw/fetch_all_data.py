#!/usr/bin/env python3
"""
Concurrently fetch all pre-trade data in one shot.
Outputs a unified JSON payload combining market, risk, orders, positions, exposure, strategy, far_orders, and history.
Includes per-task diagnostics for easier troubleshooting.
"""
import os
import sys
import json
import math
import time
import concurrent.futures
from datetime import datetime, timezone

from config import API_KEY, WORKSPACE, ENV_FILE, MAX_TOTAL, ORDER_SIZE, LEVERAGE, CANCEL_THRESHOLD, base_gap, calc_tp_sl_offset

BASE = os.environ.get("OKX_BASE_URL", "https://www.okx.com")


def _load_env_override():
    env = os.environ.copy()
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    env[k] = v
    return env


def run_script(name, *args):
    env = _load_env_override()
    cmd = [sys.executable, os.path.join(WORKSPACE, "scripts", name)] + list(args)
    t0 = time.time()
    r = __import__("subprocess").run(cmd, capture_output=True, text=True, timeout=60, env=env)
    elapsed_ms = round((time.time() - t0) * 1000, 1)
    diag = {
        "script": name,
        "elapsed_ms": elapsed_ms,
        "returncode": r.returncode,
        "stderr_snippet": (r.stderr or "")[:300],
        "stdout_snippet": (r.stdout or "")[:200],
    }
    if r.returncode != 0:
        return {"error": r.stderr or f"{name} failed", "_diag": diag}
    try:
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            data["_diag"] = diag
        return data
    except json.JSONDecodeError:
        return {"error": f"{name} returned invalid JSON", "raw": r.stdout[:500], "_diag": diag}


def fetch_public(path):
    import urllib.request
    t0 = time.time()
    try:
        req = urllib.request.Request(BASE + path)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed_ms = round((time.time() - t0) * 1000, 1)
            return data, {"path": path, "elapsed_ms": elapsed_ms, "error": ""}
    except Exception as e:
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        return {"error": str(e)}, {"path": path, "elapsed_ms": elapsed_ms, "error": str(e)[:300]}


def fetch_market():
    ticker, ticker_diag = fetch_public("/api/v5/market/ticker?instId=ETH-USDT-SWAP")
    candle_1h, candle_diag = fetch_public("/api/v5/market/candles?instId=ETH-USDT-SWAP&bar=1H&limit=24")
    if "error" in ticker or "error" in candle_1h:
        err_parts = []
        if "error" in ticker:
            err_parts.append(f"ticker: {ticker['error']}")
        if "error" in candle_1h:
            err_parts.append(f"candle: {candle_1h['error']}")
        return {"error": "; ".join(err_parts)}, {"ticker": ticker_diag, "candle": candle_diag}

    ticker_data = ticker.get("data", [{}])[0]
    last = float(ticker_data.get("last", 0))
    bid_px = float(ticker_data.get("bidPx", last))
    ask_px = float(ticker_data.get("askPx", last))
    spread = round(ask_px - bid_px, 2)
    bid_sz = float(ticker_data.get("bidSz", 0))
    ask_sz = float(ticker_data.get("askSz", 0))
    open24h = float(ticker_data.get("open24h", 0))
    change24h_pct = ((last - open24h) / open24h) * 100 if open24h else 0

    data = candle_1h.get("data", [])
    if data:
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
        stats = {
            "volatility_1h": round(avg_range, 2),
            "trend_1h": trend,
            "recent_change_1h_pct": round(change_pct, 2),
        }
    else:
        stats = {"volatility_1h": 0, "trend_1h": "sideways", "recent_change_1h_pct": 0}

    return {
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
        **stats,
    }, {"ticker": ticker_diag, "candle": candle_diag}


def main():
    # Step 1: market data (fast public API, run directly)
    market, market_diag = fetch_market()
    if "error" in market:
        payload = {"error": f"fetch_market failed: {market['error']}", "diagnostics": {"market": market_diag}}
        print(json.dumps(payload, ensure_ascii=False))
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        sys.exit(1)

    # Step 2: concurrent private/authenticated fetches
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_risk = executor.submit(run_script, "check_risk.py")
        future_orders = executor.submit(run_script, "fetch_orders.py")
        future_positions = executor.submit(run_script, "fetch_positions.py")
        future_history = executor.submit(run_script, "analyze_history.py")

        risk = future_risk.result()
        orders = future_orders.result()
        positions = future_positions.result()
        history = future_history.result()

    # Validate critical results
    errors = []
    for name, data in [("check_risk", risk), ("fetch_orders", orders), ("fetch_positions", positions)]:
        if isinstance(data, dict) and "error" in data:
            errors.append(f"{name}: {data['error']}")
    if errors:
        payload = {
            "error": "; ".join(errors),
            "diagnostics": {
                "market": market_diag,
                "risk": risk.get("_diag") if isinstance(risk, dict) else None,
                "orders": orders.get("_diag") if isinstance(orders, dict) else None,
                "positions": positions.get("_diag") if isinstance(positions, dict) else None,
                "history": history.get("_diag") if isinstance(history, dict) else None,
            }
        }
        print(json.dumps(payload, ensure_ascii=False))
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        sys.exit(1)

    # Exposure (write temp files because calc_exposure expects file paths)
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as fo:
        json.dump(orders, fo)
        orders_path = fo.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as fp:
        json.dump(positions, fp)
        positions_path = fp.name
    exposure = run_script("calc_exposure.py", orders_path, positions_path)
    try:
        os.remove(orders_path)
        os.remove(positions_path)
    except Exception:
        pass
    if "error" in exposure:
        payload = {"error": f"calc_exposure failed: {exposure['error']}", "diagnostics": {"market": market_diag}}
        print(json.dumps(payload, ensure_ascii=False))
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        sys.exit(1)

    total = exposure.get("total", 0)

    # Strategy
    gap = base_gap(int(float(total)))
    vol = market.get("volatility_1h", 0)
    spread = market.get("spread", 0)
    if vol > 25:
        gap += 4
    elif vol > 15:
        gap += 2
    if spread > 0.5:
        gap += 1

    change24h = market.get("change24h_pct", 0)
    trend_1h = market.get("trend_1h", "sideways")
    if trend_1h in ("bullish", "bearish", "sideways"):
        trend = trend_1h
    elif change24h > 2:
        trend = "bullish"
    elif change24h < -2:
        trend = "bearish"
    else:
        trend = "sideways"

    targets = {"bullish": (2, 1), "bearish": (1, 2), "sideways": (1, 2)}
    target_long, target_short = targets.get(trend, (1, 2))

    strategy = {
        "trend": trend,
        "target_long": target_long,
        "target_short": target_short,
        "base_gap": base_gap(int(float(total))),
        "adjusted_gap": gap,
        "volatility_1h": vol,
        "spread": spread,
        "change24h_pct": change24h,
    }

    # Far orders
    current_price = market.get("last", 0)
    orders_list = orders.get("data", []) if isinstance(orders, dict) else []
    far_orders = []
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        px = float(o.get("px", "0") or "0")
        if abs(px - current_price) > CANCEL_THRESHOLD:
            far_orders.append({
                "instId": "ETH-USDT-SWAP",
                "ordId": o.get("ordId"),
                "px": px,
                "side": o.get("side"),
                "posSide": o.get("posSide"),
            })

    # Depth liquidity warning
    liquidity_warning = ""
    if spread > 2 and bid_sz < 10 and ask_sz < 10:
        liquidity_warning = "极低流动性警告：spread > 2 USDT 且双边深度均 < 10 ETH"

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "risk": risk,
        "orders": orders,
        "positions": positions,
        "exposure": exposure,
        "strategy": strategy,
        "far_orders": {"far_orders": far_orders, "threshold": CANCEL_THRESHOLD, "current_price": current_price},
        "history": history,
        "liquidity_warning": liquidity_warning,
        "diagnostics": {
            "market": market_diag,
            "risk": risk.get("_diag"),
            "orders": orders.get("_diag"),
            "positions": positions.get("_diag"),
            "history": history.get("_diag"),
            "exposure": exposure.get("_diag"),
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
