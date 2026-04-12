#!/usr/bin/env python3
"""
Unified executor and finalizer for tomokx trading system.
Reads a JSON plan and performs: order execution -> stop counter update -> logging -> notification.
"""
import os
import sys
import json
import time
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta

from config import ENV_FILE, LOG_PATH, JSONL_PATH, DECISION_LOG_PATH, STOP_FILE, API_KEY, SECRET, PASSPHRASE, BASE_URL, ensure_api_ready
import base64, hmac, hashlib


# Auto-detect platform source label
SOURCE = "tomokx-openclaw" if "openclaw" in os.path.dirname(os.path.abspath(__file__)) else "tomokx"


def load_env():
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


# --- Order execution helpers ---
def run_cmd(cmd_list, env):
    cmd_str = " ".join(cmd_list)
    if sys.platform == "win32":
        r = subprocess.run(cmd_str, env=env, capture_output=True, text=True, timeout=20, shell=True, encoding="utf-8", errors="replace")
    else:
        full = f"source {ENV_FILE} && " + cmd_str
        r = subprocess.run(["bash", "-c", full], env=env, capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace")
    return r.stdout or r.stderr or ""


def cancel_order(inst_id, ord_id, env):
    out = run_cmd(["okx", "swap", "cancel", f"--instId {inst_id}", f"--ordId {ord_id}"], env)
    return out.strip()


def place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env):
    out = run_cmd([
        "okx", "swap", "place",
        f"--instId {inst_id}",
        f"--tdMode {td_mode}",
        f"--side {side}",
        f"--ordType {ord_type}",
        f"--sz {sz}",
        f"--px={px}",
        f"--posSide {pos_side}",
        f"--tpTriggerPx={tp}",
        "--tpOrdPx=-1",
        f"--slTriggerPx={sl}",
        "--slOrdPx=-1",
    ], env)
    return out.strip()


