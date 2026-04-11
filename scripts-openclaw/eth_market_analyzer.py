#!/usr/bin/env python3
"""
ETH Market Data Aggregator for tomokx-openclaw skill.
Fetches market data, orders, positions, and balance.
Outputs a single JSON for AI decision making.
"""

import json
import subprocess
import time
import os

ENV_FILE = os.path.expanduser("~/.openclaw/workspace/.env.trading")

def load_env():
    """Load KEY=VAL pairs from bash-style .env file into os.environ."""
    env = os.environ.copy()
    if not os.path.exists(ENV_FILE):
        return env
    with open(ENV_FILE, "r", encoding="utf-8") as f:
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
                env[key] = val
    return env

ENV = load_env()

def run_cmd(cmd_list, timeout=30):
    """Run a command with env loaded via bash."""
    env_bash = f"source {ENV_FILE} && " + " ".join(cmd_list)
    try:
        result = subprocess.run(
            ["bash", "-c", env_bash],
            capture_output=True,
            timeout=timeout,
        )
        stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ""
        stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ""
        return stdout, stderr, result.returncode
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
        # okx CLI uses exactly two spaces as delimiter in key-value mode
        parts = [p.strip() for p in line.split("  ") if p.strip()]
        if len(parts) >= 2:
            key = parts[0]
            val = " ".join(parts[1:])
            result[key] = val
    return result

def parse_table_output(stdout):
    """Parse okx CLI table-like output into list of dicts."""
    lines = [
        l for l in stdout.splitlines()
        if l.strip()
        and not l.startswith("[")
        and not l.startswith("Update")
        and not l.strip().startswith("Environment:")
    ]
    if not lines:
        return []

    # Find header row: it should contain multiple known column names
    header_idx = -1
    known_cols = {"ordId", "instId", "side", "posSide", "type", "price", "size", "state", "ccy", "availEq", "eq", "lever", "avgPx", "upl", "uplRatio"}
    for i, line in enumerate(lines):
        tokens = set(line.strip().split())
        if len(tokens.intersection(known_cols)) >= 2:
            header_idx = i
            break

    if header_idx == -1 or header_idx >= len(lines):
        return []

    headers = [h.strip() for h in lines[header_idx].split() if h.strip()]
    data = []

    for i in range(header_idx + 1, len(lines)):
        line = lines[i]
        # Skip separator lines and version lines
        if "-----" in line or line.strip().startswith("Version:"):
            continue
        # Skip lines that look like headers or empty
        if not line.strip():
            continue
        tokens = set(line.strip().split())
        if len(tokens.intersection(known_cols)) >= 2:
            continue
        parts = line.split()
        if len(parts) >= len(headers):
            row = {}
            for idx, h in enumerate(headers):
                if idx < len(parts):
                    row[h] = parts[idx]
            data.append(row)
    return data

def parse_cli_json(stdout):
    """Parse OKX CLI --json output (v1.3.0 raw list/object or <=v1.2.7 wrapped)."""
    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "data" in data:
                return data.get("data", [])
            return [data]
    except json.JSONDecodeError:
        pass

    # Fallback: extract first JSON array from mixed text
    start = stdout.find("[")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(stdout)):
            c = stdout[i]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if not in_string:
                if c == '[':
                    depth += 1
                elif c == ']':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(stdout[start:i+1])
                        except json.JSONDecodeError:
                            break

    # Final fallback: wrapped object extraction
    obj = extract_json(stdout)
    if obj and isinstance(obj, dict) and "data" in obj:
        return obj.get("data", [])
    if obj and isinstance(obj, dict):
        return [obj]
    return []

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
            capture_output=True, timeout=20,
        )
        stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ""
        stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ""
        if result.returncode != 0:
            return {"error": stderr or "curl ticker failed", "rc": result.returncode}
        obj = json.loads(stdout)
        if obj.get("code") == "0" and obj.get("data"):
            d = obj["data"][0]
            return {
                "last": d.get("last", ""),
                "open24h": d.get("open24h", ""),
                "high24h": d.get("high24h", ""),
                "low24h": d.get("low24h", ""),
                "bidPx": d.get("bidPx", ""),
                "askPx": d.get("askPx", ""),
            }
        return {"error": "ticker API error", "code": obj.get("code"), "msg": obj.get("msg")}
    except Exception as e:
        return {"error": str(e)}

