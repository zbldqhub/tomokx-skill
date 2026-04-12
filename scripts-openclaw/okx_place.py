#!/usr/bin/env python3
"""Place OKX SWAP limit order with TP/SL."""
import os, sys, json, base64, hmac, hashlib, urllib.request

API_KEY = os.environ.get("OKX_API_KEY", "")
SECRET = os.environ.get("OKX_SECRET_KEY", "")
PASSPHRASE = os.environ.get("OKX_PASSPHRASE", "")
BASE = os.environ.get("OKX_BASE_URL", "https://www.okx.com")


def iso_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sign(timestamp, method, request_path, body=""):
    if body and isinstance(body, (dict, list)):
        body = json.dumps(body)
    message = timestamp + method.upper() + request_path + (body or "")
    mac = hmac.new(SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def proxy_req(method, path, body=None):
    import urllib.request
    timestamp = iso_now()
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign(timestamp, method, path, body),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
    }
    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    data = (json.dumps(body) if body else None)
    req = urllib.request.Request(BASE + path, data=data.encode("utf-8") if data else None, headers=headers, method=method)
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))


def cancel(instId, ordId):
    return proxy_req("POST", "/api/v5/trade/cancel-order", {"instId": instId, "ordId": ordId})


def place(instId, tdMode, side, ordType, sz, px, posSide, tpTriggerPx, slTriggerPx):
    body = {
        "instId": instId,
        "tdMode": tdMode,
        "side": side,
        "ordType": ordType,
        "sz": str(sz),
        "px": str(px),
        "posSide": posSide,
        "attachAlgoOrds": [
            {"attachAlgoId": "", "tpTriggerPx": str(tpTriggerPx), "tpOrdPx": "-1", "slTriggerPx": str(slTriggerPx), "slOrdPx": "-1"}
        ]
    }
    return proxy_req("POST", "/api/v5/trade/order", body)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "cancel":
        print(json.dumps(cancel(sys.argv[2], sys.argv[3])))
    elif cmd == "place":
        # place instId tdMode side ordType sz px posSide tpTriggerPx slTriggerPx
        print(json.dumps(place(*sys.argv[2:11])))
    else:
        print("unknown cmd")
