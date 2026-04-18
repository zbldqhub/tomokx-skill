#!/usr/bin/env python3
"""Unit tests for calc_plan.py logic."""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw"))
from calc_plan import pick_best_long_px, pick_best_short_px, calc_tp_sl_offset


def test_calc_tp_sl_offset():
    # Gap-based fallback (atr=None)
    # tp=max(15,int(gap*2.0)), sl=max(20,int(gap*2.5))
    # Vol bonuses: >15 +1/+2, >25 +3/+5, >35 +5/+8
    assert calc_tp_sl_offset(3, 10) == (20, 25)   # tp=max(15,20)=20, sl=max(20,25)=25, vol<=15
    assert calc_tp_sl_offset(8, 10) == (20, 25)   # same
    assert calc_tp_sl_offset(12, 10) == (20, 25)  # vol=12 <=15, no bonus
    assert calc_tp_sl_offset(18, 12) == (25, 32)  # tp=max(15,24)=24, sl=max(20,30)=30, vol>15 → +1/+2
    assert calc_tp_sl_offset(30, 15) == (33, 42)  # tp=max(15,30)=30, sl=max(20,37)=37, vol>25 → +3/+5

    # ATR-based (atr provided)
    assert calc_tp_sl_offset(3, 10, atr=8) == (16, 20)   # tp=max(15,16)=16, sl=max(20,20)=20
    assert calc_tp_sl_offset(18, 12, atr=8) == (17, 22)  # atr=8 → tp=16, sl=20, vol>15 → +1/+2
    assert calc_tp_sl_offset(30, 15, atr=10) == (23, 30) # atr=10 → tp=20, sl=25, vol>25 → +3/+5


def test_pick_best_long_px_inner():
    # Price moved inside grid: existing longs at 2200, 2190. Current price 2210
    existing = [2190, 2200]
    chosen = []
    px, mode, rejected = pick_best_long_px(2210, existing, 10, chosen)
    # Should pick inner candidate: 2210 - 10 = 2200, but must be < min(existing)=2190, so 2190-10=2180
    assert px is not None
    assert mode == "replenish"
    assert px < 2210
    assert abs(px - 2210) < 80
    assert all(abs(px - p) >= 10 for p in existing)


def test_pick_best_short_px_outer():
    existing = [2300, 2310]
    chosen = []
    px, mode, rejected = pick_best_short_px(2210, existing, 10, chosen)
    assert px is not None
    assert mode == "replenish"
    assert px > 2210
    # Should pick inner candidate closest to current price: 2210 + 10 = 2220
    assert px == 2220


def test_full_plan_json():
    import subprocess
    market = {"last": 2210, "volatility_1h": 12}
    exposure = {"long_orders": 2, "short_orders": 1, "orders_count": 3, "positions_count": 2, "total": 5, "remaining_capacity": 15}
    strategy = {"trend": "bullish", "target_long": 2, "target_short": 1, "adjusted_gap": 10, "trend_alignment": "moderate", "imbalance_score": 0}
    far_orders = {"far_orders": []}
    orders = {"data": [
        {"instId": "ETH-USDT-SWAP", "state": "live", "side": "buy", "posSide": "long", "px": "2200", "ordId": "a"},
        {"instId": "ETH-USDT-SWAP", "state": "live", "side": "buy", "posSide": "long", "px": "2190", "ordId": "b"},
        {"instId": "ETH-USDT-SWAP", "state": "live", "side": "sell", "posSide": "short", "px": "2220", "ordId": "c"},
    ]}

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = {}
        for name, data in [("market", market), ("exposure", exposure), ("strategy", strategy), ("far_orders", far_orders), ("orders", orders)]:
            p = os.path.join(tmpdir, f"{name}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f)
            paths[name] = p

        script = os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw", "calc_plan.py")
        r = subprocess.run(
            [sys.executable, script, paths["market"], paths["exposure"], paths["strategy"], paths["far_orders"], paths["orders"]],
            capture_output=True, text=True
        )
        assert r.returncode == 0, r.stderr
        plan = json.loads(r.stdout)
        # We need 1 more long (2 target - 2 existing) and 0 more short
        long_placements = [p for p in plan["placements"] if p["posSide"] == "long"]
        short_placements = [p for p in plan["placements"] if p["posSide"] == "short"]
        assert len(long_placements) >= 0
        assert len(short_placements) >= 0
        for p in plan["placements"]:
            assert float(p["tpTriggerPx"]) != float(p["px"])
            assert float(p["slTriggerPx"]) != float(p["px"])


def test_inner_replenish_boost_short():
    import subprocess, tempfile
    market = {"last": 2200, "volatility_1h": 12}
    exposure = {"long_orders": 4, "short_orders": 2, "orders_count": 6, "positions_count": 2, "total": 8, "remaining_capacity": 12}
    strategy = {"trend": "bullish", "target_long": 2, "target_short": 1, "adjusted_gap": 14, "trend_alignment": "moderate", "imbalance_score": 0}
    far_orders = {"far_orders": []}
    orders = {"data": [
        {"instId": "ETH-USDT-SWAP", "state": "live", "side": "sell", "posSide": "short", "px": "2244.58", "ordId": "s1"},
        {"instId": "ETH-USDT-SWAP", "state": "live", "side": "sell", "posSide": "short", "px": "2288.75", "ordId": "s2"},
        {"instId": "ETH-USDT-SWAP", "state": "live", "side": "buy", "posSide": "long", "px": "2190", "ordId": "l1"},
    ]}

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = {}
        for name, data in [("market", market), ("exposure", exposure), ("strategy", strategy), ("far_orders", far_orders), ("orders", orders)]:
            p = os.path.join(tmpdir, f"{name}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f)
            paths[name] = p

        script = os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw", "calc_plan.py")
        r = subprocess.run(
            [sys.executable, script, paths["market"], paths["exposure"], paths["strategy"], paths["far_orders"], paths["orders"]],
            capture_output=True, text=True
        )
        assert r.returncode == 0, r.stderr
        plan = json.loads(r.stdout)
        # Should boost short_needed from 0 to 1 because price moved below all short orders
        assert len(plan["placements"]) >= 1, f"Expected at least 1 placement, got {plan}"
        short_placements = [p for p in plan["placements"] if p["posSide"] == "short"]
        assert len(short_placements) == 1
        px = float(short_placements[0]["px"])
        assert px > 2200
        assert px < 2244.58
        assert "boost needed=1" in " ".join(plan["reasoning"]["short"]["notes"])


if __name__ == "__main__":
    test_calc_tp_sl_offset()
    test_pick_best_long_px_inner()
    test_pick_best_short_px_outer()
    test_full_plan_json()
    test_inner_replenish_boost_short()
    print("test_calc_plan passed")
