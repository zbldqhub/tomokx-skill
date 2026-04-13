#!/usr/bin/env python3
"""Unit tests for calc_strategy.py logic."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts-openclaw"))
from calc_strategy import trend_from_data, targets, base_gap


def test_trend_from_data():
    assert trend_from_data(3.0, "sideways") == "sideways"
    assert trend_from_data(-1.0, "bullish") == "bullish"
    assert trend_from_data(3.0, "bearish") == "bearish"
    assert trend_from_data(3.0, "") == "bullish"
    assert trend_from_data(-3.0, "") == "bearish"


def test_targets():
    assert targets("bullish") == (2, 1)
    assert targets("bearish") == (1, 2)
    assert targets("sideways") == (1, 2)


def test_base_gap():
    assert base_gap(0) == 5
    assert base_gap(4) == 9
    assert base_gap(6) == 10
    assert base_gap(11) == 12
    assert base_gap(16) == 14


if __name__ == "__main__":
    test_trend_from_data()
    test_targets()
    test_base_gap()
    print("test_calc_strategy passed")
