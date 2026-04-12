#!/usr/bin/env python3
"""
Batch order executor for Windows tomokx skill.
Reads a JSON plan and executes cancels/placements via OKX CLI.
"""
import subprocess
import os
import sys
import json

WORKSPACE = os.path.expanduser(r"~\.openclaw\workspace")
ENV_FILE = os.path.join(WORKSPACE, ".env.trading")


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
    r = subprocess.run(cmd_list, env=env, capture_output=True, text=True, timeout=20)
    return r.stdout or r.stderr or ""


def cancel_order(inst_id, ord_id, env):
    out = run_cmd([
        "okx", "swap", "cancel",
        "--instId", inst_id,
        "--ordId", ord_id,
    ], env)
    return out.strip()


def place_order(inst_id, td_mode, side, ord_type, sz, px, pos_side, tp, sl, env):
    out = run_cmd([
        "okx", "swap", "place",
        "--instId", inst_id,
        "--tdMode", td_mode,
        "--side", side,
        "--ordType", ord_type,
        "--sz", str(sz),
        f"--px={px}",
        "--posSide", pos_side,
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
        print("Usage: python execute_orders.py <plan.json>")
        print('Plan format: {"cancellations": [...], "placements": [...]}')
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

    print("\n" + json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
