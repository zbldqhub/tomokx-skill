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
import ssl
from datetime import datetime, timezone, timedelta

_ssl_ctx = ssl.create_default_context()
if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
    _ssl_ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
    _ssl_ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT

from config import ENV_FILE, LOG_PATH, JSONL_PATH, DECISION_LOG_PATH, ORDER_TRACKING_PATH, STOP_FILE, API_KEY, SECRET, PASSPHRASE, BASE_URL, ensure_api_ready, MAX_TOTAL, ORDER_SIZE
import base64, hmac, hashlib

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# Auto-detect platform source label
SOURCE = "tomokx-openclaw" if "openclaw" in os.path.dirname(os.path.abspath(__file__)) else "tomokx"


def load_env():
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


# --- Order execution helpers ---
def run_cmd(cmd_list, env):
    """Run a command safely. On Windows .cmd files cannot be executed directly
    by CreateProcess, so we wrap with cmd.exe /c. Arguments are passed as a list,
    so subprocess quotes each element correctly — no shell injection."""
    cmd = list(cmd_list)
    if sys.platform == "win32":
        # Wrap with cmd.exe /c so .cmd scripts are found and executed
        cmd = ["cmd.exe", "/c"] + cmd
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace")
    return r.stdout or r.stderr or ""


def cancel_order(inst_id, ord_id, env):
    out = run_cmd(["okx", "swap", "cancel", f"--instId={inst_id}", f"--ordId={ord_id}"], env)
    return out.strip()


def place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env):
    out = run_cmd([
        "okx", "swap", "place",
        f"--instId={inst_id}",
        f"--tdMode={td_mode}",
        f"--side={side}",
        f"--ordType={ord_type}",
        f"--sz={sz}",
        f"--px={px}",
        f"--posSide={pos_side}",
        f"--tpTriggerPx={tp}",
        "--tpOrdPx=-1",
        f"--slTriggerPx={sl}",
        "--slOrdPx=-1",
    ], env)
    out_stripped = out.strip()
    import re
    m = re.search(r'"ordId"\s*:\s*"(\d+)"', out_stripped)
    ord_id = m.group(1) if m else ""
    return {"raw": out_stripped, "ordId": ord_id}


def get_latest_price(env):
    """Fetch latest ETH-USDT-SWAP price via OKX CLI."""
    out = run_cmd(["okx", "market", "ticker", "ETH-USDT-SWAP", "--json"], env)
    try:
        data = json.loads(out.strip())
        if isinstance(data, dict):
            if data.get("code") == "0" and data.get("data"):
                return float(data["data"][0].get("last", 0))
            return float(data.get("last", 0))
    except Exception:
        pass
    return None


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
        with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))


