#!/usr/bin/env python3
"""
Trailing / breakeven stop manager for tomokx.
Checks live positions and their attached TP/SL algo orders.
If unrealized profit >= 50% of TP distance, move SL to breakeven + 1 (or -1 for shorts).
Uses direct OKX REST API calls.
"""
import json
import os
import sys
import urllib.request
import base64
import hmac
import hashlib
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import API_KEY, SECRET, PASSPHRASE, BASE_URL, ensure_api_ready


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sign(timestamp, method, request_path, body=""):
    if body and isinstance(body, (dict, list)):
        body = json.dumps(body)
    message = timestamp + method.upper() + request_path + (body or "")
    mac = hmac.new(SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def _request(method, path, body=None):
    timestamp = iso_now()
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign(timestamp, method, path, body),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    data = json.dumps(body).encode("utf-8") if body else None
    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))


def get_positions():
    resp = _request("GET", "/api/v5/account/positions?instType=SWAP&instId=ETH-USDT-SWAP")
    if resp.get("code") == "0":
        return resp.get("data", [])
    return []


def get_algo_orders(ord_type="conditional"):
    resp = _request(
        "GET",
        f"/api/v5/trade/orders-algo-pending?instType=SWAP&instId=ETH-USDT-SWAP&ordType={ord_type}",
    )
    if resp.get("code") == "0":
        return resp.get("data", [])
    return []


def amend_algo_sl(algo_id, new_sl):
    body = {
        "instId": "ETH-USDT-SWAP",
        "algoId": algo_id,
        "newSlTriggerPx": str(new_sl),
        "newSlOrdPx": "-1",
    }
    return _request("POST", "/api/v5/trade/amend-algo-order", body)


def main():
    ensure_api_ready()
    positions = get_positions()
    algo_orders = get_algo_orders("conditional")
    if not algo_orders:
        # Fallback: try oco type
        algo_orders = get_algo_orders("oco")

    # Map algo orders by posSide for quick lookup
    algo_by_pos = {}
    for ao in algo_orders:
        ps = ao.get("posSide")
        if ps:
            algo_by_pos.setdefault(ps, []).append(ao)

    updates = []
    for pos in positions:
        if pos.get("instId") != "ETH-USDT-SWAP":
            continue
        avg_px = float(pos.get("avgPx", 0) or 0)
        pos_side = pos.get("posSide")
        sz = float(pos.get("pos", "0") or "0")
        if sz == 0 or avg_px == 0:
            continue

        mark_px = float(pos.get("markPx", avg_px) or avg_px)
        algos = algo_by_pos.get(pos_side, [])
        live_algos = [a for a in algos if a.get("state") == "live"]
        if not live_algos:
            continue

        target_algo = None
        for a in live_algos:
            if a.get("slTriggerPx"):
                target_algo = a
                break
        if not target_algo:
            continue

        sl_px = float(target_algo.get("slTriggerPx", 0) or 0)
        tp_px = float(target_algo.get("tpTriggerPx", 0) or 0)
        if tp_px == 0:
            continue

        if pos_side == "long":
            tp_distance = tp_px - avg_px
            current_profit_dist = mark_px - avg_px
            breakeven_sl = avg_px + 1
            if current_profit_dist >= tp_distance * 0.5 and sl_px < breakeven_sl:
                res = amend_algo_sl(target_algo["algoId"], round(breakeven_sl, 2))
                updates.append({
                    "posSide": "long",
                    "algoId": target_algo["algoId"],
                    "avgPx": avg_px,
                    "markPx": mark_px,
                    "old_sl": sl_px,
                    "new_sl": breakeven_sl,
                    "result": res,
                })
        elif pos_side == "short":
            tp_distance = avg_px - tp_px
            current_profit_dist = avg_px - mark_px
            breakeven_sl = avg_px - 1
            if current_profit_dist >= tp_distance * 0.5 and sl_px > breakeven_sl:
                res = amend_algo_sl(target_algo["algoId"], round(breakeven_sl, 2))
                updates.append({
                    "posSide": "short",
                    "algoId": target_algo["algoId"],
                    "avgPx": avg_px,
                    "markPx": mark_px,
                    "old_sl": sl_px,
                    "new_sl": breakeven_sl,
                    "result": res,
                })

    print(json.dumps({"updated": len(updates), "details": updates}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
