#!/usr/bin/env python3
"""
AI Decision Support Engine for tomokx.
Reads market, exposure, strategy, and history data;
outputs a structured recommendation with confidence score and reasoning.
"""
import json
import sys

import os
from datetime import datetime, timezone
from config import MAX_TOTAL, WORKSPACE

# Force UTF-8 stdout on Windows to avoid GBK encode errors for CJK characters
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_rules():
    rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")
    if os.path.exists(rules_path):
        return load_json(rules_path)
    return {}


RULES = load_rules()
MICRO = RULES.get("microstructure", {})


def calc_imbalance_score(exposure):
    long_total = exposure.get("long_orders", 0) + exposure.get("long_pos_units", 0)
    short_total = exposure.get("short_orders", 0) + exposure.get("short_pos_units", 0)
    return abs(long_total - short_total)


def check_event_risk():
    events_path = os.path.join(WORKSPACE, "events.json")
    if not os.path.exists(events_path):
        return None
    try:
        with open(events_path, "r", encoding="utf-8-sig") as f:
            events = json.load(f)
    except Exception:
        return None
    now = datetime.now(timezone.utc)
    for ev in events:
        try:
            ev_time = datetime.fromisoformat(ev["time"].replace("Z", "+00:00"))
            delta = abs((now - ev_time).total_seconds())
            if delta <= 3600:
                return ev
        except Exception:
            continue
    return None