def get_ticker():
    for attempt in range(2):
        stdout, stderr, rc = run_cmd(["okx", "market", "ticker", "ETH-USDT-SWAP", "--json"])
        if rc == 0:
            try:
                data = json.loads(stdout)
                if isinstance(data, list) and len(data) > 0:
                    d = data[0]
                    return {
                        "last": d.get("last", ""),
                        "open24h": d.get("open24h", ""),
                        "high24h": d.get("high24h", ""),
                        "low24h": d.get("low24h", ""),
                        "bidPx": d.get("bidPx", ""),
                        "askPx": d.get("askPx", ""),
                    }
            except json.JSONDecodeError:
                pass
            obj = extract_json(stdout)
            if obj and obj.get("code") == "0" and obj.get("data"):
                d = obj["data"][0]
                return {
                    "last": d.get("last", ""),
                    "open24h": d.get("open24h", ""),
                    "high24h": d.get("high24h", ""),
                    "low24h": d.get("low24h", ""),
                    "bidPx": d.get("bidPx", ""),
                    "askPx": d.get("askPx", ""),
                }
            kv = parse_key_value_output(stdout)
            if kv and "last" in kv:
                return {
                    "last": kv.get("last", "").replace(",", ""),
                    "open24h": kv.get("24h open", "").replace(",", ""),
                    "high24h": kv.get("24h high", "").replace(",", ""),
                    "low24h": kv.get("24h low", "").replace(",", ""),
                    "bidPx": kv.get("bidPx", "").replace(",", ""),
                    "askPx": kv.get("askPx", "").replace(",", ""),
                }
        time.sleep(3)
    return get_ticker_via_curl()

def get_candles():
    url = "https://www.okx.com/api/v5/market/history-candles?instId=ETH-USDT-SWAP&bar=1H&limit=10"
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "15", url],
            capture_output=True, timeout=20,
        )
        stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ""
        stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ""
        if result.returncode != 0:
            return {"error": stderr or "curl candles failed", "rc": result.returncode}
        obj = json.loads(stdout)
        if obj.get("code") == "0":
            return obj.get("data", [])
        return {"error": "candles API error", "code": obj.get("code"), "msg": obj.get("msg")}
    except Exception as e:
        return {"error": str(e)}

def get_orders():
    for attempt in range(3):
        stdout, stderr, rc = run_cmd(["okx", "swap", "orders", "--json"])
        if rc == 0:
            parsed = parse_cli_json(stdout)
            if parsed:
                return parsed
        time.sleep(2)
    # Fallback to table parsing for older CLI or edge cases
    stdout, stderr, rc, parsed = run_cmd_with_retry(["okx", "swap", "orders"], retries=2, delay=3)
    if rc != 0:
        return {"error": stderr or "orders failed", "rc": rc}
    return parsed if parsed else {"error": "orders empty after retry", "raw_preview": stdout[:500]}

def get_positions():
    for attempt in range(3):
        stdout, stderr, rc = run_cmd(["okx", "swap", "positions", "--json"])
        if rc == 0:
            parsed = parse_cli_json(stdout)
            if parsed:
                return parsed
        time.sleep(2)
    stdout, stderr, rc, parsed = run_cmd_with_retry(["okx", "swap", "positions"], retries=2, delay=3)
    if rc != 0:
        return {"error": stderr or "positions failed", "rc": rc}
    return parsed if parsed else {"error": "positions empty after retry", "raw_preview": stdout[:500]}

def get_balance():
    for attempt in range(3):
        stdout, stderr, rc = run_cmd(["okx", "account", "balance", "--json"])
        if rc == 0:
            parsed = parse_cli_json(stdout)
            if parsed:
                return parsed
        time.sleep(2)
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
        "timestamp": int(time.time()) * 1000,
        "market": market,
        "hourly_stats": stats,
        "orders": orders if isinstance(orders, list) else [],
        "positions": positions if isinstance(positions, list) else [],
        "balance": balance if isinstance(balance, list) else [],
    }
    
    print(json.dumps(output, indent=2, default=str))

if __name__ == "__main__":
    main()
