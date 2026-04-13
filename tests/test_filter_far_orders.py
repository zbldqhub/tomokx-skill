#!/usr/bin/env python3
"""Unit tests for filter_far_orders.py logic."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw"))
from filter_far_orders import main as ffm
import json


def test_filter_far_orders():
    orders = {
        "data": [
            {"instId": "ETH-USDT-SWAP", "state": "live", "px": "2100", "ordId": "1", "side": "buy", "posSide": "long"},
            {"instId": "ETH-USDT-SWAP", "state": "live", "px": "2215", "ordId": "2", "side": "sell", "posSide": "short"},
            {"instId": "ETH-USDT-SWAP", "state": "filled", "px": "2300", "ordId": "3", "side": "sell", "posSide": "short"},
        ]
    }
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(orders, f)
        path = f.name

    try:
        import io
        from contextlib import redirect_stdout
        import sys
        buf = io.StringIO()
        with redirect_stdout(buf):
            sys.argv = ["filter_far_orders.py", path, "2217"]
            ffm()
        result = json.loads(buf.getvalue())
        assert len(result["far_orders"]) == 1
        assert result["far_orders"][0]["ordId"] == "1"
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_filter_far_orders()
    print("test_filter_far_orders passed")