def check_time_risk(volatility):
    now = datetime.now(timezone.utc)
    hour = now.hour
    if 14 <= hour < 15 and volatility > 15:
        return "us_open_overlap"
    if hour == 0 and volatility > 15:
        return "funding_settlement"
    return None


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
        "long": max(0, int(strategy.get("target_long", 1))),
        "short": max(0, int(strategy.get("target_short", 1))),
    }
    suggested_gap = strategy.get("adjusted_gap", 10)

    # --- Event / time risk checks ---
    event = check_event_risk()
    if event:
        recommendation = "pause"
        confidence = min(confidence, 0.3)
        risk_flags.append("high_impact_event")
        reasons.append(f'重大事件窗口: {event.get("title", "unknown")} ({event.get("time", "")})，建议暂停')

    time_risk = check_time_risk(volatility)
    if time_risk:
        confidence -= 0.1
        risk_flags.append(time_risk)
        if time_risk == "us_open_overlap":
            reasons.append("UTC 14:00-15:00 美股开盘重叠期 + 高波动，谨慎开仓")
        elif time_risk == "funding_settlement":
            reasons.append("UTC 00:00-01:00 资金费结算窗口 + 高波动，谨慎开仓")

    # --- Market risk checks ---
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

    # --- Microstructure signals ---
    micro = market.get("microstructure", {})

    depth_ratio = bid_sz / ask_sz if ask_sz > 0 else 999
    dr_cfg = MICRO.get("depth_ratio", {})
    if depth_ratio > dr_cfg.get("bid_dominant_threshold", 3.0):
        confidence -= dr_cfg.get("confidence_penalty", 0.05)
        risk_flags.append("bid_depth_dominant")
        reasons.append(f"买方深度占优 (ratio={depth_ratio:.1f})，short 侧成交风险上升")
    elif depth_ratio < dr_cfg.get("ask_dominant_threshold", 0.33):
        confidence -= dr_cfg.get("confidence_penalty", 0.05)
        risk_flags.append("ask_depth_dominant")
        reasons.append(f"卖方深度占优 (ratio={depth_ratio:.1f})，long 侧成交风险上升")

    # Order book imbalance (near-mid price)
    obi = micro.get("order_book_imbalance", 0)
    obi_cfg = MICRO.get("order_book_imbalance", {})
    if obi > obi_cfg.get("bid_extreme", 0.5):
        confidence -= obi_cfg.get("confidence_penalty", 0.03)
        risk_flags.append("book_imbalance_bid")
        reasons.append(f"订单簿买方失衡 (obi={obi:.2f})，short 侧承压")
    elif obi < obi_cfg.get("ask_extreme", -0.5):
        confidence -= obi_cfg.get("confidence_penalty", 0.03)
        risk_flags.append("book_imbalance_ask")
        reasons.append(f"订单簿卖方失衡 (obi={obi:.2f})，long 侧承压")

    # Recent trade pressure
    pressure_ratio = micro.get("pressure_ratio", 1.0)
    pr_cfg = MICRO.get("pressure_ratio", {})
    if pressure_ratio > pr_cfg.get("buy_dominant_threshold", 3.0):
        confidence -= pr_cfg.get("confidence_penalty", 0.03)
        risk_flags.append("buy_pressure_dominant")
        reasons.append(f"买盘成交占优 (ratio={pressure_ratio:.1f})，short 成交风险上升")
    elif pressure_ratio < pr_cfg.get("sell_dominant_threshold", 0.33):
        confidence -= pr_cfg.get("confidence_penalty", 0.03)
        risk_flags.append("sell_pressure_dominant")
        reasons.append(f"卖盘成交占优 (ratio={pressure_ratio:.1f})，long 成交风险上升")

    # Large trade activity
    large_trades = micro.get("large_trade_count", 0)
    lt_cfg = MICRO.get("large_trade", {})
    if large_trades >= lt_cfg.get("count_threshold", 5):
        confidence -= lt_cfg.get("confidence_penalty", 0.05)
        risk_flags.append("whale_activity")
        reasons.append(f"近 100 笔成交出现 {large_trades} 笔大单 (≥{lt_cfg.get('size_threshold', 10)} ETH)，警惕鲸鱼操纵")

    # 5m price velocity (quick momentum check)
    vel_5m = micro.get("price_velocity_5m_pct", 0)
    pv_cfg = MICRO.get("price_velocity_5m", {})
    if abs(vel_5m) > pv_cfg.get("abs_threshold", 1.5) and volatility > pv_cfg.get("volatility_min", 15):
        if (trend == "bearish" and vel_5m > 0) or (trend == "bullish" and vel_5m < 0):
            confidence -= pv_cfg.get("confidence_penalty", 0.08)
            risk_flags.append("fast_momentum_divergence")
            reasons.append(f"5m 快速反弹 ({vel_5m:.1f}%) 与 {trend} 趋势背离")

    # Funding velocity (extremization)
    fund_vel = micro.get("funding_velocity", 0)
    fv_cfg = MICRO.get("funding_velocity", {})
    if abs(fund_vel) > fv_cfg.get("abs_threshold", 0.01):
        confidence -= fv_cfg.get("confidence_penalty", 0.05)
        risk_flags.append("funding_accelerating")
        reasons.append(f"资金费率加速偏离 (velocity={fund_vel:.4f}%)，方向风险上升")

    recent_change_1h = float(market.get("recent_change_1h_pct", 0))
    if abs(recent_change_1h) > 2 and volatility > 15:
        # Momentum divergence: recent move is large but trend may not fully align
        if (trend == "bearish" and recent_change_1h > 0) or (trend == "bullish" and recent_change_1h < 0):
            confidence -= 0.1
            risk_flags.append("momentum_divergence")
            reasons.append(f"1h 价格走势 ({recent_change_1h:.1f}%) 与 {trend} 趋势背离，警惕假突破")

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
        reasons.append(f"总暴露接近上限 ({total}/{MAX_TOTAL})，建议仅补极优位置")
        if recommendation == "proceed":
            recommendation = "reduce_exposure"
    elif total >= 14:
        confidence -= 0.05
        reasons.append(f"总暴露较高 ({total}/{MAX_TOTAL})，谨慎开仓")

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
        reasons.append(f"{trend} 趋势确认，暴露 {total}/{MAX_TOTAL}，imbalance={imbalance}，建议正常执行")

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