def run_bills():
    ensure_api_ready()
    today = datetime.now(timezone.utc).date()
    begin = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = begin + timedelta(days=1)
    begin_ms = int(begin.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    path = f"/api/v5/account/bills?instType=SWAP&instId=ETH-USDT-SWAP&begin={begin_ms}&end={end_ms}&limit=100"
    for attempt in range(3):
        try:
            return fetch_okx(path)
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
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


def _update_sl_cooldown(bills_data):
    """Detect recent SL hits from bills and update sl_cooldown.json."""
    cooldown_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sl_cooldown.json")
    cooldown = {}
    if os.path.exists(cooldown_path):
        try:
            with open(cooldown_path, "r", encoding="utf-8-sig") as f:
                cooldown = json.load(f)
        except Exception:
            cooldown = {}

    now = datetime.now(timezone.utc).isoformat()
    updated = False
    if isinstance(bills_data, dict) and bills_data.get("code") == "0":
        for r in bills_data.get("data", []):
            if r.get("instId") != "ETH-USDT-SWAP":
                continue
            sub = int(r.get("subType", -1))
            # 110=SL trigger, 4=close, 6=force close, 112=liquidation
            if sub in {4, 6, 110, 112}:
                pnl = float(r.get("pnl", "0") or "0")
                if pnl < 0:
                    pos_side = r.get("posSide", "")
                    if pos_side in ("long", "short"):
                        cooldown[pos_side] = {"last_sl_time": now, "pnl": round(pnl, 4)}
                        updated = True

    if updated:
        try:
            with open(cooldown_path, "w", encoding="utf-8") as f:
                json.dump(cooldown, f, indent=2, ensure_ascii=False)
        except Exception as e:
            sys.stderr.write(f"[WARN] Failed to write sl_cooldown.json: {e}\n")
    return cooldown


def read_stop_counter():
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
    with open(DECISION_LOG_PATH, "r", encoding="utf-8-sig") as f:
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
    with open(DECISION_LOG_PATH, "r", encoding="utf-8-sig") as f:
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

    # Capture AI review metadata
    ai_review = plan.get("ai_review", {})
    original_placements = plan.get("original_placements", [])
    deleted_placements = []
    final_ord_ids = {p.get("px") for p in plan.get("placements", [])}
    for p in original_placements:
        if p.get("px") not in final_ord_ids:
            deleted_placements.append({
                "side": p.get("side"),
                "posSide": p.get("posSide"),
                "px": p.get("px"),
                "tpTriggerPx": p.get("tpTriggerPx"),
                "slTriggerPx": p.get("slTriggerPx"),
            })

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
        "ai_review": {
            "deleted_count": ai_review.get("deleted_count", 0),
            "deleted_placements": deleted_placements,
            "ai_actions": ai_review.get("ai_actions", []),
            "alignment": ai_review.get("alignment", ""),
            "imbalance": ai_review.get("imbalance", 0),
            "recommendation": ai_review.get("recommendation", ""),
        },
        "baseline_pnl": daily_pnl,
        "decision_source": os.environ.get("TOMOKX_DECISION_SOURCE", "ai_manual"),
    }
    with open(DECISION_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry["decision_id"]


def _extract_deleted_placements(plan):
    """Extract deleted placements for last_cycle_report."""
    original = plan.get("original_placements", [])
    final = plan.get("placements", [])
    final_pxs = {p.get("px") for p in final}
    deleted = []
    for p in original:
        if p.get("px") not in final_pxs:
            deleted.append({
                "side": p.get("side"),
                "posSide": p.get("posSide"),
                "px": p.get("px"),
                "tpTriggerPx": p.get("tpTriggerPx"),
                "slTriggerPx": p.get("slTriggerPx"),
            })
    return deleted


def _append_order_tracking(plan, decision_id):
    os.makedirs(os.path.dirname(ORDER_TRACKING_PATH), exist_ok=True)
    reasoning = plan.get("reasoning", {})
    market = plan.get("summary", {})
    long_expansion = reasoning.get("long", {}).get("expansion_type", "")
    short_expansion = reasoning.get("short", {}).get("expansion_type", "")
    with open(ORDER_TRACKING_PATH, "a", encoding="utf-8") as f:
        for p in plan.get("placements", []):
            side = p.get("posSide")
            expansion = long_expansion if side == "long" else short_expansion
            entry = {
                "decision_id": decision_id,
                "ordId": p.get("ordId", ""),
                "instId": p.get("instId", "ETH-USDT-SWAP"),
                "side": p.get("side"),
                "posSide": side,
                "px": p.get("px"),
                "sz": p.get("sz"),
                "tpTriggerPx": p.get("tpTriggerPx"),
                "slTriggerPx": p.get("slTriggerPx"),
                "placed_at": iso_now(),
                "market_trend": market.get("trend", ""),
                "gap": market.get("gap", ""),
                "volatility_1h": market.get("volatility_1h", ""),
                "expansion_type": expansion,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
        f"- Total Exposure: {total}/{MAX_TOTAL}\n"
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

    with open(plan_path, "r", encoding="utf-8-sig") as f:
        plan = json.load(f)

    env = load_env()
    summary = plan.get("summary", {})
    actions_text = summary.get("actions", "")

    result = {
        "execution": {"cancellations": [], "placements": []},
        "stop_counter": {},
        "log": "",
    }

    # 0. Fetch bills for PnL baseline, SL cooldown, and close previous decision
    bills = run_bills()
    daily_pnl = None
    if "error" not in bills:
        daily_pnl = _calc_daily_pnl(bills)
        _update_sl_cooldown(bills)
        last_open = _read_last_open_decision()
        if last_open and daily_pnl is not None:
            baseline = last_open.get("baseline_pnl", 0)
            outcome = round(daily_pnl - baseline, 4)
            price = summary.get("price")
            _update_decision_outcome(last_open["decision_id"], outcome, price)
            print(f"[DECISION_LOG] Closed {last_open['decision_id']} with outcome_pnl={outcome}")
    else:
        print(f"[BILLS] ERROR: {bills['error']}")

    # 1. Log decision (intent) and get decision_id before execution
    decision_id = None
    if daily_pnl is not None:
        decision_id = _append_decision(plan, summary, daily_pnl)
        print(f"[DECISION_LOG] Appended {decision_id}")

    # 2. Execute orders
    # Pre-flight exposure check
    current_total = float(summary.get("total", 0))
    planned_units = sum(float(p.get("sz", ORDER_SIZE)) / ORDER_SIZE for p in plan.get("placements", []))
    if current_total + planned_units > MAX_TOTAL:
        print(f"[WARN] Planned exposure {current_total + planned_units} would exceed MAX_TOTAL={MAX_TOTAL}. Some placements may be skipped.")

    for item in plan.get("cancellations", []):
        inst_id = item.get("instId", "ETH-USDT-SWAP")
        ord_id = item["ordId"]
        out = cancel_order(inst_id, ord_id, env)
        result["execution"]["cancellations"].append({"ordId": ord_id, "result": out})
        # Friendly handling for already-filled/cancelled orders
        if "does not exist" in out.lower() or "filled" in out.lower() or "canceled" in out.lower():
            print(f"[CANCEL] {ord_id} -> already closed (OK)")
        else:
            print(f"[CANCEL] {ord_id} -> {out}")

    gap = float(summary.get("gap", 10))
    stale_keywords = ["price failure", "expired", "not valid", "too high", "too low", "price invalid"]

    for item in plan.get("placements", []):
        # Cooldown between placements to avoid rate limits
        time.sleep(0.5)

        inst_id = item.get("instId", "ETH-USDT-SWAP")
        td_mode = item.get("tdMode", "isolated")
        side = item["side"]
        ord_type = item.get("ordType", "limit")
        sz = item["sz"]
        px = item["px"]
        pos_side = item["posSide"]
        tp = item["tpTriggerPx"]
        sl = item["slTriggerPx"]

        # Skip if this placement would breach MAX_TOTAL
        item_units = float(sz) / ORDER_SIZE
        if current_total + item_units > MAX_TOTAL:
            skip_msg = f"SKIPPED: would exceed MAX_TOTAL ({current_total}+{item_units}>{MAX_TOTAL})"
            result["execution"]["placements"].append({"px": px, "side": side, "posSide": pos_side, "ordId": "", "result": skip_msg})
            print(f"[SKIP] {side}+{pos_side} @ {px}: {skip_msg}")
            continue
        current_total += item_units

        # Pre-flight stale check
        latest_price = get_latest_price(env)
        if latest_price is not None:
            if abs(float(px) - latest_price) > gap / 2:
                skip_msg = f"SKIPPED: stale price (latest={latest_price}, gap={gap})"
                result["execution"]["placements"].append({"px": px, "side": side, "posSide": pos_side, "ordId": "", "result": skip_msg})
                print(f"[SKIP] {side}+{pos_side} @ {px}: {skip_msg}")
                continue

        place_res = place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env)
        out = place_res["raw"]
        item["ordId"] = place_res["ordId"]
        result["execution"]["placements"].append({"px": px, "side": side, "posSide": pos_side, "ordId": place_res["ordId"], "result": out})
        print(f"[PLACE] {side}+{pos_side} @ {px} TP={tp} SL={sl} -> {out}")

        # Post-flight stale check on exchange rejection
        if any(k in out.lower() for k in stale_keywords):
            stale_msg = "SKIPPED: price invalidated by exchange"
            result["execution"]["placements"][-1]["result"] += f" | {stale_msg}"
            print(f"[STALE] {side}+{pos_side} @ {px}: {stale_msg}")
            continue

        if "429" in out or "rate limit" in out.lower():
            print("[WARN] Rate limit detected, waiting 10s...")
            time.sleep(10)
            place_res = place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env)
            out = place_res["raw"]
            item["ordId"] = place_res["ordId"]
            result["execution"]["placements"][-1]["retry_result"] = out
            print(f"[RETRY] {side}+{pos_side} @ {px} -> {out}")

    # 3. Log order tracking (after execution so ordId is known)
    if decision_id:
        _append_order_tracking(plan, decision_id)
        print("[ORDER_TRACKING] Appended placements")

    # 4. Stop counter ( informational — daily loss limit is the hard stop )
    previous_stop = read_stop_counter()
    losing_closes = count_losing_closes(bills) if "error" not in bills else 0
    new_stop = previous_stop + losing_closes
    if new_stop != previous_stop:
        write_stop_counter(new_stop)
    should_stop = summary.get("should_stop", False)
    result["stop_counter"] = {
        "previous": previous_stop,
        "written": new_stop,
        "losing_closes_today": losing_closes,
        "should_stop": should_stop,
    }
    print(f"[STOP_COUNTER] {previous_stop} -> {new_stop} (losing_closes_today={losing_closes}, should_stop={should_stop})")

    # 5. Log trade
    log_msg = log_trade(summary)
    result["log"] = log_msg
    print(f"[LOG] {log_msg}")

    # 6. Trailing stop / breakeven check
    try:
        ts_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trailing_stop_manager.py")
        if os.path.exists(ts_script):
            ts_out = subprocess.run([sys.executable, ts_script], capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(f"[TRAILING_STOP] {ts_out.stdout.strip()}")
            if ts_out.stderr:
                print(f"[TRAILING_STOP_ERR] {ts_out.stderr.strip()}")
    except Exception as e:
        print(f"[TRAILING_STOP] ERROR: {e}")

    print("\n" + json.dumps(result, indent=2))

    # 7. Write last cycle report for AI continuity
    try:
        ai_review = plan.get("ai_review", {})
        last_report = {
            "executed_at": iso_now(),
            "market_state": {
                "price": summary.get("price", ""),
                "trend": summary.get("trend", ""),
                "volatility_1h": summary.get("volatility_1h", ""),
                "gap": summary.get("gap", ""),
            },
            "decision": {
                "original_placements_count": ai_review.get("original_placements_count", 0),
                "deleted_count": ai_review.get("deleted_count", 0),
                "final_placements_count": ai_review.get("final_placements_count", 0),
                "deleted_placements": _extract_deleted_placements(plan),
                "ai_actions": ai_review.get("ai_actions", []),
                "reason": summary.get("actions", ""),
            },
            "execution": {
                "cancellations_count": len(result["execution"].get("cancellations", [])),
                "placements_count": len([p for p in result["execution"].get("placements", []) if "SKIPPED" not in p.get("result", "")]),
                "skipped_count": len([p for p in result["execution"].get("placements", []) if "SKIPPED" in p.get("result", "")]),
            },
            "daily_pnl": daily_pnl,
        }
        report_path = os.path.join(os.path.dirname(LOG_PATH), "last_cycle_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(last_report, f, indent=2, ensure_ascii=False)
        sys.stderr.write(f"[REPORT] Written to {report_path}\n")
    except Exception as e:
        sys.stderr.write(f"[REPORT] ERROR: {e}\n")

    # Exit with non-zero if stop counter triggered, so caller can halt



if __name__ == "__main__":
    main()
