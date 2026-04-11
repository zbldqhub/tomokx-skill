#!/usr/bin/env python3
"""
Tomokx OpenClaw Trading Bot - Standalone script version.
Runs the ETH-USDT-SWAP grid trading strategy without AI inference.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw" / "workspace"
ENV_FILE = WORKSPACE / ".env.trading"
STOP_FILE = WORKSPACE / ".trading_stopped"
LOG_FILE = WORKSPACE / "auto_trade.log"
BILLS_SCRIPT = WORKSPACE / "scripts" / "get_bills.py"
MARKET_SCRIPT = WORKSPACE / "scripts" / "eth_market_analyzer.py"

ORDERS_MAX = 20
TOTAL_MAX = 20
DAILY_LOSS_LIMIT = -40.0
MAX_NEW_PER_CYCLE = 5
PER_SIDE_MAX = 4
PRICE_FAR_THRESHOLD = 100.0

QQ_TARGET = "7DA38124D31C47BB7406B6020C5067FC"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def notify_qq(text):
    try:
        result = subprocess.run(
            [
                "openclaw", "message", "send",
                "--channel", "qqbot",
                "-t", QQ_TARGET,
                "-m", text,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        log(f"[INFO] QQ notify output: {result.stdout.strip()}")
    except Exception as e:
        log(f"[ERROR] Failed to send QQ message: {e}")


def run_cmd(cmd, retries=3, sleep=2):
    """Run a shell command with retry."""
    # Ensure bash is used when source is needed
    if "source " in cmd and not cmd.startswith("bash -c"):
        cmd = f'bash -c "{cmd.replace(chr(34), chr(92)+chr(34))}"'
    for attempt in range(retries):
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return result.stdout
            else:
                err = result.stderr.strip() or result.stdout.strip()
                log(f"[WARN] Command failed (attempt {attempt+1}/{retries}): {err}")
        except Exception as e:
            log(f"[WARN] Command exception (attempt {attempt+1}/{retries}): {e}")
        if attempt < retries - 1:
            time.sleep(sleep)
    return None


def api_test():
    cmd = (
        "source ~/.openclaw/workspace/.env.trading && "
        "curl -s --max-time 15 https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP "
        "2>/dev/null | grep last"
    )
    out = run_cmd(cmd, retries=3, sleep=2)
    if out is None or '"last"' not in out:
        return False
    return True


def check_stop_protection():
    today_str = datetime.now().strftime("%Y-%m-%d")
    if STOP_FILE.exists():
        content = STOP_FILE.read_text(encoding="utf-8").strip()
        # If content is a date older than today, reset to 0
        if "-" in content and len(content) == 10:
            if content < today_str:
                STOP_FILE.write_text("0", encoding="utf-8")
                return 0
        try:
            val = int(content)
            if val >= 3:
                return val
            return val
        except ValueError:
            STOP_FILE.write_text("0", encoding="utf-8")
            return 0
    else:
        STOP_FILE.write_text("0", encoding="utf-8")
        return 0


def check_daily_loss():
    out = run_cmd(f"python3 {BILLS_SCRIPT} --today")
    if out is None:
        return None  # unknown
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if data.get("code") != "0":
        return None
    rows = data.get("data", [])
    subtypes = {"4", "6", "110", "111", "112"}
    total_pnl = 0.0
    for r in rows:
        if r.get("instId") != "ETH-USDT-SWAP":
            continue
        if str(r.get("subType", "")) in subtypes:
            pnl = float(r.get("pnl", "0") or 0)
            total_pnl += pnl
    return total_pnl


def fetch_market_snapshot():
    out = run_cmd(f"python3 {MARKET_SCRIPT}")
    if out is None:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def okx_place(side, pos_side, px, tp, sl):
    cmd = (
        f"source {ENV_FILE} && "
        f"okx swap place --instId ETH-USDT-SWAP --tdMode isolated --side {side} "
        f"--ordType limit --sz 0.1 --px={px} --posSide {pos_side} "
        f"--tpTriggerPx={tp} --tpOrdPx=-1 --slTriggerPx={sl} --slOrdPx=-1"
    )
    out = run_cmd(cmd, retries=2, sleep=2)
    return out


def okx_cancel(ord_id):
    cmd = (
        f"source {ENV_FILE} && "
        f"okx swap cancel --instId ETH-USDT-SWAP --ordId {ord_id}"
    )
    out = run_cmd(cmd, retries=2, sleep=2)
    return out


def round_px(px):
    return round(float(px), 2)


def determine_trend(change24h_pct, trend_1h, recent_1h_pct):
    # Use both 24h and 1h; if they strongly disagree, trust 1h
    if change24h_pct > 2 and trend_1h == "bullish":
        return "Bullish"
    if change24h_pct < -2 and trend_1h == "bearish":
        return "Bearish"
    if (change24h_pct > 2 and trend_1h == "bearish") or (
        change24h_pct < -2 and trend_1h == "bullish"
    ):
        return "Sideways"
    # Default: sideways when near zero
    if abs(change24h_pct) <= 2:
        return "Sideways"
    # Fallback
    return "Sideways"


def base_gap(total):
    table = [
        (0, 5), (1, 6), (2, 7), (3, 8), (4, 9),
        (5, 10), (6, 10), (7, 11), (11, 12), (16, 14),
    ]
    for threshold, g in table:
        if total <= threshold:
            return g
    return 14


def adjust_gap(gap, volatility_1h, spread):
    # volatility adjustments
    if volatility_1h < 8:
        gap = max(5, gap - 1)
    elif 8 <= volatility_1h <= 15:
        pass
    elif 15 < volatility_1h <= 25:
        gap += 2
    elif volatility_1h > 25:
        gap += 4
    if spread > 0.5:
        gap += 1
    return gap


def tp_offset(volatility_1h):
    if volatility_1h < 5:
        return 12  # middle of 8-15
    elif volatility_1h < 10:
        return 20  # middle of 15-25
    elif volatility_1h < 15:
        return 28  # middle of 20-35
    elif volatility_1h < 25:
        return 38  # middle of 30-45
    else:
        return 45  # middle of 40-50


def sl_offset(volatility_1h):
    if volatility_1h < 8:
        return 85
    elif volatility_1h < 15:
        return 95
    elif volatility_1h < 25:
        return 110
    else:
        return 120


def main():
    actions = []
    new_placed = 0
    cancelled = 0

    # Step 0: API test
    if not api_test():
        msg = "🛑 API 连通性测试失败，交易中止"
        log(msg)
        notify_qq(msg)
        return

    # Step 1: Stop protection
    stop_count = check_stop_protection()
    if stop_count >= 3:
        msg = f"🛑 交易已暂停\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n⚠️ 连续止损次数: {stop_count}\n⏸️ 交易已自动暂停，请检查策略\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log(msg)
        notify_qq(msg)
        return

    # Step 1.2: Daily loss
    daily_pnl = check_daily_loss()
    if daily_pnl is not None and daily_pnl < DAILY_LOSS_LIMIT:
        msg = f"⚠️ 日亏损限制触发\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📉 今日亏损: {daily_pnl:.2f} USDT\n🚫 已停止交易，明日自动恢复\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log(msg)
        notify_qq(msg)
        return

    # Step 1.5: Market snapshot
    snapshot = fetch_market_snapshot()
    if snapshot is None:
        msg = "🛑 市场数据获取失败，交易中止"
        log(msg)
        notify_qq(msg)
        return

    market = snapshot.get("market", {})
    hourly = snapshot.get("hourly_stats", {})
    orders = snapshot.get("orders", [])
    positions = snapshot.get("positions", [])

    current_price = float(market.get("last", 0))
    change24h_pct = float(market.get("change24h_pct", 0))
    bid_px = float(market.get("bidPx", current_price))
    ask_px = float(market.get("askPx", current_price))
    spread = round_px(ask_px - bid_px)

    volatility_1h = float(hourly.get("volatility_1h", 0))
    trend_1h = hourly.get("trend_1h", "sideways")
    recent_1h_pct = float(hourly.get("recent_change_1h_pct", 0))

    trend = determine_trend(change24h_pct, trend_1h, recent_1h_pct)

    # Step 3/4/5: Count orders and positions
    live_orders = []
    for o in orders:
        if o.get("instId") != "ETH-USDT-SWAP":
            continue
        if o.get("type") != "limit" and o.get("ordType") != "limit":
            continue
        if float(o.get("sz", 0)) != 0.1:
            continue
        if o.get("state") != "live":
            continue
        side = o.get("side", "")
        pos_side = o.get("posSide", "")
        if (side == "sell" and pos_side == "short") or (side == "buy" and pos_side == "long"):
            live_orders.append(o)

    short_orders = [o for o in live_orders if o["posSide"] == "short"]
    long_orders = [o for o in live_orders if o["posSide"] == "long"]

    short_pos_size = sum(float(p.get("pos", 0)) for p in positions if p.get("posSide") == "short" and p.get("instId") == "ETH-USDT-SWAP")
    long_pos_size = sum(float(p.get("pos", 0)) for p in positions if p.get("posSide") == "long" and p.get("instId") == "ETH-USDT-SWAP")

    short_orders_count = len(short_orders)
    long_orders_count = len(long_orders)
    short_pos_units = round(short_pos_size / 0.1, 1)
    long_pos_units = round(long_pos_size / 0.1, 1)

    orders_count = short_orders_count + long_orders_count
    positions_count = short_pos_units + long_pos_units
    total = round(orders_count + positions_count, 1)

    # Step 6: Cancel far orders
    for o in live_orders:
        px = float(o.get("px", 0))
        if abs(px - current_price) > PRICE_FAR_THRESHOLD:
            out = okx_cancel(o.get("ordId"))
            if out is not None:
                actions.append(f"Cancelled far order {o.get('ordId')} @ {px}")
                cancelled += 1
                if o["posSide"] == "short":
                    short_orders_count -= 1
                else:
                    long_orders_count -= 1
            else:
                actions.append(f"Failed to cancel far order {o.get('ordId')} @ {px}")

    # Step 7: Target distribution
    target_map = {"Bullish": (2, 1), "Bearish": (1, 2), "Sideways": (1, 2)}
    target_long, target_short = target_map.get(trend, (1, 2))

    # Step 8: Manage orders
    if total < TOTAL_MAX and orders_count < ORDERS_MAX:
        gap = base_gap(int(total))
        gap = adjust_gap(gap, volatility_1h, spread)

        remaining_capacity = int(TOTAL_MAX - total)
        need_orders = min(ORDERS_MAX - orders_count, remaining_capacity, MAX_NEW_PER_CYCLE)

        # Replenish if below 10
        if orders_count < 10 and total < TOTAL_MAX:
            replenish_count = min(10 - orders_count, remaining_capacity, MAX_NEW_PER_CYCLE)
            need_orders = max(need_orders, replenish_count)

        need_orders = max(0, need_orders)

        planned_prices = []
        placed_this_cycle = 0

        def price_conflict(px, side):
            existing = [float(o["px"]) for o in (short_orders if side == "short" else long_orders)]
            for ep in existing + planned_prices:
                if abs(ep - px) < gap:
                    return True
            return False

        def place_one(side, pos_side, px):
            nonlocal placed_this_cycle, new_placed
            px = round_px(px)
            offset_tp = tp_offset(volatility_1h)
            offset_sl = sl_offset(volatility_1h)
            if pos_side == "long":
                tp = round_px(px + offset_tp)
                sl = round_px(px - offset_sl)
            else:
                tp = round_px(px - offset_tp)
                sl = round_px(px + offset_sl)
            out = okx_place(side, pos_side, px, tp, sl)
            if out is not None:
                actions.append(f"Placed {pos_side} @ {px} TP={tp} SL={sl}")
                placed_this_cycle += 1
                new_placed += 1
                planned_prices.append(px)
                return True
            else:
                actions.append(f"Failed to place {pos_side} @ {px}")
                return False

        # Ensure target ratio first
        while (
            long_orders_count < target_long
            and placed_this_cycle < need_orders
            and long_orders_count < PER_SIDE_MAX
            and total + placed_this_cycle < TOTAL_MAX
        ):
            if long_orders_count == 0:
                px = current_price * 0.998
            else:
                min_long = min(float(o["px"]) for o in long_orders)
                px = min_long - gap
            while price_conflict(px, "long"):
                px -= gap
            if place_one("buy", "long", px):
                long_orders_count += 1

        while (
            short_orders_count < target_short
            and placed_this_cycle < need_orders
            and short_orders_count < PER_SIDE_MAX
            and total + placed_this_cycle < TOTAL_MAX
        ):
            if short_orders_count == 0:
                px = current_price * 1.002
            else:
                max_short = max(float(o["px"]) for o in short_orders)
                px = max_short + gap
            while price_conflict(px, "short"):
                px += gap
            if place_one("sell", "short", px):
                short_orders_count += 1

        # Then fill remaining capacity preferring the side with fewer total
        while placed_this_cycle < need_orders and total + placed_this_cycle < TOTAL_MAX:
            long_total = long_orders_count + long_pos_units
            short_total = short_orders_count + short_pos_units

            if long_orders_count < PER_SIDE_MAX and short_orders_count < PER_SIDE_MAX:
                if long_total <= short_total:
                    side_choice = "long"
                else:
                    side_choice = "short"
            elif long_orders_count < PER_SIDE_MAX:
                side_choice = "long"
            elif short_orders_count < PER_SIDE_MAX:
                side_choice = "short"
            else:
                break

            if side_choice == "long":
                if long_orders_count == 0:
                    px = current_price * 0.998
                else:
                    min_long = min(float(o["px"]) for o in long_orders)
                    px = min_long - gap
                while price_conflict(px, "long"):
                    px -= gap
                if place_one("buy", "long", px):
                    long_orders_count += 1
                else:
                    break
            else:
                if short_orders_count == 0:
                    px = current_price * 1.002
                else:
                    max_short = max(float(o["px"]) for o in short_orders)
                    px = max_short + gap
                while price_conflict(px, "short"):
                    px += gap
                if place_one("sell", "short", px):
                    short_orders_count += 1
                else:
                    break

    # Step 8.5: Update stop-loss counter
    # Check for new negative PnL close events since last run
    # For simplicity in script mode, we read today's bills and compare timestamps.
    # We use the file mtime of STOP_FILE or a companion timestamp file.
    # Here we do a simplified check: if daily_pnl decreased since last run.
    # Because persistent state across runs needs a file; we store last-check-ts.
    LAST_TS_FILE = WORKSPACE / ".trading_last_ts"
    now_ts = int(datetime.now().timestamp() * 1000)
    last_ts = 0
    if LAST_TS_FILE.exists():
        try:
            last_ts = int(LAST_TS_FILE.read_text().strip())
        except ValueError:
            last_ts = 0

    bills_out = run_cmd(f"python3 {BILLS_SCRIPT} --today")
    new_stop_events = 0
    if bills_out:
        try:
            bills_data = json.loads(bills_out)
            for r in bills_data.get("data", []):
                if r.get("instId") != "ETH-USDT-SWAP":
                    continue
                if str(r.get("subType", "")) not in {"4", "6", "110", "111", "112"}:
                    continue
                pnl = float(r.get("pnl", "0") or 0)
                ts = int(r.get("ts", 0))
                if pnl < 0 and ts > last_ts:
                    new_stop_events += 1
        except Exception:
            pass

    if new_stop_events > 0:
        stop_count = check_stop_protection()
        stop_count += new_stop_events
        STOP_FILE.write_text(str(stop_count), encoding="utf-8")
        log(f"[INFO] Incremented stop count by {new_stop_events} to {stop_count}")
        actions.append(f"连续止损次数更新: {stop_count}")
        if stop_count >= 3:
            msg = f"🛑 交易已暂停\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n⚠️ 连续止损次数: {stop_count}\n⏸️ 交易已自动暂停，请检查策略\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            log(msg)
            notify_qq(msg)
            LAST_TS_FILE.write_text(str(now_ts), encoding="utf-8")
            return

    LAST_TS_FILE.write_text(str(now_ts), encoding="utf-8")

    if not actions:
        actions.append("无交易操作")

    # Step 10: Summary
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary_log = (
        f"[{ts_str}] | tomokx | Trading Cycle Summary\n"
        f"- Market Trend: {trend}\n"
        f"- Current Price: {current_price} USDT\n"
        f"- Orders: {orders_count} live, {new_placed} new placed\n"
        f"- Positions: {positions_count} open\n"
        f"- Total Exposure: {total}/20\n"
        f"- Actions: {actions}"
    )
    log(summary_log)

    actions_text = "\n".join(f"• {a}" for a in actions)
    notify_msg = (
        f"📊 ETH Trader 执行完成\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ 时间: {ts_str}\n"
        f"📈 趋势: {trend}\n"
        f"💰 价格: {current_price} USDT\n"
        f"📋 挂单: {orders_count}/20\n"
        f"💼 持仓: {positions_count}\n"
        f"📊 总暴露: {total}/20\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 操作记录:\n"
        f"{actions_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    notify_qq(notify_msg)


if __name__ == "__main__":
    main()
