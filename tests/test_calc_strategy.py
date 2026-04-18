#!/usr/bin/env python3
"""Unit tests for calc_strategy.py logic."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw"))
from calc_strategy import resolve_trend, targets, base_gap


def test_targets():
    # Align with SKILL.md (strong/moderate: bullish 2/1, bearish 1/2)
    assert targets("bullish", "strong") == (2, 1)
    assert targets("bearish", "strong") == (1, 2)
    assert targets("sideways", "strong") == (1, 1)
    assert targets("bullish", "moderate") == (2, 1)
    assert targets("bearish", "moderate") == (1, 2)
    assert targets("bullish", "mixed") == (1, 1)
    assert targets("sideways", "weak") == (1, 1)


def test_resolve_trend():
    # Strong bullish
    m1 = {"trend_4h": "bullish", "trend_1h": "bullish", "trend_15m": "bullish", "funding_bias": "neutral"}
    trend, tl, ts, align, _ = resolve_trend(m1)
    assert trend == "bullish" and align == "strong"
    assert tl == 2 and ts == 1

    # Moderate bearish
    m2 = {"trend_4h": "bearish", "trend_1h": "bearish", "trend_15m": "bullish", "funding_bias": "neutral"}
    trend, tl, ts, align, _ = resolve_trend(m2)
    assert trend == "bearish" and align == "moderate"
    assert tl == 1 and ts == 2

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
    # P2: relaxed floor values (2026-04-16)
    assert base_gap(0) == 8
    assert base_gap(1) == 9
    assert base_gap(4) == 11
    assert base_gap(6) == 12
    assert base_gap(11) == 14
    assert base_gap(16) == 16


if __name__ == "__main__":
    test_targets()
    test_resolve_trend()
    test_base_gap()
    print("test_calc_strategy passed")
