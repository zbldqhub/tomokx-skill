#!/usr/bin/env python3
"""Run one full trading cycle and print human-readable report."""
import json
import os
import subprocess
import sys
import tempfile
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
SCRIPTS = os.path.join(WORKSPACE, "scripts")


def run(cmd, *args):
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, cmd)] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
    )
    elapsed_ms = round((time.time() - t0) * 1000, 1)
    if r.returncode != 0 and "error" not in r.stdout.lower():
        return {"_error": r.stderr or f"{cmd} failed", "_elapsed_ms": elapsed_ms}
    stdout = r.stdout or ""
    candidates = [stdout]
    # Find first line that starts a JSON object/array block
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            candidates.append("\n".join(lines[i:]))
            break
    # Fallback: find first '{' or '[' character position in raw string
    for marker in ("{", "["):
        pos = stdout.find(marker)
        if pos != -1:
            candidates.append(stdout[pos:])
            break
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            data["_elapsed_ms"] = elapsed_ms
            return data
        except json.JSONDecodeError:
            continue
    return {"_error": f"invalid JSON from {cmd}", "_raw": stdout[:500], "_elapsed_ms": elapsed_ms}


def main():
    print("=" * 60)
    print("开始执行一次完整交易循环")
    print("=" * 60)

    # Step 1+2
    print("\n[Step 1+2] 并发数据采集...")
    all_data = run("fetch_all_data.py")
    if "_error" in all_data:
        print(f"❌ fetch_all_data 失败: {all_data['_error']}")
        sys.exit(1)

    market = all_data.get("market", {})
    strategy = all_data.get("strategy", {})
    exposure = all_data.get("exposure", {})
    risk = all_data.get("risk", {})
    far_orders = all_data.get("far_orders", {})
    history = all_data.get("history", {})

    print(f"✅ 完成（{all_data['_elapsed_ms']} ms）")
    print(f"   当前价格: {market.get('last')} USDT")
    print(f"   趋势: {strategy.get('trend')}")
    print(f"   总暴露: {exposure.get('total')}/20")
    print(f"   剩余容量: {exposure.get('remaining_capacity')}")
    print(f"   远单数量: {len(far_orders.get('far_orders', []))}")
    print(f"   今日盈亏: {risk.get('daily_pnl')} USDT")
    print(f"   风控停止: {risk.get('should_stop')}")

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = {}
        for name in ["market", "exposure", "strategy", "far_orders", "orders", "history"]:
            p = os.path.join(tmpdir, f"{name}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(all_data.get(name, {}), f, ensure_ascii=False)
            paths[name] = p

        # Step 3a
        print("\n[Step 3a] AI 决策参考...")
        rec = run("calc_recommendation.py", paths["market"], paths["exposure"], paths["strategy"], paths["history"])
        print(f"✅ 完成（{rec['_elapsed_ms']} ms）")
        print(f"   建议: {rec.get('recommendation')} (置信度 {rec.get('confidence')})")
        print(f"   理由: {rec.get('reason')}")
        print(f"   风险标记: {rec.get('risk_flags', [])}")
        print(f"   脚本建议 target: long={rec.get('suggested_targets', {}).get('long')}, short={rec.get('suggested_targets', {}).get('short')}")

        # Step 3b
        print("\n[Step 3b] 生成交易草案...")
        plan = run("calc_plan.py", paths["market"], paths["exposure"], paths["strategy"], paths["far_orders"], paths["orders"])
        print(f"✅ 完成（{plan['_elapsed_ms']} ms）")
        print(f"   撤销: {len(plan.get('cancellations', []))} 张")
        print(f"   新建: {len(plan.get('placements', []))} 张")
        print(f"   操作: {plan.get('summary', {}).get('actions')}")

        for p in plan.get("placements", []):
            print(f"   ➕ {p.get('side')}+{p.get('posSide')} @ {p.get('px')}  TP={p.get('tpTriggerPx')} SL={p.get('slTriggerPx')}")

        plan_path = os.path.join(tmpdir, "tomokx_plan.json")
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False)

        # Step 4
        print("\n[Step 4] 执行交易计划...")
        exec_out = run("execute_and_finalize.py", plan_path)
        print(f"✅ 完成（{exec_out['_elapsed_ms']} ms）")

        exec_data = exec_out.get("execution", {})
        stop_counter = exec_out.get("stop_counter", {})

        print(f"   实际撤销: {len(exec_data.get('cancellations', []))} 张")
        for c in exec_data.get("cancellations", []):
            status = "✅" if "OK" in c.get("result", "") or "Cancelled" in c.get("result", "") else "⚠️"
            print(f"   {status} 撤单 {c.get('ordId')}: {c.get('result')}")

        print(f"   实际新建: {len(exec_data.get('placements', []))} 张")
        for p in exec_data.get("placements", []):
            status = "✅" if "OK" in p.get("result", "") or "placed" in p.get("result", "").lower() else "⚠️"
            print(f"   {status} 下单 {p.get('side')}+{p.get('posSide')} @ {p.get('px')}: {p.get('result')}")

        if "error" in stop_counter:
            print(f"   ⚠️ 止损计数器更新失败: {stop_counter['error']}")
        else:
            print(f"   止损计数器: {stop_counter.get('previous')} → {stop_counter.get('written')} (今日亏损平仓={stop_counter.get('losing_closes_today')})")
            print(f"   是否停止: {stop_counter.get('should_stop')}")

        print(f"   日志: {exec_out.get('log', 'N/A')}")

    print("\n" + "=" * 60)
    print("交易循环执行完毕")
    print("=" * 60)


if __name__ == "__main__":
    main()