# --- Stop counter helpers ---
def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sign(timestamp, method, request_path, body=""):
    if body and isinstance(body, (dict, list)):
        body = json.dumps(body)
    message = timestamp + method.upper() + request_path + (body or "")
    mac = hmac.new(SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def fetch_okx(path):
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
        req = urllib.request.Request(BASE_URL + path, headers=headers)
        with opener.open(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        req = urllib.request.Request(BASE_URL + path, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))


def run_bills():
    ensure_api_ready()
    today = datetime.now(timezone.utc).date()
    begin = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = begin + timedelta(days=1)
    begin_ms = int(begin.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    path = f"/api/v5/account/bills?instType=SWAP&instId=ETH-USDT-SWAP&begin={begin_ms}&end={end_ms}&limit=100"
    try:
        return fetch_okx(path)
    except Exception as e:
        return {"error": str(e)}


def count_losing_closes(bills_data):
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


def read_stop_counter():
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


def write_stop_counter(value):
    with open(STOP_FILE, "w", encoding="utf-8") as f:
        f.write(str(value))


# --- Logging helpers ---
def _calc_daily_pnl(bills_data):
    if not isinstance(bills_data, dict) or bills_data.get("code") != "0":
        return None
    total = 0.0
    for r in bills_data.get("data", []):
        if r.get("instId") != "ETH-USDT-SWAP":
            continue
        try:
            sub = int(r.get("subType", -1))
        except (ValueError, TypeError):
            continue
        if sub in {4, 6, 110, 111, 112}:
            total += float(r.get("pnl", "0") or "0")
    return round(total, 4)


def _read_last_open_decision():
    if not os.path.exists(DECISION_LOG_PATH):
        return None
    last_open = None
    with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if "outcome_pnl" not in entry:
                    last_open = entry
            except json.JSONDecodeError:
                continue
    return last_open


def _update_decision_outcome(decision_id, outcome_pnl, exit_price):
    if not os.path.exists(DECISION_LOG_PATH):
        return False
    lines = []
    updated = False
    with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("decision_id") == decision_id and "outcome_pnl" not in entry:
                    entry["outcome_pnl"] = outcome_pnl
                    entry["exit_price"] = exit_price
                    entry["closed_at"] = iso_now()
                    updated = True
                lines.append(json.dumps(entry, ensure_ascii=False))
            except json.JSONDecodeError:
                lines.append(line)
    if updated:
        with open(DECISION_LOG_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return updated


def _append_decision(plan, summary, daily_pnl):
    os.makedirs(os.path.dirname(DECISION_LOG_PATH), exist_ok=True)
    reasoning = plan.get("reasoning", {})
    long_prices = []
    short_prices = []
    long_expansion = ""
    short_expansion = ""
    for p in plan.get("placements", []):
        if p.get("side") == "buy" and p.get("posSide") == "long":
            long_prices.append(p.get("px"))
        elif p.get("side") == "sell" and p.get("posSide") == "short":
            short_prices.append(p.get("px"))
    long_expansion = reasoning.get("long", {}).get("expansion_type", "")
    short_expansion = reasoning.get("short", {}).get("expansion_type", "")
    entry = {
        "decision_id": iso_now().replace(":", "").replace("-", "").replace(".", "") + "_" + str(os.getpid()),
        "timestamp": iso_now(),
        "market_state": {
            "trend": summary.get("trend", ""),
            "price": summary.get("price", ""),
            "volatility_1h": summary.get("volatility_1h", ""),
        },
        "strategy_params": {
            "gap": summary.get("gap", ""),
            "target_long": reasoning.get("long", {}).get("target"),
            "target_short": reasoning.get("short", {}).get("target"),
        },
        "actual_actions": {
            "cancellations_count": len(plan.get("cancellations", [])),
            "placements_count": len(plan.get("placements", [])),
            "long_prices": long_prices,
            "short_prices": short_prices,
            "long_expansion": long_expansion,
            "short_expansion": short_expansion,
        },
        "baseline_pnl": daily_pnl,
        "decision_source": os.environ.get("TOMOKX_DECISION_SOURCE", "ai_manual"),
    }
    with open(DECISION_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry["decision_id"]


def log_trade(summary, gap="", high24h="", low24h="", short_orders="", long_orders=""):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    trend = summary.get("trend", "unknown")
    price = summary.get("price", "")
    orders = summary.get("orders", "")
    positions = summary.get("positions", "")
    total = summary.get("total", "")
    actions = summary.get("actions", "")

    line = (
        f"[{timestamp}] | {SOURCE} | Trading Cycle Summary\n"
        f"- Market Trend: {trend}\n"
        f"- Current Price: {price} USDT\n"
        f"- Orders: {orders} live\n"
        f"- Positions: {positions} open\n"
        f"- Total Exposure: {total}/20\n"
        f"- Actions: {actions}\n"
    )

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    jsonl_entry = {
        "timestamp": timestamp,
        "source": SOURCE,
        "trend": trend,
        "price": price,
        "orders": orders,
        "positions": positions,
        "total": total,
        "actions": actions,
    }
    if gap:
        jsonl_entry["gap"] = gap
    if high24h:
        jsonl_entry["high24h"] = high24h
    if low24h:
        jsonl_entry["low24h"] = low24h
    if short_orders:
        jsonl_entry["short_orders"] = short_orders
    if long_orders:
        jsonl_entry["long_orders"] = long_orders

    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(jsonl_entry, ensure_ascii=False) + "\n")

    return f"Logged to {LOG_PATH} and {JSONL_PATH}"


# --- Main ---
def main():
    plan_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not plan_path or not os.path.exists(plan_path):
        print("Usage: python3 execute_and_finalize.py <plan.json>")
        sys.exit(1)

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    env = load_env()
    summary = plan.get("summary", {})
    actions_text = summary.get("actions", "")

    result = {
        "execution": {"cancellations": [], "placements": []},
        "stop_counter": {},
        "log": "",
    }

    # 0. Fetch bills for PnL baseline and close previous decision
    bills = run_bills()
    daily_pnl = None
    if "error" not in bills:
        daily_pnl = _calc_daily_pnl(bills)
        last_open = _read_last_open_decision()
        if last_open and daily_pnl is not None:
            baseline = last_open.get("baseline_pnl", 0)
            outcome = round(daily_pnl - baseline, 4)
            price = summary.get("price")
            _update_decision_outcome(last_open["decision_id"], outcome, price)
            print(f"[DECISION_LOG] Closed {last_open['decision_id']} with outcome_pnl={outcome}")
    else:
        print(f"[BILLS] ERROR: {bills['error']}")

    # 1. Execute orders
    for item in plan.get("cancellations", []):
        inst_id = item.get("instId", "ETH-USDT-SWAP")
        ord_id = item["ordId"]
        out = cancel_order(inst_id, ord_id, env)
        result["execution"]["cancellations"].append({"ordId": ord_id, "result": out})
        print(f"[CANCEL] {ord_id} -> {out}")

    for item in plan.get("placements", []):
        inst_id = item.get("instId", "ETH-USDT-SWAP")
        td_mode = item.get("tdMode", "isolated")
        side = item["side"]
        ord_type = item.get("ordType", "limit")
        sz = item["sz"]
        px = item["px"]
        pos_side = item["posSide"]
        tp = item["tpTriggerPx"]
        sl = item["slTriggerPx"]
        out = place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env)
        result["execution"]["placements"].append({"px": px, "side": side, "posSide": pos_side, "result": out})
        print(f"[PLACE] {side}+{pos_side} @ {px} TP={tp} SL={sl} -> {out}")
        if "429" in out or "rate limit" in out.lower():
            print("[WARN] Rate limit detected, waiting 10s...")
            time.sleep(10)
            out = place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env)
            result["execution"]["placements"][-1]["retry_result"] = out
            print(f"[RETRY] {side}+{pos_side} @ {px} -> {out}")

    # 2. Update stop counter (reuse bills)
    if "error" not in bills:
        losing = count_losing_closes(bills)
        current = read_stop_counter()
        new_value = max(current, losing)
        write_stop_counter(new_value)
        result["stop_counter"] = {
            "previous": current,
            "losing_closes_today": losing,
            "written": new_value,
            "should_stop": new_value >= 3,
        }
        print(f"[STOP_COUNTER] updated to {new_value}")
    else:
        result["stop_counter"] = {"error": bills["error"]}
        print(f"[STOP_COUNTER] ERROR: {bills['error']}")

    # 3. Log trade
    log_msg = log_trade(summary)
    result["log"] = log_msg
    print(f"[LOG] {log_msg}")

    # 4. Log decision
    if daily_pnl is not None:
        did = _append_decision(plan, summary, daily_pnl)
        print(f"[DECISION_LOG] Appended {did}")

    print("\n" + json.dumps(result, indent=2))

    # Exit with non-zero if stop counter triggered, so caller can halt
    if result.get("stop_counter", {}).get("should_stop"):
        sys.exit(2)


if __name__ == "__main__":
    main()
