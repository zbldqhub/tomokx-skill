#!/usr/bin/env python3
"""
Virtual PnL attribution for AI-deleted orders.
Reads decisions.jsonl, pulls 5m candles, and simulates what would have happened
if the deleted orders had actually been placed.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DECISION_LOG_PATH, API_KEY, SECRET, PASSPHRASE, BASE_URL
import base64, hmac, hashlib
import urllib.request


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


def fetch_candles(bar="5m", limit=288):
    path = f"/api/v5/market/candles?instId=ETH-USDT-SWAP&bar={bar}&limit={limit}"
    try:
        return fetch_okx(path)
    except Exception as e:
        return {"error": str(e)}


def parse_candles(data):
    if not isinstance(data, dict) or data.get("code") != "0":
        return []
    rows = []
    for r in data.get("data", []):
        # OKX candle format: [ts, o, h, l, c, vol, volCcy]
        rows.append({
            "ts": int(r[0]),
            "o": float(r[1]),
            "h": float(r[2]),
            "l": float(r[3]),
            "c": float(r[4]),
        })
    rows.sort(key=lambda x: x["ts"])
    return rows


def load_today_decisions():
    if not os.path.exists(DECISION_LOG_PATH):
        return []
    entries = []
    today = datetime.now(timezone.utc).date()
    with open(DECISION_LOG_PATH, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp", "")
                if ts:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.date() == today:
                        entries.append(entry)
            except Exception:
                continue
    return entries


def simulate_order(px, tp, sl, pos_side, candles):
    """Simulate lifecycle of a limit order on 5m candles."""
    entered = False
    entry_ts = None
    for i, c in enumerate(candles):
        if not entered:
            # Limit fill check: price touches or crosses px within the bar
            if pos_side == "long":
                if c["l"] <= px <= c["h"]:
                    entered = True
                    entry_ts = c["ts"]
            else:  # short
                if c["l"] <= px <= c["h"]:
                    entered = True
                    entry_ts = c["ts"]
            continue

        # After entry, check TP/SL on subsequent bars
        if pos_side == "long":
            if c["h"] >= tp:
                return {"status": "closed_by_tp", "pnl": round(tp - px, 4), "hold_bars": i}
            if c["l"] <= sl:
                return {"status": "closed_by_sl", "pnl": round(sl - px, 4), "hold_bars": i}
        else:
            if c["l"] <= tp:
                return {"status": "closed_by_tp", "pnl": round(px - tp, 4), "hold_bars": i}
            if c["h"] >= sl:
                return {"status": "closed_by_sl", "pnl": round(px - sl, 4), "hold_bars": i}

    if entered:
        # Still open: mark-to-market on last close
        last_c = candles[-1]["c"]
        if pos_side == "long":
            unrealized = round(last_c - px, 4)
        else:
            unrealized = round(px - last_c, 4)
        return {"status": "open", "pnl": unrealized, "hold_bars": len(candles)}

    return {"status": "unfilled", "pnl": 0.0, "hold_bars": 0}


def main():
    decisions = load_today_decisions()
    if not decisions:
        print(json.dumps({"error": "No decisions found for today"}, indent=2))
        sys.exit(0)

    candles = parse_candles(fetch_candles(bar="5m", limit=288))
    if not candles:
        print(json.dumps({"error": "Failed to fetch candles"}, indent=2))
        sys.exit(1)

    results = []
    total_virtual_pnl = 0.0
    for dec in decisions:
        deleted = dec.get("ai_review", {}).get("deleted_placements", [])
        for d in deleted:
            px = float(d.get("px", 0))
            tp = float(d.get("tpTriggerPx", 0))
            sl = float(d.get("slTriggerPx", 0))
            pos_side = d.get("posSide", "")
            if not px or not tp or not sl or not pos_side:
                continue

            sim = simulate_order(px, tp, sl, pos_side, candles)
            total_virtual_pnl += sim["pnl"]
            results.append({
                "decision_id": dec.get("decision_id"),
                "timestamp": dec.get("timestamp"),
                "posSide": pos_side,
                "px": px,
                "tp": tp,
                "sl": sl,
                **sim,
            })

    report = {
        "generated_at": iso_now(),
        "candle_bar": "5m",
        "deleted_orders_today": len(results),
        "total_virtual_pnl": round(total_virtual_pnl, 4),
        "details": results,
    }

    report_path = os.path.join(os.path.dirname(DECISION_LOG_PATH), "virtual_pnl_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[REPORT] Saved to {report_path}")


if __name__ == "__main__":
    main()
