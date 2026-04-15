#!/usr/bin/env python3
"""Unit tests for calc_strategy.py logic."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw"))
from calc_strategy import resolve_trend, targets, base_gap


def test_targets():
    assert targets("bullish", "strong") == (4, 1)
    assert targets("bearish", "strong") == (1, 4)
    assert targets("sideways", "strong") == (2, 2)
    assert targets("bullish", "moderate") == (3, 1)
    assert targets("bearish", "moderate") == (1, 3)
    assert targets("bullish", "mixed") == (2, 1)
    assert targets("sideways", "weak") == (1, 1)


def test_resolve_trend():
    # Strong bullish
    m1 = {"trend_4h": "bullish", "trend_1h": "bullish", "trend_15m": "bullish", "funding_bias": "neutral"}
    trend, tl, ts, align, _ = resolve_trend(m1)
    assert trend == "bullish" and align == "strong"
    assert tl == 4 and ts == 1

    # Moderate bearish
    m2 = {"trend_4h": "bearish", "trend_1h": "bearish", "trend_15m": "bullish", "funding_bias": "neutral"}
    trend, tl, ts, align, _ = resolve_trend(m2)
    assert trend == "bearish" and align == "moderate"
    assert tl == 1 and ts == 3

    # Mixed (4h == 15m != 1h)
    m3 = {"trend_4h": "bullish", "trend_1h": "bearish", "trend_15m": "bullish", "funding_bias": "neutral"}
    trend, tl, ts, align, _ = resolve_trend(m3)
    assert trend == "sideways" and align == "mixed"
    assert tl == 0 and ts == 0

    # Weak
    m4 = {"trend_4h": "bullish", "trend_1h": "bearish", "trend_15m": "sideways", "funding_bias": "neutral"}
    trend, tl, ts, align, _ = resolve_trend(m4)
    assert trend == "sideways" and align == "weak"
    assert tl == 0 and ts == 0


def test_base_gap():
    assert base_gap(0) == 3
    assert base_gap(1) == 4
    assert base_gap(4) == 7
    assert base_gap(6) == 8
    assert base_gap(11) == 10
    assert base_gap(16) == 12


if __name__ == "__main__":
    test_targets()
    test_resolve_trend()
    test_base_gap()
    print("test_calc_strategy passed")
