#!/usr/bin/env python3
"""
Unified configuration module for tomokx trading system.
Loads environment variables and exposes all strategy constants.
"""
import os
import sys

# Workspace paths
WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
ENV_FILE = os.path.join(WORKSPACE, ".env.trading")
LOG_PATH = os.path.join(WORKSPACE, "auto_trade.log")
JSONL_PATH = os.path.join(WORKSPACE, "auto_trade.jsonl")
DECISION_LOG_PATH = os.path.join(WORKSPACE, "decisions.jsonl")
ORDER_TRACKING_PATH = os.path.join(WORKSPACE, "order_tracking.jsonl")
STOP_FILE = os.path.join(WORKSPACE, ".trading_stopped")

# Strategy constants
MAX_TOTAL = 30
MAX_PER_SIDE = 6
ORDER_SIZE = 0.1
LEVERAGE = 10
DAILY_LOSS_LIMIT = -40
CANCEL_THRESHOLD = 100
DISTANCE_CAP = 80

# Gap table by total exposure
def base_gap(total):
    if total <= 0:
        return 3
    elif total == 1:
        return 4
    elif total == 2:
        return 5
    elif total == 3:
        return 6
    elif total == 4:
        return 7
    elif total <= 6:
        return 8
    elif total <= 10:
        return 9
    elif total <= 15:
        return 10
    else:
        return 12


def calc_tp_sl_offset(volatility_1h, gap):
    tp = max(8, int(gap * 1.2))
    sl = max(16, int(gap * 1.8))
    if volatility_1h > 25:
        tp += 3
        sl += 4
    elif volatility_1h > 15:
        tp += 2
        sl += 3
    elif volatility_1h > 10:
        tp += 1
        sl += 2
    return tp, sl


def load_env():
    """Load .env.trading into os.environ if not already present."""
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v


# Auto-load on import
load_env()

# OKX API credentials (may be empty if env not configured)
API_KEY = os.environ.get("OKX_API_KEY", "")
SECRET = os.environ.get("OKX_SECRET_KEY", "")
PASSPHRASE = os.environ.get("OKX_PASSPHRASE", "")
BASE_URL = os.environ.get("OKX_BASE_URL", "https://www.okx.com")


def classify_orders(orders_list):
    short, long = 0, 0
    for o in orders_list:
        if o.get("instId") != "ETH-USDT-SWAP" or o.get("state") != "live":
            continue
        if o.get("ordType") != "limit":
            continue
        side = o.get("side")
        pos_side = o.get("posSide")
        if side == "sell" and pos_side == "short":
            short += 1
        elif side == "buy" and pos_side == "long":
            long += 1
    return short, long


def classify_positions(positions_list):
    short_pos, long_pos = 0.0, 0.0
    for p in positions_list:
        if p.get("instId") != "ETH-USDT-SWAP":
            continue
        if str(p.get("lever")) != str(LEVERAGE):
            continue
        if p.get("mgnMode") != "isolated":
            continue
        sz = float(p.get("pos", "0") or "0")
        if p.get("posSide") == "short":
            short_pos += sz
        elif p.get("posSide") == "long":
            long_pos += sz
    return short_pos, long_pos


def ensure_api_ready():
    if not API_KEY or not SECRET or not PASSPHRASE:
        print("{" + '"error": "Missing API credentials in ' + ENV_FILE.replace("\\", "/") + '"' + "}")
        sys.exit(1)
