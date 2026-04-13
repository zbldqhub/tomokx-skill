#!/usr/bin/env python3
"""Unit tests for calc_exposure.py logic."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw"))
from config import classify_orders, classify_positions


def test_classify_orders():
    orders = [
        {"instId": "ETH-USDT-SWAP", "state": "live", "ordType": "limit", "side": "buy", "posSide": "long"},
        {"instId": "ETH-USDT-SWAP", "state": "live", "ordType": "limit", "side": "sell", "posSide": "short"},
        {"instId": "ETH-USDT-SWAP", "state": "filled", "ordType": "limit", "side": "buy", "posSide": "long"},
        {"instId": "BTC-USDT-SWAP", "state": "live", "ordType": "limit", "side": "buy", "posSide": "long"},
    ]
    short, long = classify_orders(orders)
    assert short == 1
    assert long == 1


def test_classify_positions():
    positions = [
        {"instId": "ETH-USDT-SWAP", "lever": "10", "mgnMode": "isolated", "pos": "0.3", "posSide": "long"},
        {"instId": "ETH-USDT-SWAP", "lever": "10", "mgnMode": "isolated", "pos": "0.2", "posSide": "short"},
        {"instId": "ETH-USDT-SWAP", "lever": "20", "mgnMode": "isolated", "pos": "0.1", "posSide": "long"},
        {"instId": "BTC-USDT-SWAP", "lever": "10", "mgnMode": "isolated", "pos": "0.5", "posSide": "long"},
    ]
    short_pos, long_pos = classify_positions(positions)
    assert short_pos == 0.2
    assert long_pos == 0.3


if __name__ == "__main__":
    test_classify_orders()
    test_classify_positions()
    print("test_calc_exposure passed")
