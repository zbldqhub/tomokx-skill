#!/usr/bin/env python3
"""Simple helper to fetch OKX bills for today."""
import sys
import json
import urllib.request
from datetime import datetime, timezone, timedelta

from config import API_KEY, SECRET, PASSPHRASE, BASE_URL, ensure_api_ready
import base64, hmac, hashlib


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sign(timestamp, method, request_path, body=""):
    if body and isinstance(body, (dict, list)):
        body = json.dumps(body)
    message = timestamp + method.upper() + request_path + (body or "")
    mac = hmac.new(SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def fetch(path):
    timestamp = iso_now()
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign(timestamp, "GET", path),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
    }
    import os
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


def main():
    ensure_api_ready()
    today = datetime.now(timezone.utc).date()
    begin = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = begin + timedelta(days=1)
    begin_ms = int(begin.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    path = f"/api/v5/account/bills?instType=SWAP&instId=ETH-USDT-SWAP&begin={begin_ms}&end={end_ms}&limit=100"
    try:
        data = fetch(path)
        print(json.dumps(data))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()
