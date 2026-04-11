#!/usr/bin/env python3
"""
ETH Market Data Aggregator for tomokx skill.
Fetches market data, orders, positions, and balance.
Outputs a single JSON for AI decision making.
"""

import json
import subprocess
import time
import os

ENV_FILE = os.path.expanduser("~/.openclaw/workspace/.env.trading")
PROXYCHAINS_CONF = "/etc/proxychains.conf"

def run_cmd(cmd_list, timeout=30):
    """Run a command through proxychains with env loaded."""
    env_bash = f"source {ENV_FILE} && proxychains4 -f {PROXYCHAINS_CONF} " + " ".join(cmd_list)
    try:
        result = subprocess.run(
            ["bash", "-c", env_bash],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return "", str(e), 1

def run_cmd_with_retry(cmd_list, retries=2, delay=2, timeout=30):
    """Run command with retry on failure or empty table output."""
    for attempt in range(retries + 1):
        stdout, stderr, rc = run_cmd(cmd_list, timeout=timeout)
        if rc == 0:
            parsed = parse_table_output(stdout)
            if parsed:
                return stdout, stderr, rc, parsed
            # Empty parsed but rc=0: might be transient empty response
            if attempt < retries:
                time.sleep(delay)
                continue
        else:
            if attempt < retries:
                time.sleep(delay)
                continue
    return stdout, stderr, rc, []

def parse_key_value_output(stdout):
    """Parse okx CLI key-value plain text output into a dict."""
    result = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("[") or line.startswith("Update") or line.startswith("Version:"):
            continue
        if "   " in line or "\t" in line or ("  " in line and len(line.split("  ")) == 2):
            parts = [p.strip() for p in line.replace("\t", "  ").split("  ") if p.strip()]
            if len(parts) >= 2:
                key = parts[0]
                val = " ".join(parts[1:])
                result[key] = val
    return result

def parse_table_output(stdout):
    """Parse okx CLI table-like output into list of dicts."""
    lines = [l for l in stdout.splitlines() if l.strip() and not l.startswith("[") and not l.startswith("Update")]
    if not lines:
        return []
    header_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("ordId") or line.strip().startswith("instId") or line.strip().startswith("side") or line.strip().startswith("ccy") or line.strip().startswith("ETH-"):
            if i > 0:
                header_idx = i - 1
            else:
                header_idx = i
            break
    if header_idx == -1:
        for i, line in enumerate(lines):
            if any(k in line for k in ["instId", "side", "price", "size", "state", "ordId", "ccy", "availEq", "eq"]):
                header_idx = i
                break
    if header_idx == -1 or header_idx >= len(lines):
        return []
    
    headers = [h.strip() for h in lines[header_idx].split() if h.strip()]
    data = []
    sep_line = None
    for i in range(header_idx + 1, len(lines)):
        line = lines[i]
        if "-----" in line:
            sep_line = i
            continue
        if sep_line and i == sep_line:
            continue
        if not line.strip() or line.strip().startswith("Version:"):
            continue
        if not headers:
            continue
        parts = line.split()
        if len(parts) >= len(headers):
            row = {}
            for idx, h in enumerate(headers):
                if idx < len(parts):
                    row[h] = parts[idx]
            data.append(row)
    return data

def extract_json(stdout):
    """Extract the outermost JSON object from mixed stdout text."""
    start = stdout.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(stdout)):
        if stdout[i] == "{":
            depth += 1
        elif stdout[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stdout[start:i+1])
                except json.JSONDecodeError:
                    return None
    return None

def get_ticker_via_curl():
    url = "https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP"
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "15", url],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            return {"error": result.stderr or "curl ticker failed", "rc": result.returncode}
        obj = json.loads(result.stdout)
        if obj.get("code") == "0" and obj.get("data"):
            return obj["data"][0]
        return {"error": "ticker API error", "code": obj.get("code"), "msg": obj.get("msg")}
    except Exception as e:
        return {"error": str(e)}

def get_ticker():
    for attempt in range(2):
        stdout, stderr, rc = run_cmd(["okx", "market", "ticker", "ETH-USDT-SWAP"])
        if rc == 0:
            obj = extract_json(stdout)
            if obj and obj.get("code") == "0" and obj.get("data"):
                return obj["data"][0]
            kv = parse_key_value_output(stdout)
            if kv and "last" in kv:
                return {
                    "last": kv.get("last", "").replace(",", ""),
                    "open24h": kv.get("24h open", "").replace(",", ""),
                    "high24h": kv.get("24h high", "").replace(",", ""),
                    "low24h": kv.get("24h low", "").replace(",", ""),
                    "bidPx": "",
                    "askPx": "",
                }
        time.sleep(3)
    return get_ticker_via_curl()

