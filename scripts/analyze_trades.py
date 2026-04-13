#!/usr/bin/env python3
"""Analyze order_tracking.jsonl against OKX bills to evaluate per-order lifecycle performance."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ORDER_TRACKING_PATH, API_KEY, SECRET, PASSPHRASE, BASE_URL, ensure_api_ready
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


def fetch_bills(begin_ms, end_ms, limit=100):
    ensure_api_ready()
    path = f"/api/v5/account/bills?instType=SWAP&instId=ETH-USDT-SWAP&begin={begin_ms}&end={end_ms}&limit={limit}"
    try:
        return fetch_okx(path)
    except Exception as e:
        return {"error": str(e)}


def load_tracking(path):
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def match_trades(tracking_entries, bills_data):
    if not isinstance(bills_data, dict) or bills_data.get("code") != "0":
        return {}, bills_data.get("error", "invalid bills")

    records = bills_data.get("data", [])
    ord_map = {}
    for r in records:
        oid = r.get("ordId")
        if not oid:
            continue
        ord_map.setdefault(oid, []).append(r)

    results = []
    for t in tracking_entries:
        oid = t.get("ordId", "")
        recs = ord_map.get(oid, [])
        if not recs:
            results.append({
                **t,
                "status": "open_or_unfilled",
                "total_pnl": None,
                "hold_time_hours": None,
            })
            continue

        recs.sort(key=lambda x: int(x.get("cTime", 0)))
        total_pnl = 0.0
        total_fee = 0.0
        for r in recs:
            try:
                total_pnl += float(r.get("pnl", "0") or "0")
                total_fee += float(r.get("fee", "0") or "0")
            except (ValueError, TypeError):
                continue

        first_ms = int(recs[0].get("cTime", 0))
        last_ms = int(recs[-1].get("cTime", 0))
        hold_hours = round((last_ms - first_ms) / 3600000, 2) if last_ms > first_ms else 0.0

        results.append({
            **t,
            "status": "closed",
            "total_pnl": round(total_pnl, 4),
            "total_fee": round(total_fee, 4),
            "hold_time_hours": hold_hours,
            "bill_count": len(recs),
        })

    return results, None


def analyze(results, min_samples=3):
    groups = {}
    for r in results:
        if r.get("status") != "closed":
            continue
        key = (
            r.get("market_trend", "unknown"),
            str(r.get("gap", "")),
            r.get("expansion_type", ""),
            r.get("posSide", ""),
        )
        if key not in groups:
            groups[key] = []
        groups[key].append(float(r["total_pnl"]))

    stats = []
    for key, pnls in groups.items():
        if len(pnls) < min_samples:
            continue
        avg = round(sum(pnls) / len(pnls), 4)
        win_rate = round(sum(1 for p in pnls if p > 0) / len(pnls), 2)
        stats.append({
            "trend": key[0],
            "gap": key[1],
            "expansion_type": key[2],
            "posSide": key[3],
            "count": len(pnls),
            "avg_pnl": avg,
            "win_rate": win_rate,
        })

    stats.sort(key=lambda x: x["avg_pnl"], reverse=True)
    return stats


def main():
    ensure_api_ready()
    tracking = load_tracking(ORDER_TRACKING_PATH)
    if not tracking:
        print(json.dumps({"error": "No tracking entries found"}, indent=2))
        sys.exit(0)

    # Fetch last 7 days of bills
    end = datetime.now(timezone.utc)
    begin = end - timedelta(days=7)
    bills = fetch_bills(int(begin.timestamp() * 1000), int(end.timestamp() * 1000), limit=100)

    if "error" in bills:
        print(json.dumps({"error": bills["error"]}, indent=2))
        sys.exit(1)

    matched, err = match_trades(tracking, bills)
    if err:
        print(json.dumps({"error": err}, indent=2))
        sys.exit(1)

    closed_count = sum(1 for m in matched if m["status"] == "closed")
    open_count = len(matched) - closed_count

    stats = analyze(matched, min_samples=3)

    result = {
        "tracking_total": len(matched),
        "closed_count": closed_count,
        "open_or_unfilled_count": open_count,
        "top_setups": stats[:5],
        "bottom_setups": stats[-5:],
        "recommendations": [],
    }

    if stats:
        best = stats[0]
        result["recommendations"].append(
            f"Best setup: {best['posSide']} {best['expansion_type']} in {best['trend']} with gap={best['gap']} -> avg_pnl={best['avg_pnl']} win_rate={best['win_rate']} (n={best['count']})"
        )
    if stats and stats[-1]["avg_pnl"] < 0:
        worst = stats[-1]
        result["recommendations"].append(
            f"Worst setup: {worst['posSide']} {worst['expansion_type']} in {worst['trend']} with gap={worst['gap']} -> avg_pnl={worst['avg_pnl']} win_rate={worst['win_rate']} (n={worst['count']}); consider avoiding"
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
