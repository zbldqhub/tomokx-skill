#!/usr/bin/env python3
"""
Update stop-loss counter for openclaw (Linux).
Counts today's losing closes from bills and writes to .trading_stopped.
"""
import os
import sys
import json
import subprocess
from datetime import datetime, timezone

from config import WORKSPACE, STOP_FILE


def run_bills():
    env = os.environ.copy()
    env_path = os.path.join(WORKSPACE, ".env.trading")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    env[k] = v
    cmd = [sys.executable, os.path.join(WORKSPACE, "scripts", "get_bills.py"), "--today"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    if r.returncode != 0:
        return {"error": r.stderr or "get_bills failed"}
    return json.loads(r.stdout)


def count_losing_closes(bills_data):
    count = 0
    if isinstance(bills_data, dict) and bills_data.get("code") == "0":
        for r in bills_data.get("data", []):
            if r.get("instId") != "ETH-USDT-SWAP":
                continue
            sub = int(r.get("subType", -1))
            if sub in {4, 6, 110, 111, 112}:
                pnl = float(r.get("pnl", "0") or "0")
                if pnl < 0:
                    count += 1
    return count


def read_current():
    if not os.path.exists(STOP_FILE):
        return 0
    # Reset if file was not modified today
    mtime = datetime.fromtimestamp(os.path.getmtime(STOP_FILE), tz=timezone.utc)
    today = datetime.now(timezone.utc).date()
    if mtime.date() != today:
        return 0
    try:
        with open(STOP_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except:
        return 0


def write_counter(value):
    with open(STOP_FILE, "w", encoding="utf-8") as f:
        f.write(str(value))


def main():
    bills = run_bills()
    if "error" in bills:
        print(json.dumps({"error": bills["error"]}))
        sys.exit(1)

    losing = count_losing_closes(bills)
    current = read_current()
    new_value = max(current, losing)
    write_counter(new_value)

    print(json.dumps({
        "previous": current,
        "losing_closes_today": losing,
        "written": new_value,
        "should_stop": new_value >= 3,
    }, indent=2))


if __name__ == "__main__":
    main()
