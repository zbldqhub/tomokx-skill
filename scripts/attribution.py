#!/usr/bin/env python3
"""
AI Review Attribution Engine for tomokx.
Evaluates the real-world performance of AI-kept orders vs deleted orders
by matching order_tracking.jsonl and decisions.jsonl against OKX bills.
Generates a weekly report with accuracy stats and tuning recommendations.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ORDER_TRACKING_PATH, DECISION_LOG_PATH, API_KEY, SECRET, PASSPHRASE, BASE_URL, ensure_api_ready
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


def load_jsonl(path):
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def match_bills(bills_data):
    """Return dict ordId -> list of bill records."""
    if not isinstance(bills_data, dict) or bills_data.get("code") != "0":
        return {}
    ord_map = {}
    for r in bills_data.get("data", []):
        oid = r.get("ordId")
        if not oid:
            continue
        ord_map.setdefault(oid, []).append(r)
    return ord_map


def calc_ord_pnl(ord_map, oid):
    recs = ord_map.get(oid, [])
    if not recs:
        return None, 0
    total_pnl = 0.0
    total_fee = 0.0
    for r in recs:
        try:
            total_pnl += float(r.get("pnl", "0") or "0")
            total_fee += float(r.get("fee", "0") or "0")
        except (ValueError, TypeError):
            continue
    return round(total_pnl, 4), round(total_fee, 4)


def parse_dt(ts_str):
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def analyze_attribution(tracking_entries, decision_entries, ord_map):
    """Core attribution logic."""
    # Build tracking lookup by ordId
    tracking_by_oid = {}
    for t in tracking_entries:
        oid = t.get("ordId", "")
        if oid:
            tracking_by_oid[oid] = t

    # Aggregate by decision
    kept_results = []  # list of dicts for kept orders
    deleted_summary = []  # list of dicts for deleted orders
    rule_counts = {}  # reason -> count

    for dec in decision_entries:
        dec_id = dec.get("decision_id")
        ai_review = dec.get("ai_review", {})
        deleted = ai_review.get("deleted_placements", [])
        kept_prices = set(dec.get("actual_actions", {}).get("long_prices", []) + dec.get("actual_actions", {}).get("short_prices", []))

        # Process kept orders via tracking
        for t in tracking_entries:
            if t.get("decision_id") != dec_id:
                continue
            oid = t.get("ordId", "")
            pnl, fee = calc_ord_pnl(ord_map, oid)
            kept_results.append({
                "decision_id": dec_id,
                "timestamp": dec.get("timestamp"),
                "ordId": oid,
                "px": t.get("px"),
                "posSide": t.get("posSide"),
                "expansion_type": t.get("expansion_type", ""),
                "market_trend": t.get("market_trend", ""),
                "pnl": pnl,
                "fee": fee,
                "status": "closed" if pnl is not None else "open_or_unfilled",
            })

        # Process deleted orders (opportunity cost proxy)
        for d in deleted:
            deleted_summary.append({
                "decision_id": dec_id,
                "timestamp": dec.get("timestamp"),
                "px": d.get("px"),
                "posSide": d.get("posSide"),
                "market_trend": dec.get("market_state", {}).get("trend", ""),
            })
            # Extract primary deletion reason from ai_actions
            for action in ai_review.get("ai_actions", []):
                if "Deleted" in action and d.get("px") in str(action):
                    reason = action.split(":")[-1].strip() if ":" in action else action
                    rule_counts[reason] = rule_counts.get(reason, 0) + 1

    # Statistics
    closed_kept = [k for k in kept_results if k["status"] == "closed"]
    total_kept_closed_pnl = sum(k["pnl"] for k in closed_kept) if closed_kept else 0.0
    avg_kept_pnl = round(total_kept_closed_pnl / len(closed_kept), 4) if closed_kept else 0.0
    win_rate = round(sum(1 for k in closed_kept if k["pnl"] > 0) / len(closed_kept), 2) if closed_kept else 0.0

    # Group by expansion_type + trend
    setup_stats = {}
    for k in closed_kept:
        key = (k.get("market_trend", "unknown"), k.get("expansion_type", "unknown"), k.get("posSide", "unknown"))
        setup_stats.setdefault(key, []).append(k["pnl"])

    setup_report = []
    for key, pnls in setup_stats.items():
        if len(pnls) < 2:
            continue
        avg = round(sum(pnls) / len(pnls), 4)
        wr = round(sum(1 for p in pnls if p > 0) / len(pnls), 2)
        setup_report.append({
            "trend": key[0],
            "expansion_type": key[1],
            "posSide": key[2],
            "count": len(pnls),
            "avg_pnl": avg,
            "win_rate": wr,
        })
    setup_report.sort(key=lambda x: x["avg_pnl"], reverse=True)

    # Top deletion reasons
    top_deletions = sorted(rule_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # Recommendations
    recommendations = []
    if setup_report:
        best = setup_report[0]
        recommendations.append(
            f"Best setup: {best['posSide']} {best['expansion_type']} in {best['trend']} -> avg_pnl={best['avg_pnl']} win_rate={best['win_rate']} (n={best['count']})"
        )
        worst = setup_report[-1]
        if worst["avg_pnl"] < 0:
            recommendations.append(
                f"Worst setup: {worst['posSide']} {best['expansion_type']} in {worst['trend']} -> avg_pnl={worst['avg_pnl']} win_rate={worst['win_rate']} (n={worst['count']}); consider blocking"
            )

    if win_rate < 0.4 and len(closed_kept) >= 5:
        recommendations.append(f"Low win rate ({win_rate}) on kept orders; rules may be too lenient or sizing too large.")
    elif win_rate > 0.7 and len(closed_kept) >= 5:
        recommendations.append(f"High win rate ({win_rate}) on kept orders; current AI rules are well calibrated.")

    if top_deletions:
        recommendations.append(f"Top deletion reason: '{top_deletions[0][0]}' ({top_deletions[0][1]} times). Review if this rule is too aggressive.")

    report = {
        "generated_at": iso_now(),
        "period_days": 7,
        "summary": {
            "total_decisions": len(decision_entries),
            "kept_orders_closed": len(closed_kept),
            "kept_orders_open": len([k for k in kept_results if k["status"] != "closed"]),
            "deleted_orders": len(deleted_summary),
            "total_kept_pnl": round(total_kept_closed_pnl, 4),
            "avg_kept_pnl": avg_kept_pnl,
            "win_rate": win_rate,
        },
        "top_setups": setup_report[:5],
        "bottom_setups": setup_report[-5:] if len(setup_report) >= 5 else [],
        "top_deletion_reasons": [{"reason": r, "count": c} for r, c in top_deletions],
        "recommendations": recommendations,
    }
    return report


def main():
    ensure_api_ready()
    tracking = load_jsonl(ORDER_TRACKING_PATH)
    decisions = load_jsonl(DECISION_LOG_PATH)

    if not decisions:
        print(json.dumps({"error": "No decisions found"}, indent=2, ensure_ascii=False))
        sys.exit(0)

    end = datetime.now(timezone.utc)
    begin = end - timedelta(days=7)
    bills = fetch_bills(int(begin.timestamp() * 1000), int(end.timestamp() * 1000), limit=100)

    if "error" in bills:
        print(json.dumps({"error": bills["error"]}, indent=2, ensure_ascii=False))
        sys.exit(1)

    ord_map = match_bills(bills)
    report = analyze_attribution(tracking, decisions, ord_map)

    # Write weekly report
    report_path = os.path.join(os.path.expanduser("~/.openclaw/workspace"), "ai_attribution_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[REPORT] Saved to {report_path}")


if __name__ == "__main__":
    main()
