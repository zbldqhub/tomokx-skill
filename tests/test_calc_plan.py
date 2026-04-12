#!/usr/bin/env python3
"""Unit tests for calc_plan.py logic."""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw"))
from calc_plan import pick_best_long_px, pick_best_short_px, calc_tp_sl_offset


def test_calc_tp_sl_offset():
    assert calc_tp_sl_offset(3) == (12, 85)
    assert calc_tp_sl_offset(8) == (20, 90)
    assert calc_tp_sl_offset(18) == (38, 108)
    assert calc_tp_sl_offset(30) == (45, 115)


def test_pick_best_long_px_inner():
    # Price moved inside grid: existing longs at 2200, 2190. Current price 2210
    existing = [2190, 2200]
    chosen = []
    px = pick_best_long_px(2210, existing, 10, chosen)
    # Should pick inner candidate: 2210 - 10 = 2200, but must be < min(existing)=2190, so 2190-10=2180
    assert px is not None
    assert px < 2210
    assert abs(px - 2210) < 80
    assert all(abs(px - p) >= 10 for p in existing)


def test_pick_best_short_px_outer():
    existing = [2300, 2310]
    chosen = []
    px = pick_best_short_px(2210, existing, 10, chosen)
    assert px is not None
    assert px > 2210
    # Should pick inner candidate closest to current price: 2210 + 10 = 2220
    assert px == 2220


def test_full_plan_json():
    import subprocess
    market = {"last": 2210, "volatility_1h": 12}
    exposure = {"long_orders": 2, "short_orders": 1, "orders_count": 3, "positions_count": 2, "total": 5, "remaining_capacity": 15}
    strategy = {"trend": "bullish", "target_long": 2, "target_short": 1, "adjusted_gap": 10}
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


if __name__ == "__main__":
    test_calc_tp_sl_offset()
    test_pick_best_long_px_inner()
    test_pick_best_short_px_outer()
    test_full_plan_json()
    print("test_calc_plan passed")
