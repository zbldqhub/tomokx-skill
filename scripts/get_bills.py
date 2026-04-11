#!/usr/bin/env python3
"""
OKX Account Bills fetcher via REST API.
Replaces 'okx account bills' CLI which lacks --begin/--type in v1.3.0.
"""
import os
import sys
import json
import time
import base64
import hmac
import hashlib
from urllib import request, error

ENV_FILE = os.path.expanduser("~/.openclaw/workspace/.env.trading")
PROXY_URL = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or ""


def load_env():
    env = {}
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
                env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def sign(message, secret):
    mac = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def fetch_bills(inst_type="SWAP", begin_ms="", end_ms="", limit="100"):
    env = load_env()
    api_key = env.get("OKX_API_KEY", "")
    secret = env.get("OKX_SECRET_KEY", "")
    passphrase = env.get("OKX_PASSPHRASE", "")
    if not api_key or not secret or not passphrase:
        print(json.dumps({"error": "Missing OKX_API_KEY, OKX_SECRET_KEY or OKX_PASSPHRASE"}))
        sys.exit(1)

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    base_url = "https://www.okx.com"
    path = f"/api/v5/account/bills?instType={inst_type}&limit={limit}"
    if begin_ms:
        path += f"&begin={begin_ms}"
    if end_ms:
        path += f"&end={end_ms}"

    message = timestamp + "GET" + path
    signature = sign(message, secret)

    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }

    req = request.Request(base_url + path, headers=headers, method="GET")
    handlers = []
    if PROXY_URL:
        handlers.append(request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL}))
    opener = request.build_opener(*handlers)

    try:
        with opener.open(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(json.dumps(data, indent=2))
    except error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(json.dumps({"error": "HTTPError", "code": e.code, "body": body}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch OKX account bills via REST API")
    parser.add_argument("--instType", default="SWAP")
    parser.add_argument("--today", action="store_true", help="Filter from today 00:00 UTC")
    parser.add_argument("--limit", default="100")
    args = parser.parse_args()

    begin_ms = ""
    end_ms = ""
    if args.today:
        now = time.time()
        today_start = int(now - (now % 86400))
        begin_ms = str(today_start * 1000)

    fetch_bills(args.instType, begin_ms, end_ms, args.limit)


if __name__ == "__main__":
    main()
