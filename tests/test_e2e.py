#!/usr/bin/env python3
"""End-to-end integration test for the full tomokx trading cycle."""
import json
import os
import subprocess
import sys
import tempfile
import time

# Force UTF-8 stdout on Windows to avoid GBK encode errors
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
    if r.returncode not in (0, 2) and "error" not in r.stdout.lower():
        return {"_error": r.stderr or f"{cmd} failed", "_elapsed_ms": elapsed_ms}
    stdout = r.stdout or ""
    # Some scripts (e.g., execute_and_finalize) print human-readable lines before JSON.
    # Try the whole stdout first, then fall back to the last non-empty line.
    # Extract JSON from stdout: try whole stdout, then from the first line starting with { or [
    candidates = [stdout]
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("{"):
            candidates.append("\n".join(lines[i:]))
            break
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            data["_elapsed_ms"] = elapsed_ms
            return data
        except json.JSONDecodeError:
            continue
    return {"_error": f"invalid JSON from {cmd}", "_raw": stdout[:500], "_raw_full": stdout, "_elapsed_ms": elapsed_ms}


def main():
    results = []
    t0_total = time.time()

    # Step 1+2: fetch_all_data
    all_data = run("fetch_all_data.py")
    if "_error" in all_data:
        print(json.dumps({"fatal": f"fetch_all_data failed: {all_data['_error']}"}, ensure_ascii=False, indent=2))
        sys.exit(1)

    results.append({
        "step": "1+2 fetch_all_data",
        "elapsed_ms": all_data["_elapsed_ms"],
        "market_last": all_data.get("market", {}).get("last"),
        "trend": all_data.get("strategy", {}).get("trend"),
        "exposure_total": all_data.get("exposure", {}).get("total"),
        "remaining": all_data.get("exposure", {}).get("remaining_capacity"),
        "far_count": len(all_data.get("far_orders", {}).get("far_orders", [])),
        "risk_stop": all_data.get("risk", {}).get("should_stop"),
        "daily_pnl": all_data.get("risk", {}).get("daily_pnl"),
    })

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = {}
        for name in ["market", "exposure", "strategy", "far_orders", "orders", "history"]:
            p = os.path.join(tmpdir, f"{name}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(all_data.get(name, {}), f, ensure_ascii=False)
            paths[name] = p

        # Step 3a: calc_recommendation
        rec = run("calc_recommendation.py", paths["market"], paths["exposure"], paths["strategy"], paths["history"])
        results.append({
            "step": "3a calc_recommendation",
            "elapsed_ms": rec.get("_elapsed_ms", 0),
            "recommendation": rec.get("recommendation"),
            "confidence": rec.get("confidence"),
            "reason": rec.get("reason"),
            "risk_flags": rec.get("risk_flags", []),
        })

        # Step 3b: calc_plan
        plan = run("calc_plan.py", paths["market"], paths["exposure"], paths["strategy"], paths["far_orders"], paths["orders"])
        plan_path = os.path.join(tmpdir, "tomokx_plan.json")
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False)
        results.append({
            "step": "3b calc_plan",
            "elapsed_ms": plan.get("_elapsed_ms", 0),
            "cancellations": len(plan.get("cancellations", [])),
            "placements": len(plan.get("placements", [])),
            "actions": plan.get("summary", {}).get("actions"),
        })

        # Step 4: execute_and_finalize
        exec_out = run("execute_and_finalize.py", plan_path)
        if "_error" in exec_out:
            print(f"[WARN] execute_and_finalize returned error: {exec_out.get('_error')}")
        results.append({
            "step": "4 execute_and_finalize",
            "elapsed_ms": exec_out.get("_elapsed_ms", 0),
            "exec_cancellations": len(exec_out.get("execution", {}).get("cancellations", [])),
            "exec_placements": len(exec_out.get("execution", {}).get("placements", [])),
            "stop_written": exec_out.get("stop_counter", {}).get("written"),
            "should_stop": exec_out.get("stop_counter", {}).get("should_stop"),
            "log": exec_out.get("log"),
        })

    total_ms = round((time.time() - t0_total) * 1000, 1)
    results.append({"step": "TOTAL", "elapsed_ms": total_ms})

    # Print human-readable report
    print("=" * 60)
    print("Tomokx End-to-End Trading Execution Report")
    print("=" * 60)
    for r in results:
        if r["step"] == "TOTAL":
            print(f"\n[TOTAL] {r['step']}: {r['elapsed_ms']} ms")
        else:
            print(f"\n[STEP] {r['step']}: {r['elapsed_ms']} ms")
            for k, v in r.items():
                if k in ("step", "elapsed_ms"):
                    continue
                print(f"    - {k}: {v}")
    print("=" * 60)

    # Also emit structured JSON
    print("\n" + json.dumps({"results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
