#!/usr/bin/env python3
"""Unit tests for calc_recommendation.py logic."""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw"))
from calc_recommendation import calc_imbalance_score, trend_performance


def test_calc_imbalance_score():
    exposure = {
        "long_orders": 3, "long_pos_units": 1.0,
        "short_orders": 1, "short_pos_units": 0.5
    }
    assert calc_imbalance_score(exposure) == 2.5

    exposure2 = {
        "long_orders": 1, "long_pos_units": 0.0,
        "short_orders": 1, "short_pos_units": 0.0
    }
    assert calc_imbalance_score(exposure2) == 0.0


def test_trend_performance():
    history = {
        "trend_performance_7d": {
            "bullish": {"days": 3, "pnl": 5.5},
            "bearish": {"days": 1, "pnl": -2.0}
        }
    }
    days, pnl = trend_performance(history, "bullish")
    assert days == 3
    assert pnl == 5.5
    days2, pnl2 = trend_performance(history, "sideways")
    assert days2 == 0
    assert pnl2 == 0.0


def test_main_json():
    import subprocess
    market = {"last": 2210, "volatility_1h": 12, "spread": 0.1, "bidSz": 100, "askSz": 100}
    exposure = {"long_orders": 2, "short_orders": 1, "long_pos_units": 0.2, "short_pos_units": 0.1, "total": 5.3, "remaining_capacity": 14}
    strategy = {"trend": "bullish", "target_long": 2, "target_short": 1, "adjusted_gap": 10}
    history = {
        "total_pnl_7d": 5.0, "win_rate_7d": 0.6, "profit_factor": 1.5,
        "max_drawdown_7d": -2.0, "avg_daily_pnl_7d": 0.5,
        "trend_performance_7d": {"bullish": {"days": 2, "pnl": 3.0}}
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = {}
        for name, data in [("market", market), ("exposure", exposure), ("strategy", strategy), ("history", history)]:
            p = os.path.join(tmpdir, f"{name}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f)
            paths[name] = p

        script = os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw", "calc_recommendation.py")
        r = subprocess.run(
            [sys.executable, script, paths["market"], paths["exposure"], paths["strategy"], paths["history"]],
            capture_output=True, text=True
        )
        assert r.returncode == 0, r.stderr
        result = json.loads(r.stdout)
        assert result["recommendation"] == "proceed"
        assert 0 < result["confidence"] <= 0.99
        assert "reason" in result
        assert "suggested_targets" in result
        assert "risk_flags" in result
        assert "historical_context" in result


if __name__ == "__main__":
    test_calc_imbalance_score()
    test_trend_performance()
    test_main_json()
    print("test_calc_recommendation passed")
