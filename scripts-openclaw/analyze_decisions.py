#!/usr/bin/env python3
"""Analyze decisions.jsonl and suggest strategy parameter optimizations."""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DECISION_LOG_PATH


def load_decisions(path):
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError:
                continue
    return entries


def analyze(entries, min_samples=3):
    # Group by composite key
    groups = defaultdict(list)
    for e in entries:
        if "outcome_pnl" not in e:
            continue
        market = e.get("market_state", {})
        strategy = e.get("strategy_params", {})
        actions = e.get("actual_actions", {})
        key = (
            market.get("trend", "unknown"),
            strategy.get("gap", ""),
            strategy.get("target_long"),
            strategy.get("target_short"),
            actions.get("long_expansion", ""),
            actions.get("short_expansion", ""),
        )
        groups[key].append(float(e["outcome_pnl"]))

    stats = []
    for key, pnls in groups.items():
        if len(pnls) < min_samples:
            continue
        avg = round(sum(pnls) / len(pnls), 4)
        win_rate = round(sum(1 for p in pnls if p > 0) / len(pnls), 2)
        stats.append({
            "trend": key[0],
            "gap": key[1],
            "target_long": key[2],
            "target_short": key[3],
            "long_expansion": key[4],
            "short_expansion": key[5],
            "count": len(pnls),
            "avg_pnl": avg,
            "win_rate": win_rate,
        })

    stats.sort(key=lambda x: x["avg_pnl"], reverse=True)
    return stats


def suggest_gap_adjustment(entries):
    """Compare average outcome across gap values."""
    gap_pnls = defaultdict(list)
    for e in entries:
        if "outcome_pnl" not in e:
            continue
        gap = str(e.get("strategy_params", {}).get("gap", ""))
        if gap:
            gap_pnls[gap].append(float(e["outcome_pnl"]))

    if not gap_pnls:
        return {}
    gap_stats = {}
    for gap, pnls in gap_pnls.items():
        if len(pnls) < 3:
            continue
        gap_stats[gap] = {
            "count": len(pnls),
            "avg_pnl": round(sum(pnls) / len(pnls), 4),
            "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 2),
        }
    return gap_stats


def main():
    entries = load_decisions(DECISION_LOG_PATH)
    total = len(entries)
    closed = [e for e in entries if "outcome_pnl" in e]

    print(f"Total decisions: {total}")
    print(f"Closed decisions: {len(closed)}")

    if len(closed) < 5:
        print("Not enough closed decisions for statistical analysis (need >= 5).")
        sys.exit(0)

    stats = analyze(closed, min_samples=3)
    gap_stats = suggest_gap_adjustment(closed)

    result = {
        "total_decisions": total,
        "closed_decisions": len(closed),
        "top_performers": stats[:5],
        "bottom_performers": stats[-5:],
        "gap_comparison": gap_stats,
        "recommendations": [],
    }

    if stats:
        best = stats[0]
        result["recommendations"].append(
            f"Best performing setup: trend={best['trend']} gap={best['gap']} "
            f"targets=({best['target_long']},{best['target_short']}) "
            f"avg_pnl={best['avg_pnl']} win_rate={best['win_rate']}"
        )
    if gap_stats:
        best_gap = max(gap_stats.items(), key=lambda x: x[1]["avg_pnl"])
        result["recommendations"].append(
            f"Best gap value so far: {best_gap[0]} (avg_pnl={best_gap[1]['avg_pnl']}, n={best_gap[1]['count']})"
        )
    if stats and stats[0]["avg_pnl"] < 0:
        result["recommendations"].append(
            "WARNING: All analyzed setups have negative average PnL. Consider reducing exposure or pausing."
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
