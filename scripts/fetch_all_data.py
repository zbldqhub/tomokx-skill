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
import subprocess
import shutil
from datetime import datetime, timezone, timedelta

from config import (
    API_KEY, SECRET, PASSPHRASE, WORKSPACE, ENV_FILE, MAX_TOTAL, ORDER_SIZE, LEVERAGE,
    CANCEL_THRESHOLD, STOP_FILE, DAILY_LOSS_LIMIT,
    base_gap, calc_atr, ensure_api_ready, classify_orders, classify_positions, calc_order_size
)

BASE = os.environ.get("OKX_BASE_URL", "https://www.okx.com")

# Inject .env.trading into os.environ so downstream code (including fetch_public) sees proxy settings
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)


def _ssl_context():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    return ctx


COOLDOWN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sl_cooldown.json")
COOLDOWN_MINUTES = 30


def _check_sl_cooldown():
    """Check if any side is within the post-SL cooldown period."""
    if not os.path.exists(COOLDOWN_FILE):
        return {}
    try:
        with open(COOLDOWN_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        now = datetime.now(timezone.utc)
        result = {}
        for side, entry in data.items():
            last_sl = entry.get("last_sl_time", "")
            if last_sl:
                try:
                    t = datetime.fromisoformat(last_sl.replace("Z", "+00:00"))
                    elapsed = (now - t).total_seconds() / 60
                    if elapsed < COOLDOWN_MINUTES:
                        result[side] = {"remaining_min": round(COOLDOWN_MINUTES - elapsed, 1)}
                except Exception:
                    continue
        return result
    except Exception:
        return {}


def _load_env_override():
    env = os.environ.copy()
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8-sig") as f:
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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, os.path.join(script_dir, name)] + list(args)
    t0 = time.time()
    r = __import__("subprocess").run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=60, env=env)
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
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        if proxy:
            handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            https_handler = urllib.request.HTTPSHandler(context=_ssl_context())
            opener = urllib.request.build_opener(handler, https_handler)
            with opener.open(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                elapsed_ms = round((time.time() - t0) * 1000, 1)
                return data, {"path": path, "elapsed_ms": elapsed_ms, "error": ""}
        else:
            with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                elapsed_ms = round((time.time() - t0) * 1000, 1)
                return data, {"path": path, "elapsed_ms": elapsed_ms, "error": ""}
    except Exception as e:
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        return {"error": str(e)}, {"path": path, "elapsed_ms": elapsed_ms, "error": str(e)[:300]}


def _calc_trend_from_candles(data, threshold=0.3):
    if not data or len(data) < 2:
        return "sideways", 0, 0
    highs = [float(x[2]) for x in data]
    lows = [float(x[3]) for x in data]
    opens = [float(x[1]) for x in data]
    closes = [float(x[4]) for x in data]
    recent = closes[-1]
    past = closes[0] if len(closes) >= len(data) else opens[0]
    avg_range = sum(h - l for h, l in zip(highs, lows)) / len(data)
    change_pct = ((recent - past) / past) * 100 if past else 0
    if change_pct > threshold:
        trend = "bullish"
    elif change_pct < -threshold:
        trend = "bearish"
    else:
        trend = "sideways"
    return trend, round(avg_range, 2), round(change_pct, 2)


def _calc_microstructure(trades, books, candle_5m, funding_hist, current_funding, last, bid_px, ask_px, bid_sz, ask_sz, vol24h):
    """Compute enriched microstructure signals."""
    result = {
        "depth_ratio": round(bid_sz / ask_sz, 2) if ask_sz > 0 else 999.0,
        "order_book_imbalance": 0.0,
        "buy_pressure": 0.0,
        "sell_pressure": 0.0,
        "pressure_ratio": 1.0,
        "large_trade_count": 0,
        "price_velocity_5m_pct": 0.0,
        "volume_24h": float(vol24h) if vol24h else 0.0,
        "funding_velocity": 0.0,
    }

    # Order book imbalance within 1% of mid price
    if isinstance(books, dict) and books.get("code") == "0":
        book_data = books.get("data", [{}])[0]
        bids = book_data.get("bids", [])
        asks = book_data.get("asks", [])
        mid = (bid_px + ask_px) / 2
        lower = mid * 0.99
        upper = mid * 1.01
        bid_vol = sum(float(b[1]) for b in bids if float(b[0]) >= lower)
        ask_vol = sum(float(a[1]) for a in asks if float(a[0]) <= upper)
        total_vol = bid_vol + ask_vol
        if total_vol > 0:
            result["order_book_imbalance"] = round((bid_vol - ask_vol) / total_vol, 2)

    # Trade pressure and large trades
    if isinstance(trades, dict) and trades.get("code") == "0":
        trade_list = trades.get("data", [])
        buy_sz = 0.0
        sell_sz = 0.0
        large_count = 0
        for t in trade_list:
            sz = float(t.get("sz", 0))
            side = t.get("side", "")
            if side == "buy":
                buy_sz += sz
            elif side == "sell":
                sell_sz += sz
            if sz >= 10:
                large_count += 1
        result["buy_pressure"] = round(buy_sz, 2)
        result["sell_pressure"] = round(sell_sz, 2)
        result["pressure_ratio"] = round(buy_sz / sell_sz, 2) if sell_sz > 0 else 999.0
        result["large_trade_count"] = large_count

    # 5m price velocity (latest candle, OKX returns newest first)
    if isinstance(candle_5m, dict) and candle_5m.get("code") == "0":
        data_5m = candle_5m.get("data", [])
        if data_5m:
            latest = data_5m[0]
            o5 = float(latest[1])
            c5 = float(latest[4])
            result["price_velocity_5m_pct"] = round(((c5 - o5) / o5) * 100, 2) if o5 else 0.0

    # Funding velocity vs previous period
    if isinstance(funding_hist, dict) and funding_hist.get("code") == "0":
        hist = funding_hist.get("data", [])
        if len(hist) >= 2:
            prev = float(hist[1].get("fundingRate", "0") or "0") * 100
            result["funding_velocity"] = round(current_funding - prev, 4)

    return result


def fetch_market():
    # Core endpoints
    ticker, ticker_diag = fetch_public("/api/v5/market/ticker?instId=ETH-USDT-SWAP")
    candle_1h, candle_1h_diag = fetch_public("/api/v5/market/candles?instId=ETH-USDT-SWAP&bar=1H&limit=24")
    candle_4h, candle_4h_diag = fetch_public("/api/v5/market/candles?instId=ETH-USDT-SWAP&bar=4H&limit=24")
    candle_15m, candle_15m_diag = fetch_public("/api/v5/market/candles?instId=ETH-USDT-SWAP&bar=15m&limit=48")
    funding, funding_diag = fetch_public("/api/v5/public/funding-rate?instId=ETH-USDT-SWAP")

    # Microstructure endpoints (concurrent)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_trades = executor.submit(fetch_public, "/api/v5/market/trades?instId=ETH-USDT-SWAP&limit=100")
        future_books = executor.submit(fetch_public, "/api/v5/market/books?instId=ETH-USDT-SWAP&sz=50")
        future_candle_5m = executor.submit(fetch_public, "/api/v5/market/candles?instId=ETH-USDT-SWAP&bar=5m&limit=12")
        future_funding_hist = executor.submit(fetch_public, "/api/v5/public/funding-rate-history?instId=ETH-USDT-SWAP&limit=2")

    trades, trades_diag = future_trades.result()
    books, books_diag = future_books.result()
    candle_5m, candle_5m_diag = future_candle_5m.result()
    funding_hist, funding_hist_diag = future_funding_hist.result()

    errors = []
    for name, obj in [("ticker", ticker), ("candle_1h", candle_1h), ("candle_4h", candle_4h), ("candle_15m", candle_15m)]:
        if isinstance(obj, dict) and "error" in obj:
            errors.append(f"{name}: {obj['error']}")
    if errors:
        return {"error": "; ".join(errors)}, {
            "ticker": ticker_diag,
            "candle_1h": candle_1h_diag,
            "candle_4h": candle_4h_diag,
            "candle_15m": candle_15m_diag,
            "funding": funding_diag,
        }

    ticker_data = ticker.get("data", [{}])[0]
    last = float(ticker_data.get("last", 0))
    bid_px = float(ticker_data.get("bidPx", last))
    ask_px = float(ticker_data.get("askPx", last))
    spread = round(ask_px - bid_px, 2)
    bid_sz = float(ticker_data.get("bidSz", 0))
    ask_sz = float(ticker_data.get("askSz", 0))
    open24h = float(ticker_data.get("open24h", 0))
    change24h_pct = ((last - open24h) / open24h) * 100 if open24h else 0
    vol24h = ticker_data.get("vol24h", 0)

    trend_1h, vol_1h, change_1h = _calc_trend_from_candles(candle_1h.get("data", []), threshold=0.5)
    trend_4h, vol_4h, change_4h = _calc_trend_from_candles(candle_4h.get("data", []), threshold=0.8)
    trend_15m, vol_15m, change_15m = _calc_trend_from_candles(candle_15m.get("data", []), threshold=0.2)

    # Trend alignment: 4h is primary, 1h confirms, 15m is noise filter
    if trend_4h == trend_1h == trend_15m:
        alignment = "strong"
        primary_trend = trend_4h
    elif trend_4h == trend_1h:
        alignment = "moderate"
        primary_trend = trend_4h
    elif trend_4h == trend_15m:
        alignment = "mixed"
        primary_trend = "sideways"
    else:
        alignment = "weak"
        primary_trend = "sideways"

    # Funding rate bias
    funding_rate = 0.0
    funding_bias = "neutral"
    if isinstance(funding, dict) and funding.get("code") == "0":
        funding_data = funding.get("data", [{}])[0]
        try:
            funding_rate = float(funding_data.get("fundingRate", "0") or "0") * 100
        except (ValueError, TypeError):
            funding_rate = 0.0
        if funding_rate > 0.01:
            funding_bias = "short_favored"
        elif funding_rate < -0.01:
            funding_bias = "long_favored"

    # Microstructure
    micro = _calc_microstructure(
        trades, books, candle_5m, funding_hist, funding_rate,
        last, bid_px, ask_px, bid_sz, ask_sz, vol24h
    )

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
        "volatility_1h": vol_1h,
        "trend_1h": trend_1h,
        "recent_change_1h_pct": change_1h,
        "volatility_4h": vol_4h,
        "trend_4h": trend_4h,
        "recent_change_4h_pct": change_4h,
        "volatility_15m": vol_15m,
        "trend_15m": trend_15m,
        "recent_change_15m_pct": change_15m,
        "trend_alignment": alignment,
        "primary_trend": primary_trend,
        "funding_rate": round(funding_rate, 4),
        "funding_bias": funding_bias,
        "microstructure": micro,
        "candle_1h": candle_1h.get("data", []),
    }, {
        "ticker": ticker_diag,
        "candle_1h": candle_1h_diag,
        "candle_4h": candle_4h_diag,
        "candle_15m": candle_15m_diag,
        "funding": funding_diag,
        "trades": trades_diag,
        "books": books_diag,
        "candle_5m": candle_5m_diag,
        "funding_history": funding_hist_diag,
    }


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
        https_handler = urllib.request.HTTPSHandler(context=_ssl_context())
        opener = urllib.request.build_opener(handler, https_handler)
        req = urllib.request.Request(BASE + path, headers=headers)
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        req = urllib.request.Request(BASE + path, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))


