#!/usr/bin/env python3
"""
Unified notification sender for tomokx trading system.
Supports QQ (via HTTP API) and generic webhook.
Reads notification config from ~/.openclaw/workspace/.env.trading
"""
import os
import sys
import json
import urllib.request

from config import ENV_FILE


def load_notify_config():
    config = {}
    if not os.path.exists(ENV_FILE):
        return config
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k.startswith("NOTIFY_"):
                    config[k] = v
    return config


def send_qq(msg, qq_api_url):
    try:
        payload = json.dumps({"message": msg}).encode("utf-8")
        req = urllib.request.Request(
            qq_api_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "status": resp.status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_webhook(msg, webhook_url):
    try:
        payload = json.dumps({"text": msg}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "status": resp.status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not msg:
        print(json.dumps({"error": "Usage: python3 notify.py <message>"}))
        sys.exit(1)

    config = load_notify_config()
    results = []

    qq_url = config.get("NOTIFY_QQ_API_URL", "")
    webhook_url = config.get("NOTIFY_WEBHOOK_URL", "")

    if qq_url:
        results.append(send_qq(msg, qq_url))
    if webhook_url:
        results.append(send_webhook(msg, webhook_url))

    if not results:
        print(json.dumps({"warning": "No notification channel configured. Set NOTIFY_QQ_API_URL or NOTIFY_WEBHOOK_URL in .env.trading"}))
        return

    print(json.dumps({"results": results}))


if __name__ == "__main__":
    main()