def get_candles():
    url = "https://www.okx.com/api/v5/market/history-candles?instId=ETH-USDT-SWAP&bar=1H&limit=10"
    try:
        # Use proxychains to match the network path of CLI commands
        result = subprocess.run(
            ["proxychains4", "-f", PROXYCHAINS_CONF, "curl", "-s", "--max-time", "15", url],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            return {"error": result.stderr or "curl candles failed", "rc": result.returncode}
        obj = json.loads(result.stdout)
        if obj.get("code") == "0":
            return obj.get("data", [])
        return {"error": "candles API error", "code": obj.get("code"), "msg": obj.get("msg")}
    except Exception as e:
        return {"error": str(e)}

def get_orders():
    stdout, stderr, rc, parsed = run_cmd_with_retry(["okx", "swap", "orders"], retries=2, delay=3)
    if rc != 0:
        return {"error": stderr or "orders failed", "rc": rc}
    return parsed if parsed else {"error": "orders empty after retry", "raw_preview": stdout[:500]}

def get_positions():
    stdout, stderr, rc, parsed = run_cmd_with_retry(["okx", "swap", "positions"], retries=2, delay=3)
    if rc != 0:
        return {"error": stderr or "positions failed", "rc": rc}
    return parsed if parsed else {"error": "positions empty after retry", "raw_preview": stdout[:500]}

def get_balance():
    stdout, stderr, rc, parsed = run_cmd_with_retry(["okx", "account", "balance"], retries=2, delay=3)
    if rc != 0:
        return {"error": stderr or "balance failed", "rc": rc}
    return parsed if parsed else {"error": "balance empty after retry", "raw_preview": stdout[:500]}

def calc_hourly_stats(candles):
    if not candles or isinstance(candles, dict):
        return {"volatility_1h": None, "trend_1h": None, "candles_count": 0}
    
    closes = []
    highs = []
    lows = []
    for c in reversed(candles):
        if isinstance(c, list) and len(c) >= 5:
            closes.append(float(c[4]))
            highs.append(float(c[2]))
            lows.append(float(c[3]))
    
    if len(closes) < 2:
        return {"volatility_1h": None, "trend_1h": None, "candles_count": len(closes)}
    
    ranges = [h - l for h, l in zip(highs, lows)]
    avg_range = sum(ranges) / len(ranges)
    
    total_change = ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] != 0 else 0
    
    if len(closes) >= 3:
        recent_change = ((closes[-1] - closes[-3]) / closes[-3]) * 100 if closes[-3] != 0 else 0
    else:
        recent_change = total_change
    
    trend_1h = "sideways"
    if recent_change > 0.5:
        trend_1h = "bullish"
    elif recent_change < -0.5:
        trend_1h = "bearish"
    
    return {
        "volatility_1h": round(avg_range, 2),
        "trend_1h": trend_1h,
        "recent_change_1h_pct": round(recent_change, 2),
        "total_change_window_pct": round(total_change, 2),
        "candles_count": len(closes),
        "latest_close": closes[-1],
    }

def main():
    ticker = get_ticker()
    candles = get_candles()
    orders = get_orders()
    positions = get_positions()
    balance = get_balance()
    
    stats = calc_hourly_stats(candles)
    
    if isinstance(ticker, dict) and "error" not in ticker:
        def _num(k):
            v = ticker.get(k, "0")
            try:
                return float(str(v).replace(",", ""))
            except:
                return 0.0
        last_px = _num("last")
        open24h = _num("open24h")
        change24h_pct = round(((last_px - open24h) / open24h) * 100, 2) if open24h else 0
        market = {
            "last": last_px,
            "open24h": open24h,
            "high24h": _num("high24h"),
            "low24h": _num("low24h"),
            "change24h_pct": change24h_pct,
            "bidPx": _num("bidPx"),
            "askPx": _num("askPx"),
        }
    else:
        market = {"error": ticker.get("error", "unknown"), **ticker} if isinstance(ticker, dict) else {"error": "ticker unavailable"}
    
    output = {
        "timestamp": int(os.popen("date +%s").read().strip()) * 1000,
        "market": market,
        "hourly_stats": stats,
        "orders": orders if isinstance(orders, list) else [],
        "positions": positions if isinstance(positions, list) else [],
        "balance": balance if isinstance(balance, list) else [],
    }
    
    print(json.dumps(output, indent=2, default=str))

if __name__ == "__main__":
    main()
