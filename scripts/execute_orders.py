#!/usr/bin/env python3
"""
Batch order executor for openclaw (Linux).
Reads a JSON plan and executes cancels/placements via OKX CLI.
"""
import subprocess
import os
import sys
import json
import time

from config import ENV_FILE


def load_env():
    env = os.environ.copy()
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    env[k] = v
    return env


def run_cmd(cmd_list, env):
    cmd_str = " ".join(cmd_list)
    if sys.platform == "win32":
        r = subprocess.run(cmd_str, env=env, capture_output=True, text=True, timeout=20, shell=True, encoding="utf-8", errors="replace")
    else:
        full = f"source {ENV_FILE} && " + cmd_str
        r = subprocess.run(["bash", "-c", full], env=env, capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace")
    return r.stdout or r.stderr or ""


def cancel_order(inst_id, ord_id, env):
    out = run_cmd([
        "okx", "swap", "cancel",
        f"--instId {inst_id}",
        f"--ordId {ord_id}",
    ], env)
    return out.strip()


def place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env):
    out = run_cmd([
        "okx", "swap", "place",
        f"--instId {inst_id}",
        f"--tdMode {td_mode}",
        f"--side {side}",
        f"--ordType {ord_type}",
        f"--sz {sz}",
        f"--px={px}",
        f"--posSide {pos_side}",
        f"--tpTriggerPx={tp}",
        "--tpOrdPx=-1",
        f"--slTriggerPx={sl}",
        "--slOrdPx=-1",
    ], env)
    return out.strip()


def main():
    env = load_env()
    plan_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not plan_path or not os.path.exists(plan_path):
        print("Usage: python3 execute_orders.py <plan.json>")
        print("Plan format: {\"cancellations\": [...], \"placements\": [...]}")
        sys.exit(1)

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    results = {"cancellations": [], "placements": []}

    for item in plan.get("cancellations", []):
        inst_id = item.get("instId", "ETH-USDT-SWAP")
        ord_id = item["ordId"]
        out = cancel_order(inst_id, ord_id, env)
        results["cancellations"].append({"ordId": ord_id, "result": out})
        print(f"[CANCEL] {ord_id} -> {out}")

    for item in plan.get("placements", []):
        inst_id = item.get("instId", "ETH-USDT-SWAP")
        td_mode = item.get("tdMode", "isolated")
        side = item["side"]
        ord_type = item.get("ordType", "limit")
        sz = item["sz"]
        px = item["px"]
        pos_side = item["posSide"]
        tp = item["tpTriggerPx"]
        sl = item["slTriggerPx"]
        out = place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env)
        results["placements"].append({"px": px, "side": side, "posSide": pos_side, "result": out})
        print(f"[PLACE] {side}+{pos_side} @ {px} TP={tp} SL={sl} -> {out}")
        if "429" in out or "rate limit" in out.lower():
            print("[WARN] Rate limit detected, waiting 10s...")
            time.sleep(10)
            out = place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env)
            results["placements"][-1]["retry_result"] = out
            print(f"[RETRY] {side}+{pos_side} @ {px} -> {out}")

    print("\n" + json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
