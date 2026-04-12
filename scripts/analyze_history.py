#!/usr/bin/env python3
"""
Analyze recent trading history from OKX bills and auto_trade.log.
Outputs a JSON report for AI decision support.
"""
import os
import sys
import json
import re
import base64
import hmac
import hashlib
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.environ.get("OKX_BASE_URL", "https://www.okx.com")
LOG_PATH = os.path.expanduser("~/.openclaw/workspace/auto_trade.log")


def _load_env_file():
    env_path = os.path.expanduser("~/.openclaw/workspace/.env.trading")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
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
                    if k not in os.environ:
                        os.environ[k] = v


_load_env_file()
API_KEY = os.environ.get("OKX_API_KEY", "")
SECRET = os.environ.get("OKX_SECRET_KEY", "")
PASSPHRASE = os.environ.get("OKX_PASSPHRASE", "")


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sign(timestamp, method, request_path, body=""):
    if body and isinstance(body, (dict, list)):
        body = json.dumps(body)
    message = timestamp + method.upper() + request_path + (body or "")
    mac = hmac.new(SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def fetch(path):
    if not API_KEY:
        return {"error": "Missing API credentials"}
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
        req = urllib.request.Request(BASE + path, headers=headers)
        with opener.open(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        req = urllib.request.Request(BASE + path, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))


def get_bills_range(begin_ms, end_ms):
    path = f"/api/v5/account/bills?instType=SWAP&instId=ETH-USDT-SWAP&begin={begin_ms}&end={end_ms}&limit=100"
    resp = fetch(path)
    if not isinstance(resp, dict) or resp.get("code") != "0":
        return []
    records = []
    for r in resp.get("data", []):
        sub = int(r.get("subType", -1))
        if sub in {4, 6, 110, 111, 112}:
            records.append(r)
    return records


def parse_auto_trade_log():
    if not os.path.exists(LOG_PATH):
        return {}
    entries = []
    current_entry = None
    with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip()
            m = re.match(r"\[(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\]", line)
            if m:
                if current_entry:
                    entries.append(current_entry)
                current_entry = {"date": m.group(1), "trend": "unknown", "total": "", "actions": ""}
            elif current_entry and line.startswith("- Market Trend:"):
                current_entry["trend"] = line.split(":", 1)[1].strip().lower()
            elif current_entry and line.startswith("- Total Exposure:"):
                current_entry["total"] = line.split(":", 1)[1].strip()
            elif current_entry and line.startswith("- Actions:"):
                current_entry["actions"] = line.split(":", 1)[1].strip()
    if current_entry:
        entries.append(current_entry)
    return entries


def dominant_trend_per_day(entries):
    day_trends = {}
    for e in entries:
        d = e["date"]
        t = e["trend"]
        if d not in day_trends:
            day_trends[d] = {}
        day_trends[d][t] = day_trends[d].get(t, 0) + 1
    result = {}
    for d, counts in day_trends.items():
        result[d] = max(counts, key=counts.get)
    return result


def main():
    try:
        now = datetime.now(timezone.utc)
        begin_7d = int((now - timedelta(days=7)).timestamp() * 1000)
        begin_30d = int((now - timedelta(days=30)).timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)

        records_7d = get_bills_range(begin_7d, end_ms)
        records_30d = get_bills_range(begin_30d, end_ms)

        def daily_pnl(records):
            days = {}
            for r in records:
                ts = int(r.get("ts", 0))
                day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                pnl = float(r.get("pnl", "0") or "0")
                days[day] = days.get(day, 0.0) + pnl
            return days

        pnl_7d = daily_pnl(records_7d)
        pnl_30d = daily_pnl(records_30d)

        total_7d = round(sum(pnl_7d.values()), 4)
        total_30d = round(sum(pnl_30d.values()), 4)
        win_days_7d = sum(1 for v in pnl_7d.values() if v > 0)
        loss_days_7d = sum(1 for v in pnl_7d.values() if v < 0)
        avg_daily_7d = round(total_7d / max(len(pnl_7d), 1), 4)
        max_loss_7d = round(min(pnl_7d.values()) if pnl_7d else 0, 4)

        log_entries = parse_auto_trade_log()
        day_trend = dominant_trend_per_day(log_entries)

        trend_pnl = {"bullish": {"days": 0, "pnl": 0.0}, "bearish": {"days": 0, "pnl": 0.0}, "sideways": {"days": 0, "pnl": 0.0}, "unknown": {"days": 0, "pnl": 0.0}}
        for day, pnl in pnl_7d.items():
            t = day_trend.get(day, "unknown")
            if t not in trend_pnl:
                t = "unknown"
            trend_pnl[t]["days"] += 1
            trend_pnl[t]["pnl"] += pnl

        for t in trend_pnl:
            trend_pnl[t]["pnl"] = round(trend_pnl[t]["pnl"], 4)

        # Simple recommendation
        recommendation = ""
        best_trend = max((k for k in trend_pnl if k != "unknown"), key=lambda x: trend_pnl[x]["pnl"], default="")
        worst_trend = min((k for k in trend_pnl if k != "unknown"), key=lambda x: trend_pnl[x]["pnl"], default="")
        if total_7d < -20:
            recommendation = f"最近 7 天整体亏损 ({total_7d} USDT)，建议降低仓位或加大 gap。"
        elif total_7d > 20:
            recommendation = f"最近 7 天整体盈利 ({total_7d} USDT)，可维持当前策略。"
        else:
            recommendation = f"最近 7 天盈亏平缓 ({total_7d} USDT)，维持现有策略并关注异常。"

        if best_trend and worst_trend and best_trend != worst_trend:
            recommendation += f" {best_trend} 行情下表现最好 ({trend_pnl[best_trend]['pnl']} USDT)，{worst_trend} 下表现最差 ({trend_pnl[worst_trend]['pnl']} USDT)。"

        result = {
            "total_pnl_7d": total_7d,
            "total_pnl_30d": total_30d,
            "win_days_7d": win_days_7d,
            "loss_days_7d": loss_days_7d,
            "avg_daily_pnl_7d": avg_daily_7d,
            "max_daily_loss_7d": max_loss_7d,
            "trend_performance_7d": {k: v for k, v in trend_pnl.items() if k != "unknown"},
            "recommendation": recommendation.strip(),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))


if __name__ == "__main__":
    main()
