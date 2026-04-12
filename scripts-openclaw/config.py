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
STOP_FILE = os.path.join(WORKSPACE, ".trading_stopped")

# Strategy constants
MAX_TOTAL = 20
MAX_PER_SIDE = 4
ORDER_SIZE = 0.1
LEVERAGE = 10
DAILY_LOSS_LIMIT = -40
CANCEL_THRESHOLD = 100
DISTANCE_CAP = 80

# Gap table by total exposure
def base_gap(total):
    if total <= 0:
        return 5
    elif total == 1:
        return 6
    elif total == 2:
        return 7
    elif total == 3:
        return 8
    elif total == 4:
        return 9
    elif total <= 6:
        return 10
    elif total <= 10:
        return 11
    elif total <= 15:
        return 12
    else:
        return 14


def calc_tp_sl_offset(volatility_1h):
    if volatility_1h < 5:
        return 12, 85
    elif volatility_1h < 10:
        return 20, 90
    elif volatility_1h < 15:
        return 28, 98
    elif volatility_1h < 25:
        return 38, 108
    else:
        return 45, 115


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


def ensure_api_ready():
    if not API_KEY or not SECRET or not PASSPHRASE:
        print("{" + '"error": "Missing API credentials in ' + ENV_FILE.replace("\\", "/") + '"' + "}")
        sys.exit(1)
