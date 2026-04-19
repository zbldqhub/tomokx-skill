#!/usr/bin/env python3
"""
Unified configuration module for tomokx trading system.
Loads environment variables and exposes all strategy constants.
"""
import os
import sys
import ssl

# Patch ssl.create_default_context to add OP_LEGACY_SERVER_CONNECT for OKX API compatibility
if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
    _orig_create_default_context = ssl.create_default_context
    def _patched_create_default_context(*args, **kwargs):
        ctx = _orig_create_default_context(*args, **kwargs)
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        return ctx
    ssl.create_default_context = _patched_create_default_context

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
ORDER_SIZE = 0.1  # fallback legacy constant
LEVERAGE = 10
DAILY_LOSS_LIMIT = -40
CANCEL_THRESHOLD = 100
DISTANCE_CAP = 80


def calc_order_size(equity, mark_px=None, total_exposure=0, volatility_1h=0):
    """Return order size (in contracts) based on account equity tier.
    
    ETH-USDT-SWAP contract size: 0.1 ETH per contract.
    Target margin per order: ~2.5-4% of equity.
    High volatility reduces size to limit per-trade loss.
    """
    if equity < 100:
        base = 0.05
    elif equity < 300:
        base = 0.1
    elif equity < 600:
        base = 0.2
    elif equity < 1000:
        base = 0.3
    else:
        base = 0.5

    # Density adjustment: shrink size as exposure grows
    if total_exposure >= 20:
        base *= 0.5
    elif total_exposure >= 14:
        base *= 0.75

    # Volatility adjustment: high vol → smaller size to avoid large SL hits
    if volatility_1h > 35:
        base *= 0.5
    elif volatility_1h > 25:
        base *= 0.75

    # Optional sanity-check against mark price margin
    if mark_px and mark_px > 0:
        margin_per_contract = mark_px * 0.1 / LEVERAGE
        target_margin = equity * 0.03
        calculated = target_margin / margin_per_contract
        base = min(base, calculated * 1.5)

    base = max(0.02, min(base, 1.0))
    return round(base, 2)

# Gap table by total exposure (v2026-04-16 dynamic: ATR-dominant with conservative floor)
def base_gap(total):
    # P2: 放宽 Gap 地板值，低暴露时给予更大呼吸空间
    if total <= 0:
        return 8
    elif total == 1:
        return 9
    elif total == 2:
        return 10
    elif total <= 4:
        return 11
    elif total <= 6:
        return 12
    elif total <= 10:
        return 13
    elif total <= 15:
        return 14
    else:
        return 16


def calc_atr(candles):
    """Calculate ATR(14) from list of OKX candle dicts [ts,o,h,l,c,vol,volCcy]."""
    if not candles or len(candles) < 15:
        return None
    trs = []
    for i in range(1, min(15, len(candles))):
        prev = candles[i - 1]
        curr = candles[i]
        try:
            h = float(curr[2])
            l = float(curr[3])
            pc = float(prev[4])
        except Exception:
            continue
        tr1 = h - l
        tr2 = abs(h - pc)
        tr3 = abs(l - pc)
        trs.append(max(tr1, tr2, tr3))
    if not trs:
        return None
    return sum(trs) / len(trs)


def calc_tp_sl_offset(volatility_1h, gap, atr=None):
    """Calculate TP/SL offsets.
    
    If atr (ATR from 1h candles) is provided, use ATR-based distances
    for better volatility adaptation. Fallback to gap-based when ATR
    is unavailable.
    """
    if atr is not None and atr > 0:
        tp = max(15, int(atr * 2.0))
        sl = max(20, int(atr * 2.5))
    else:
        tp = max(15, int(gap * 2.0))
        sl = max(20, int(gap * 2.5))
    # Reduced vol bonuses since ATR already captures volatility
    if volatility_1h > 35:
        tp += 5
        sl += 8
    elif volatility_1h > 25:
        tp += 3
        sl += 5
    elif volatility_1h > 15:
        tp += 1
        sl += 2
    return tp, sl


def load_env():
    """Load .env.trading into os.environ if not already present."""
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, "r", encoding="utf-8-sig") as f:
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
