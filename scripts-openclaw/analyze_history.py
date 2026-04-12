#!/usr/bin/env python3
"""
Analyze recent trading history from OKX bills and auto_trade log/jsonl.
Outputs a JSON report for AI decision support.
"""
import os
import sys
import json
import re
from datetime import datetime, timezone, timedelta

from config import API_KEY, SECRET, PASSPHRASE, BASE_URL, JSONL_PATH, LOG_PATH
import base64, hmac, hashlib, urllib.request


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
        req = urllib.request.Request(BASE_URL + path, headers=headers)
        with opener.open(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        req = urllib.request.Request(BASE_URL + path, headers=headers)
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


def parse_jsonl():
    entries = []
    if not os.path.exists(JSONL_PATH):
        return entries
    with open(JSONL_PATH, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except:
                continue
    return entries


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


def get_log_entries():
    jsonl = parse_jsonl()
    if jsonl:
        return jsonl
    legacy = parse_auto_trade_log()
    return legacy


def dominant_trend_per_day(entries):
    day_trends = {}
    for e in entries:
        d = e.get("timestamp", "")[:10] if "timestamp" in e else e.get("date", "")
        if not d:
            continue
        t = e.get("trend", "unknown").lower()
        if d not in day_trends:
            day_trends[d] = {}
        day_trends[d][t] = day_trends[d].get(t, 0) + 1
    result = {}
    for d, counts in day_trends.items():
        result[d] = max(counts, key=counts.get)
    return result


def imbalance_per_day(entries):
    """Returns day -> max imbalance (abs(long - short)) if available."""
    result = {}
    for e in entries:
        d = e.get("timestamp", "")[:10] if "timestamp" in e else e.get("date", "")
        if not d:
            continue
        # Try structured fields first
        long_o = e.get("long_orders")
        short_o = e.get("short_orders")
        if long_o is not None and short_o is not None:
            result[d] = max(result.get(d, 0), abs(int(long_o) - int(short_o)))
        else:
            # Fallback: try to infer from actions text
            actions = e.get("actions", "")
            m = re.search(r"(\d+)\s*short.*?\s*(\d+)\s*long", actions, re.IGNORECASE)
            if m:
                result[d] = max(result.get(d, 0), abs(int(m.group(1)) - int(m.group(2))))
    return result


def gap_per_day(entries):
    """Returns day -> avg gap if available."""
    result = {}
    counts = {}
    for e in entries:
        d = e.get("timestamp", "")[:10] if "timestamp" in e else e.get("date", "")
        if not d:
            continue
        gap = e.get("gap")
        if gap is not None:
            result[d] = result.get(d, 0.0) + float(gap)
            counts[d] = counts.get(d, 0) + 1
    for d in result:
        result[d] = round(result[d] / counts[d], 1)
    return result


def entry_percentile_per_day(entries):
    """Returns day -> avg price percentile in 24h range if high24h/low24h available."""
    result = {}
    counts = {}
    for e in entries:
        d = e.get("timestamp", "")[:10] if "timestamp" in e else e.get("date", "")
        if not d:
            continue
        price = e.get("price")
        high = e.get("high24h")
        low = e.get("low24h")
        if price is not None and high is not None and low is not None:
            try:
                p, h, l = float(price), float(high), float(low)
                if h > l:
                    pct = (p - l) / (h - l) * 100
                    result[d] = result.get(d, 0.0) + pct
                    counts[d] = counts.get(d, 0) + 1
            except:
                continue
    for d in result:
        result[d] = round(result[d] / counts[d], 1)
    return result


def max_drawdown(daily_pnls):
    """Maximum consecutive/cumulative loss from peak."""
    if not daily_pnls:
        return 0.0
    sorted_days = sorted(daily_pnls.keys())
    peak = 0.0
    max_dd = 0.0
    cumulative = 0.0
    for day in sorted_days:
        cumulative += daily_pnls[day]
        if cumulative > peak:
            peak = cumulative
        dd = cumulative - peak
        if dd < max_dd:
            max_dd = dd
    return round(max_dd, 4)


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
        mdd_7d = max_drawdown(pnl_7d)

        log_entries = get_log_entries()
        day_trend = dominant_trend_per_day(log_entries)
        imbalance = imbalance_per_day(log_entries)
        gap_map = gap_per_day(log_entries)
        percentile_map = entry_percentile_per_day(log_entries)

        # Trend performance
        trend_pnl = {"bullish": {"days": 0, "pnl": 0.0}, "bearish": {"days": 0, "pnl": 0.0}, "sideways": {"days": 0, "pnl": 0.0}, "unknown": {"days": 0, "pnl": 0.0}}
        for day, pnl in pnl_7d.items():
            t = day_trend.get(day, "unknown")
            if t not in trend_pnl:
                t = "unknown"
            trend_pnl[t]["days"] += 1
            trend_pnl[t]["pnl"] += pnl
        for t in trend_pnl:
            trend_pnl[t]["pnl"] = round(trend_pnl[t]["pnl"], 4)

        # Imbalance analysis
        balanced_days = [d for d in pnl_7d if imbalance.get(d, 0) < 2]
        imbalanced_days = [d for d in pnl_7d if imbalance.get(d, 0) >= 3]
        balanced_pnl = round(sum(pnl_7d[d] for d in balanced_days), 4)
        imbalanced_pnl = round(sum(pnl_7d[d] for d in imbalanced_days), 4)

        # Gap performance (if gap data available)
        large_gap_days = [d for d in pnl_7d if gap_map.get(d, 0) >= 14]
        small_gap_days = [d for d in pnl_7d if 0 < gap_map.get(d, 0) <= 10]
        large_gap_pnl = round(sum(pnl_7d[d] for d in large_gap_days), 4)
        small_gap_pnl = round(sum(pnl_7d[d] for d in small_gap_days), 4)

        # Entry timing analysis (if percentile data available)
        low_entry_days = [d for d in pnl_7d if percentile_map.get(d, 50) <= 30]
        high_entry_days = [d for d in pnl_7d if percentile_map.get(d, 50) >= 70]
        low_entry_pnl = round(sum(pnl_7d[d] for d in low_entry_days), 4)
        high_entry_pnl = round(sum(pnl_7d[d] for d in high_entry_days), 4)

        # Recommendation
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

        if mdd_7d < -5:
            recommendation += f" 注意最大回撤达 {mdd_7d} USDT，需收紧风控。"
        if imbalanced_days and imbalanced_pnl < balanced_pnl:
            recommendation += " 单侧严重失衡时表现更差，建议保持两侧均衡。"
        if large_gap_days and large_gap_pnl > small_gap_pnl:
            recommendation += " 大 gap 策略近期更优。"
        elif small_gap_days and small_gap_pnl > large_gap_pnl:
            recommendation += " 小 gap 策略近期更优。"

        result = {
            "total_pnl_7d": total_7d,
            "total_pnl_30d": total_30d,
            "win_days_7d": win_days_7d,
            "loss_days_7d": loss_days_7d,
            "avg_daily_pnl_7d": avg_daily_7d,
            "max_daily_loss_7d": max_loss_7d,
            "max_drawdown_7d": mdd_7d,
            "trend_performance_7d": {k: v for k, v in trend_pnl.items() if k != "unknown"},
            "imbalance_analysis": {
                "balanced_pnl": balanced_pnl,
                "imbalanced_pnl": imbalanced_pnl,
            },
            "gap_performance": {
                "large_gap_pnl": large_gap_pnl,
                "small_gap_pnl": small_gap_pnl,
            },
            "entry_timing": {
                "low_percentile_pnl": low_entry_pnl,
                "high_percentile_pnl": high_entry_pnl,
            },
            "recommendation": recommendation.strip(),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))


if __name__ == "__main__":
    main()
