#!/usr/bin/env python3
"""
Standalone bills fetcher for backward compatibility.
Outputs daily ETH-USDT-SWAP bills and realized PnL.
"""
import json
import os
import sys
import urllib.request
import base64
import hmac
import hashlib
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import API_KEY, SECRET, PASSPHRASE, BASE_URL, DAILY_LOSS_LIMIT, ensure_api_ready


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


def calc_daily_pnl(bills_data):
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


def main():
    bills = run_bills()
    daily_pnl = calc_daily_pnl(bills)
    should_stop = False
    if daily_pnl is not None and daily_pnl < DAILY_LOSS_LIMIT:
        should_stop = True

    result = {
        "daily_pnl": daily_pnl,
        "daily_loss_limit": DAILY_LOSS_LIMIT,
        "should_stop": should_stop,
        "bills_code": bills.get("code") if isinstance(bills, dict) else None,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