def _read_trading_stopped():
    if not os.path.exists(STOP_FILE):
        return 0
    mtime = datetime.fromtimestamp(os.path.getmtime(STOP_FILE), tz=timezone.utc)
    today = datetime.now(timezone.utc).date()
    if mtime.date() != today:
        return 0
    try:
        with open(STOP_FILE, "r", encoding="utf-8-sig") as f:
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
    if risk_vals["daily_pnl"] < DAILY_LOSS_LIMIT:
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
def build_exposure(orders, positions):
    orders_list = orders.get("data", []) if isinstance(orders, dict) else []
    positions_list = positions.get("data", []) if isinstance(positions, dict) else []

    short_orders_raw, long_orders_raw = classify_orders(orders_list)
    short_pos, long_pos = classify_positions(positions_list)

    short_pos_units = round(short_pos / ORDER_SIZE, 1)
    long_pos_units = round(long_pos / ORDER_SIZE, 1)
    positions_count = round(short_pos_units + long_pos_units, 1)

    # FIX: 统一 orders 和 positions 的口径为 units（sz / ORDER_SIZE），
    # 否则每单 sz=0.2 时 orders 只计 1 单，而实际等价于 2 units，
    # 导致 total 被低估、remaining_capacity 被高估，允许过度暴露。
    # 同时 short_orders/long_orders 也必须用 units，因为下游脚本
    # （calc_recommendation, calc_plan, ai_review）用它们 + pos_units 算 imbalance。
    short_orders_sz = 0.0
    long_orders_sz = 0.0
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        sz = float(o.get("sz", 0) or 0)
        ps = o.get("posSide")
        if ps == "short":
            short_orders_sz += sz
        elif ps == "long":
            long_orders_sz += sz
    short_orders = round(short_orders_sz / ORDER_SIZE, 1)
    long_orders = round(long_orders_sz / ORDER_SIZE, 1)
    orders_count = round(short_orders + long_orders, 1)
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

    def fetch_balance():
        try:
            env = os.environ.copy()
            if os.path.exists(ENV_FILE):
                with open(ENV_FILE, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("export "):
                            line = line[7:]
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            env[k] = v.strip().strip('"').strip("'")
            okx_exe = shutil.which("okx.cmd") or shutil.which("okx") or shutil.which("okx.exe")
            if not okx_exe:
                return {"error": "okx CLI not found in PATH"}
            out = subprocess.run(
                [okx_exe, "account", "balance", "--json"],
                env=env, capture_output=True, timeout=15
            ).stdout
            data = json.loads(out.decode("utf-8", errors="replace"))
            details = data[0].get("details", []) if data and len(data) > 0 else []
            usdt = next((d for d in details if d.get("ccy") == "USDT"), {})
            return {
                "total_eq": float(usdt.get("eq", "0") or "0"),
                "avail_eq": float(usdt.get("availEq", "0") or "0"),
                "cash_bal": float(usdt.get("cashBal", "0") or "0"),
            }
        except Exception as e:
            return {"error": str(e)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_orders = executor.submit(run_script, "fetch_orders.py")
        future_positions = executor.submit(run_script, "fetch_positions.py")
        future_history = executor.submit(run_script, "analyze_history.py")
        future_balance = executor.submit(fetch_balance)
        orders = future_orders.result()
        positions = future_positions.result()
        history = future_history.result()
        balance = future_balance.result()

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

    # Account balance & dynamic order size
    current_price = market.get("last", 0)
    equity = balance.get("total_eq", 0) if "error" not in balance else 0
    market["account_balance"] = balance

    # Strategy params (needed before order_size and atr fallback)
    gap = base_gap(int(float(total)))
    vol = market.get("volatility_1h", 0)
    spread = market.get("spread", 0)
    if vol > 25:
        gap += 4
    elif vol > 15:
        gap += 2
    if spread > 0.5:
        gap += 1

    # Calculate ATR for volatility-adaptive SL/TP
    atr = calc_atr(market.get("candle_1h", []))
    market["atr_1h"] = round(atr, 2) if atr else round(gap, 2)

    market["suggested_order_size"] = calc_order_size(equity, current_price, total, vol)

    primary_trend = market.get("primary_trend", "sideways")
    trend_alignment = market.get("trend_alignment", "weak")
    funding_bias = market.get("funding_bias", "neutral")
    change24h = market.get("change24h_pct", 0)

    # Use primary trend (4h-based with alignment check)
    trend = primary_trend

    # Reduce exposure when timeframes disagree
    targets = {"bullish": (2, 1), "bearish": (1, 2), "sideways": (1, 2)}
    target_long, target_short = targets.get(trend, (1, 2))

    if trend_alignment in ("mixed", "weak"):
        # Compress targets when there is disagreement
        target_long = max(0, target_long - 1)
        target_short = max(0, target_short - 1)

    # Funding rate bias: nudge target distribution
    if funding_bias == "long_favored" and target_long < 2:
        target_long = min(2, target_long + 1)
        if target_short > 0:
            target_short = max(0, target_short - 1)
    elif funding_bias == "short_favored" and target_short < 2:
        target_short = min(2, target_short + 1)
        if target_long > 0:
            target_long = max(0, target_long - 1)

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
        "trend_alignment": trend_alignment,
        "funding_bias": funding_bias,
    }

    # P3: Far orders 动态阈值——按 gap*5 或 80 取大，避免低波动时过早取消、高波动时保留过远单
    _dynamic_threshold = max(80, int(gap * 5))
    orders_list = orders.get("data", []) if isinstance(orders, dict) else []
    far_orders = []
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        px = float(o.get("px", "0") or "0")
        if abs(px - current_price) > _dynamic_threshold:
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
        "sl_cooldown": _check_sl_cooldown(),
    "strategy": strategy,
        "far_orders": {"far_orders": far_orders, "threshold": _dynamic_threshold, "current_price": current_price},
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

    # Write intermediate files for downstream scripts
    _tmp_files = {
        "market.json": market,
        "exposure.json": exposure,
        "strategy.json": strategy,
        "orders.json": orders,
        "far_orders.json": {"far_orders": far_orders, "threshold": _dynamic_threshold, "current_price": current_price},
        "history.json": history,
    }
    for _path, _data in _tmp_files.items():
        try:
            with open(_path, "w", encoding="utf-8") as _f:
                json.dump(_data, _f, indent=2, ensure_ascii=False)
        except Exception as _e:
            sys.stderr.write(f"Warning: failed to write {_path}: {_e}\n")

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
