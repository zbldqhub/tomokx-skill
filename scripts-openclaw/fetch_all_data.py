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
import urllib.request
import concurrent.futures
from datetime import datetime, timezone, timedelta

from config import (
    API_KEY, SECRET, PASSPHRASE, WORKSPACE, ENV_FILE, MAX_TOTAL, ORDER_SIZE, LEVERAGE,
    CANCEL_THRESHOLD, STOP_FILE, DAILY_LOSS_LIMIT,
    base_gap, ensure_api_ready
)

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


# --- Public market data ---
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


# --- Inlined risk check (was check_risk.py) ---
def _iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _sign(timestamp, method, request_path, body=""):
    if body and isinstance(body, (dict, list)):
        body = json.dumps(body)
    import base64, hmac, hashlib
    message = timestamp + method.upper() + request_path + (body or "")
    mac = hmac.new(SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def _fetch_auth(path):
    timestamp = _iso_now()
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": _sign(timestamp, "GET", path),
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


def _read_trading_stopped():
    if not os.path.exists(STOP_FILE):
        return 0
    mtime = datetime.fromtimestamp(os.path.getmtime(STOP_FILE), tz=timezone.utc)
    today = datetime.now(timezone.utc).date()
    if mtime.date() != today:
        return 0
    try:
        with open(STOP_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def _fetch_today_bills():
    ensure_api_ready()
    today = datetime.now(timezone.utc).date()
    begin = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = begin + timedelta(days=1)
    begin_ms = int(begin.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    path = f"/api/v5/account/bills?instType=SWAP&instId=ETH-USDT-SWAP&begin={begin_ms}&end={end_ms}&limit=100"
    try:
        return _fetch_auth(path)
    except Exception as e:
        return {"error": str(e)}


def _calc_risk(bills_data):
    if not isinstance(bills_data, dict) or bills_data.get("code") != "0":
        return {"daily_pnl": 0.0, "matched": 0, "sl_count": 0}
    records = bills_data.get("data", [])
    daily_pnl = 0.0
    matched = 0
    sl_count = 0
    for r in records:
        if r.get("instId") != "ETH-USDT-SWAP":
            continue
        sub = int(r.get("subType", -1))
        if sub not in {4, 6, 110, 111, 112}:
            continue
        pnl = float(r.get("pnl", "0") or "0")
        daily_pnl += pnl
        matched += 1
        if pnl < 0:
            sl_count += 1
    return {"daily_pnl": daily_pnl, "matched": matched, "sl_count": sl_count}


def build_risk():
    stopped = _read_trading_stopped()
    bills = _fetch_today_bills()
    if "error" in bills:
        return {"error": bills["error"]}, {"elapsed_ms": 0, "error": bills["error"]}

    risk_vals = _calc_risk(bills)
    should_stop = False
    reason = ""
    if stopped >= 3:
        should_stop = True
        reason = f"Consecutive stop-loss limit reached ({stopped} >= 3)"
    elif risk_vals["daily_pnl"] < DAILY_LOSS_LIMIT:
        should_stop = True
        reason = f"Daily loss limit exceeded ({risk_vals['daily_pnl']} USDT)"

    return {
        "should_stop": should_stop,
        "stop_reason": reason,
        "stopped_count": stopped,
        "daily_pnl": round(risk_vals["daily_pnl"], 4),
        "daily_pnl_matched_records": risk_vals["matched"],
        "sl_count_today": risk_vals["sl_count"],
    }, {"elapsed_ms": 0, "error": ""}


# --- Inlined exposure calc (was calc_exposure.py) ---
def classify_orders(orders_list):
    short, long = 0, 0
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        if o.get("ordType") != "limit":
            continue
        side = o.get("side")
        pos_side = o.get("posSide")
        if side == "sell" and pos_side == "short":
            short += 1
        elif side == "buy" and pos_side == "long":
            long += 1
    return short, long


def classify_positions(positions_list):
    short_pos, long_pos = 0.0, 0.0
    for p in positions_list:
        if p.get("instId") != "ETH-USDT-SWAP":
            continue
        if str(p.get("lever")) != str(LEVERAGE):
            continue
        if p.get("mgnMode") != "isolated":
            continue
        sz = float(p.get("pos", "0") or "0")
        if p.get("posSide") == "short":
            short_pos += sz
        elif p.get("posSide") == "long":
            long_pos += sz
    return short_pos, long_pos


def build_exposure(orders, positions):
    orders_list = orders.get("data", []) if isinstance(orders, dict) else []
    positions_list = positions.get("data", []) if isinstance(positions, dict) else []

    short_orders, long_orders = classify_orders(orders_list)
    short_pos, long_pos = classify_positions(positions_list)

    short_pos_units = round(short_pos / ORDER_SIZE, 1)
    long_pos_units = round(long_pos / ORDER_SIZE, 1)
    orders_count = short_orders + long_orders
    positions_count = round(short_pos_units + long_pos_units, 1)
    total = round(orders_count + positions_count, 1)
    remaining = math.floor(MAX_TOTAL - total)

    return {
        "short_orders": short_orders,
        "long_orders": long_orders,
        "orders_count": orders_count,
        "short_pos": short_pos,
        "long_pos": long_pos,
        "short_pos_units": short_pos_units,
        "long_pos_units": long_pos_units,
        "positions_count": positions_count,
        "total": total,
        "remaining_capacity": remaining,
    }


# --- Main ---
def main():
    # Step 1: market data
    market, market_diag = fetch_market()
    if "error" in market:
        payload = {"error": f"fetch_market failed: {market['error']}", "diagnostics": {"market": market_diag}}
        print(json.dumps(payload, ensure_ascii=False))
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        sys.exit(1)

    # Step 2: concurrent private/authenticated fetches (orders, positions, history) + inline risk
    t0_risk = time.time()
    risk, _ = build_risk()
    risk_elapsed = round((time.time() - t0_risk) * 1000, 1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_orders = executor.submit(run_script, "fetch_orders.py")
        future_positions = executor.submit(run_script, "fetch_positions.py")
        future_history = executor.submit(run_script, "analyze_history.py")
        orders = future_orders.result()
        positions = future_positions.result()
        history = future_history.result()

    # Validate critical results
    errors = []
    for name, data in [("fetch_orders", orders), ("fetch_positions", positions)]:
        if isinstance(data, dict) and "error" in data:
            errors.append(f"{name}: {data['error']}")
    if errors:
        payload = {
            "error": "; ".join(errors),
            "diagnostics": {
                "market": market_diag,
                "risk": {"elapsed_ms": risk_elapsed, "error": risk.get("error", "")},
                "orders": orders.get("_diag") if isinstance(orders, dict) else None,
                "positions": positions.get("_diag") if isinstance(positions, dict) else None,
                "history": history.get("_diag") if isinstance(history, dict) else None,
            }
        }
        print(json.dumps(payload, ensure_ascii=False))
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        sys.exit(1)

    # Inline exposure calc
    t0_exp = time.time()
    exposure = build_exposure(orders, positions)
    exposure_elapsed = round((time.time() - t0_exp) * 1000, 1)

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

    # Imbalance adjustment
    long_total = exposure.get("long_orders", 0) + exposure.get("long_pos_units", 0)
    short_total = exposure.get("short_orders", 0) + exposure.get("short_pos_units", 0)
    imbalance = abs(long_total - short_total)
    if imbalance >= 3:
        if long_total > short_total and target_long > 0:
            target_long = max(0, target_long - 1)
        elif short_total > long_total and target_short > 0:
            target_short = max(0, target_short - 1)

    strategy = {
        "trend": trend,
        "target_long": target_long,
        "target_short": target_short,
        "base_gap": base_gap(int(float(total))),
        "adjusted_gap": gap,
        "volatility_1h": vol,
        "spread": spread,
        "change24h_pct": change24h,
        "imbalance_score": round(imbalance, 1),
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
            "risk": {"elapsed_ms": risk_elapsed, "error": risk.get("error", "")},
            "orders": orders.get("_diag") if isinstance(orders, dict) else None,
            "positions": positions.get("_diag") if isinstance(positions, dict) else None,
            "history": history.get("_diag") if isinstance(history, dict) else None,
            "exposure": {"elapsed_ms": exposure_elapsed, "error": ""},
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
