#!/usr/bin/env python3
"""
AI Decision Support Engine for tomokx.
Reads market, exposure, strategy, and history data;
outputs a structured recommendation with confidence score and reasoning.
"""
import json
import sys

# Force UTF-8 stdout on Windows to avoid GBK encode errors for CJK characters
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def calc_imbalance_score(exposure):
    long_total = exposure.get("long_orders", 0) + exposure.get("long_pos_units", 0)
    short_total = exposure.get("short_orders", 0) + exposure.get("short_pos_units", 0)
    return abs(long_total - short_total)


def trend_performance(history, trend):
    tp = history.get("trend_performance_7d", {})
    data = tp.get(trend, {"days": 0, "pnl": 0.0})
    return data.get("days", 0), data.get("pnl", 0.0)


def main():
    if len(sys.argv) < 5:
        print("Usage: python3 calc_recommendation.py <market.json> <exposure.json> <strategy.json> <history.json>")
        sys.exit(1)

    market = load_json(sys.argv[1])
    exposure = load_json(sys.argv[2])
    strategy = load_json(sys.argv[3])
    history = load_json(sys.argv[4])

    current_price = float(market.get("last", 0))
    volatility = float(market.get("volatility_1h", 0))
    spread = float(market.get("spread", 0))
    bid_sz = float(market.get("bidSz", 0))
    ask_sz = float(market.get("askSz", 0))
    trend = strategy.get("trend", "sideways")

    total = exposure.get("total", 0)
    remaining = exposure.get("remaining_capacity", 0)
    imbalance = round(calc_imbalance_score(exposure), 1)

    # Historical context
    trend_days, trend_pnl = trend_performance(history, trend)
    win_rate = history.get("win_rate_7d", 0.5)
    profit_factor = history.get("profit_factor", 1.0)
    max_dd = history.get("max_drawdown_7d", 0)
    avg_daily = history.get("avg_daily_pnl_7d", 0)

    # Base confidence
    confidence = 0.7
    reasons = []
    risk_flags = []
    recommendation = "proceed"
    suggested_targets = {
        "long": strategy.get("target_long", 1),
        "short": strategy.get("target_short", 1),
    }
    suggested_gap = strategy.get("adjusted_gap", 10)

    # --- Risk checks ---
    if spread > 2 and bid_sz < 10 and ask_sz < 10:
        recommendation = "pause"
        confidence = 0.95
        risk_flags.append("liquidity_crisis")
        reasons.append("极低流动性：spread > 2 USDT 且双边深度 < 10")

    if volatility > 35:
        recommendation = "pause"
        confidence = 0.9
        risk_flags.append("extreme_volatility")
        reasons.append(f"波动率极高 ({volatility})，建议暂停")
    elif volatility > 25:
        confidence -= 0.15
        risk_flags.append("high_volatility")
        reasons.append(f"波动率较高 ({volatility})，需加大 gap 或谨慎开仓")
        suggested_gap += 2

    if avg_daily < -5:
        confidence -= 0.15
        risk_flags.append("poor_recent_performance")
        reasons.append(f"近7天日均亏损 ({avg_daily} USDT)")

    if max_dd < -10:
        confidence -= 0.1
        risk_flags.append("deep_drawdown")
        reasons.append(f"最大回撤较深 ({max_dd} USDT)")

    # --- Historical regime check ---
    if trend_days >= 2:
        if trend_pnl < -5 or win_rate < 0.3:
            confidence -= 0.2
            risk_flags.append("bad_regime")
            reasons.append(f"{trend} 行情近期表现极差 ({trend_pnl} USDT, 胜率 {win_rate:.0%})")
            if recommendation == "proceed":
                recommendation = "reduce_exposure"
        elif trend_pnl > 5 and win_rate > 0.5:
            confidence += 0.1
            reasons.append(f"{trend} 行情近期表现良好 ({trend_pnl} USDT, 胜率 {win_rate:.0%})")

    # --- Imbalance adjustment ---
    if imbalance >= 3:
        confidence -= 0.1
        risk_flags.append("severe_imbalance")
        long_total = exposure.get("long_orders", 0) + exposure.get("long_pos_units", 0)
        short_total = exposure.get("short_orders", 0) + exposure.get("short_pos_units", 0)
        if long_total > short_total:
            suggested_targets["long"] = max(0, suggested_targets["long"] - 1)
            reasons.append(f"Long 侧过重 (imbalance={imbalance})，建议减少 long target")
        else:
            suggested_targets["short"] = max(0, suggested_targets["short"] - 1)
            reasons.append(f"Short 侧过重 (imbalance={imbalance})，建议减少 short target")
    elif imbalance >= 2:
        risk_flags.append("mild_imbalance")
        reasons.append(f"轻度失衡 (imbalance={imbalance})，优先补弱势侧")

    # --- Exposure checks ---
    if total >= 18:
        confidence -= 0.15
        risk_flags.append("high_exposure")
        reasons.append(f"总暴露接近上限 ({total}/20)，建议仅补极优位置")
        if recommendation == "proceed":
            recommendation = "reduce_exposure"
    elif total >= 14:
        confidence -= 0.05
        reasons.append(f"总暴露较高 ({total}/20)，谨慎开仓")

    if remaining <= 0:
        recommendation = "cancel_only"
        confidence = 0.95
        reasons.append("剩余容量为 0，仅处理远单")

    # --- Price jump / rebuild check ---
    existing_prices = []
    orders_list = exposure.get("_raw_orders", [])  # Not available here; leave for plan stage
    # Simplistic: if no remaining and price moved > 50 from any live order, suggest rebuild
    # This is best handled in calc_plan, so we only flag it lightly here

    # --- Finalize ---
    if not reasons:
        reasons.append(f"{trend} 趋势确认，暴露 {total}/20，imbalance={imbalance}，建议正常执行")

    confidence = round(max(0.1, min(0.99, confidence)), 2)

    result = {
        "recommendation": recommendation,
        "confidence": confidence,
        "reason": " ".join(reasons),
        "suggested_targets": suggested_targets,
        "suggested_gap": suggested_gap,
        "risk_flags": risk_flags,
        "historical_context": {
            "trend": trend,
            "trend_days_7d": trend_days,
            "trend_pnl_7d": trend_pnl,
            "win_rate_7d": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown_7d": max_dd,
            "imbalance_score": imbalance,
            "total_exposure": total,
            "remaining_capacity": remaining,
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
