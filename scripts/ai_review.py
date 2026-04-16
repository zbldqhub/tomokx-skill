#!/usr/bin/env python3
"""
AI Review Engine for tomokx.
Reads calc_plan output and market/strategy/exposure/recommendation data,
applies SKILL.md rules via rules.json, and outputs the finalized plan.
Supports: hard rules, LLM edge-case gate, and dynamic sizing.
Auto-detects LLM backend: openclaw gateway -> kimi CLI -> conservative fallback.
"""
import json
import sys
import os
import urllib.request
import subprocess
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MAX_TOTAL, MAX_PER_SIDE, ORDER_SIZE


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_rules():
    rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")
    if os.path.exists(rules_path):
        return load_json(rules_path)
    return {}


RULES = load_rules()
HARDS = RULES.get("hard_rules", {})
YELLOW_CFG = RULES.get("yellow_rules", [])
DYNAMIC = RULES.get("dynamic_sizing", {})


def is_heavy_side(pos_side, exposure):
    long_total = exposure.get("long_orders", 0) + exposure.get("long_pos_units", 0)
    short_total = exposure.get("short_orders", 0) + exposure.get("short_pos_units", 0)
    if pos_side == "long" and long_total > short_total:
        return True
    if pos_side == "short" and short_total > long_total:
        return True
    return False


def get_expansion_type(p, reasoning_side):
    exp = reasoning_side.get("expansion_type", "")
    if exp:
        return exp
    existing = reasoning_side.get("existing", [])
    if not existing:
        return "scratch"
    px = float(p.get("px", 0))
    pos_side = p.get("posSide")
    if pos_side == "long":
        return "inner" if px > max(existing) else "outer"
    elif pos_side == "short":
        return "inner" if px < min(existing) else "outer"
    return "unknown"


def funding_aligned(pos_side, funding_bias):
    if funding_bias in ("neutral", ""):
        return True
    if pos_side == "long" and funding_bias == "long_favored":
        return True
    if pos_side == "short" and funding_bias == "short_favored":
        return True
    return False


def calc_dynamic_sz(base_sz, context):
    volatility = context.get("volatility_1h", 0)
    confidence = context.get("confidence", 0.7)
    daily_pnl = context.get("daily_pnl", 0)
    consecutive_losses = context.get("consecutive_losses", 0)
    recommendation = context.get("recommendation", "proceed")
    alignment = context.get("alignment", "weak")

    sz = base_sz

    if volatility > 25:
        sz *= DYNAMIC.get("volatility_above_25", 0.5)
    elif volatility > 15:
        sz *= DYNAMIC.get("volatility_above_15", 0.75)

    if confidence > 0.85 and alignment == "strong":
        sz = min(base_sz * DYNAMIC.get("confidence_above_0_85_strong", 1.5), DYNAMIC.get("max_order_size", 0.2))
    elif confidence < 0.5:
        sz *= DYNAMIC.get("confidence_below_0_5", 0.5)

    if daily_pnl < -20:
        sz *= DYNAMIC.get("daily_pnl_below_minus_20", 0.5)
    elif daily_pnl < -30:
        sz *= DYNAMIC.get("daily_pnl_below_minus_30", 0.25)

    if consecutive_losses >= 3:
        sz *= DYNAMIC.get("consecutive_losses_above_3", 0.5)

    if recommendation in ("pause", "cancel_only"):
        sz *= DYNAMIC.get("recommendation_pause", 0.25)
    elif recommendation == "reduce_exposure":
        sz *= DYNAMIC.get("recommendation_reduce_exposure", 0.75)

    return max(DYNAMIC.get("min_order_size", 0.01), round(sz, 2))


def read_consecutive_losses():
    path = os.path.join(os.path.expanduser("~/.openclaw/workspace"), "decisions.jsonl")
    if not os.path.exists(path):
        return 0
    losses = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if "outcome_pnl" in entry:
                    if entry["outcome_pnl"] < 0:
                        losses += 1
                    else:
                        break
            except Exception:
                continue
    except Exception:
        pass
    return losses


def review_single(p, reasoning_side, context):
    px = float(p.get("px", 0))
    tp = float(p.get("tpTriggerPx", 0))
    sl = float(p.get("slTriggerPx", 0))
    pos_side = p.get("posSide")
    current_price = context["current_price"]
    gap = context["gap"]
    alignment = context["alignment"]
    imbalance = context["imbalance"]
    exposure = context["exposure"]
    recommendation = context["recommendation"]
    funding_bias = context.get("funding_bias", "neutral")

    notes = []
    delete = False
    yellow = False

    exp_type = get_expansion_type(p, reasoning_side)
    heavy = is_heavy_side(pos_side, exposure)
    existing_count = reasoning_side.get("existing_count", 0)
    target = reasoning_side.get("target", 0)
    distance = abs(px - current_price)

    tp_zone = HARDS.get("tp_forbidden_zone", 3.0)
    outer_mult = HARDS.get("distance_cap_outer_multiplier", 2.0)

    # TP forbidden zone
    tp_distance_from_market = abs(tp - current_price)
    if tp_distance_from_market < tp_zone:
        delete = True
        notes.append(f"TP {tp} is only {tp_distance_from_market:.2f} USDT from current price (< {tp_zone}), noise risk")

    # Heavy outer funding alignment
    if heavy and exp_type == "outer":
        if alignment != "strong" or not funding_aligned(pos_side, funding_bias):
            delete = True
            notes.append(f"heavy outer blocked: alignment={alignment}, funding={funding_bias}, pos={pos_side}")

    if alignment in ("mixed", "weak") and heavy and exp_type == "outer":
        delete = True
        notes.append(f"alignment={alignment} + heavy side outer -> delete")

    if imbalance >= 3 and heavy and exp_type == "outer":
        delete = True
        notes.append(f"imbalance={imbalance} >= 3 + heavy side outer -> delete")

    if existing_count > target and exp_type == "outer":
        delete = True
        notes.append(f"existing_count({existing_count}) > target({target}) + outer -> delete")

    if distance > gap * outer_mult and exp_type == "outer":
        delete = True
        notes.append(f"distance {distance:.2f} > gap*{outer_mult}({gap*outer_mult}) + outer -> delete")

    if pos_side == "long":
        if not (tp > px and sl < px):
            delete = True
            notes.append("Long TP/SL validation failed")
    elif pos_side == "short":
        if not (tp < px and sl > px):
            delete = True
            notes.append("Short TP/SL validation failed")

    tp_distance = abs(tp - px)
    if tp_distance < gap:
        notes.append(f"TP distance {tp_distance:.2f} < gap({gap}), risky")
        delete = True

    side_orders = exposure.get(f"{pos_side}_orders", 0)
    side_pos = exposure.get(f"{pos_side}_pos_units", 0)
    if side_orders + side_pos + 1 > MAX_PER_SIDE:
        delete = True
        notes.append(f"per-side max {MAX_PER_SIDE} would be exceeded")

    total = exposure.get("total", 0)
    if total >= MAX_TOTAL:
        delete = True
        notes.append(f"total exposure {total} >= {MAX_TOTAL}")

    # Yellow rules
    if not delete:
        for y in YELLOW_CFG:
            cond = y.get("condition", "")
            triggered = False
            if cond == "recommendation=pause AND expansion_type!=outer" and recommendation in ("pause", "cancel_only") and exp_type in ("inner", "scratch"):
                triggered = True
            elif cond == "recommendation=reduce_exposure AND expansion_type=outer" and recommendation == "reduce_exposure" and exp_type == "outer":
                triggered = True
            elif cond == "imbalance>=2 AND heavy_side AND expansion_type=inner" and imbalance >= 2 and heavy and exp_type == "inner":
                triggered = True
            elif cond == "expansion_type=inner AND distance>gap*1.5" and exp_type == "inner" and distance > gap * 1.5:
                triggered = True

            if triggered:
                yellow = True
                notes.append(f"YELLOW: {y.get('description', cond)}; needs LLM judgment")
                break

    return delete, yellow, notes, exp_type, heavy, distance


def apply_cross_placement_rules(placements_info, context):
    alignment = context["alignment"]

    light_inners = [info for info in placements_info if info["exp_type"] == "inner" and not info["heavy"] and not info["delete"]]
    heavy_outers = [info for info in placements_info if info["exp_type"] == "outer" and info["heavy"] and not info["delete"]]
    if heavy_outers and light_inners:
        for info in heavy_outers:
            info["delete"] = True
            info["yellow"] = False
            info["notes"].append("heavy outer + light inner exists -> delete heavy outer")

    outers = [info for info in placements_info if info["exp_type"] == "outer" and not info["delete"]]
    if len(outers) >= 2:
        sides = {info["pos_side"] for info in outers}
        if len(sides) >= 2:
            if alignment in ("mixed", "weak"):
                for info in outers:
                    info["delete"] = True
                    info["yellow"] = False
                    info["notes"].append("both sides outer + mixed/weak alignment -> delete outer")
            else:
                outers.sort(key=lambda x: x["distance"])
                for info in outers[1:]:
                    info["delete"] = True
                    info["yellow"] = False
                    info["notes"].append("both sides outer -> keep only closer one, delete farther")

    return placements_info


# --- LLM Backends ---

def load_openclaw_token():
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("gateway", {}).get("auth", {}).get("token", "")
        except Exception:
            pass
    return os.environ.get("OPENCLAW_TOKEN", "")


def call_openclaw_gateway(prompt):
    token = load_openclaw_token()
    if not token:
        raise RuntimeError("openclaw token not found")

    req = urllib.request.Request(
        "http://127.0.0.1:18789/v1/chat/completions",
        data=json.dumps({
            "model": "kimi-code",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 200,
        }).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def call_kimi_cli(prompt):
    candidates = [
        os.path.expanduser("~/AppData/Roaming/Code/User/globalStorage/moonshot-ai.kimi-code/bin/kimi/kimi.exe"),
        shutil.which("kimi"),
    ]
    exe = None
    for c in candidates:
        if c and os.path.exists(c):
            exe = c
            break
    if not exe:
        raise RuntimeError("kimi.exe not found")

    r = subprocess.run(
        [exe, "--print", "--quiet", "--yolo", "--prompt", prompt],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
    )
    return r.stdout.strip()


def detect_llm_backend():
    env = os.environ.get("TOMOKX_LLM_BACKEND", "").lower()
    if env == "openclaw":
        return "openclaw"
    if env == "kimi":
        return "kimi"
    # Auto-detect
    try:
        req = urllib.request.Request("http://127.0.0.1:18789/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return "openclaw"
    except Exception:
        pass
    return "kimi"


def call_llm(prompt):
    backend = detect_llm_backend()
    if backend == "openclaw":
        try:
            return call_openclaw_gateway(prompt)
        except Exception:
            pass
    return call_kimi_cli(prompt)


def build_llm_prompt(p, info, context, plan):
    px = p.get("px")
    tp = p.get("tpTriggerPx")
    sl = p.get("slTriggerPx")
    pos_side = p.get("posSide")
    side = p.get("side")
    tp_zone = HARDS.get("tp_forbidden_zone", 3.0)
    return f"""You are the AI arbiter for a crypto grid trading bot (ETH-USDT-SWAP).
Rules:
- Never open if recommendation=pause without explicit justification.
- Never add heavy-side outer expansion unless trend_alignment=strong AND funding_rate aligns.
- Never place TP within {tp_zone} USDT of current price.
- Inner expansions on the light side are preferred.

Current context:
- Price: {context['current_price']}
- Trend: {context['trend']}, alignment: {context['alignment']}
- Recommendation: {context['recommendation']}
- Imbalance: {context['imbalance']}
- Volatility 1h: {context.get('volatility_1h', 'N/A')}
- Funding bias: {context.get('funding_bias', 'neutral')}
- Heavy side: {'yes' if info['heavy'] else 'no'}

Proposed order:
- Side: {side}+{pos_side}
- Price: {px}, TP: {tp}, SL: {sl}
- Expansion type: {info['exp_type']}
- Distance from current price: {info['distance']:.2f} USDT
- Flags: {', '.join(info['notes'])}

Respond with exactly one line: either "KEEP: <one-sentence reason>" or "DELETE: <one-sentence reason>".
"""


def llm_judge(placements_info, context, plan):
    yellows = [info for info in placements_info if info["yellow"] and not info["delete"]]
    if not yellows:
        return placements_info

    for info in yellows:
        p = info["placement"]
        prompt = build_llm_prompt(p, info, context, plan)

        try:
            decision = call_llm(prompt)
            if "keep" in decision.lower():
                info["notes"].append(f"LLM decision: KEEP -> {decision.strip()}")
                info["yellow"] = False
            else:
                info["delete"] = True
                info["yellow"] = False
                info["notes"].append(f"LLM decision: DELETE -> {decision.strip()}")
        except Exception as e:
            info["notes"].append(f"LLM call failed ({e}), falling back to conservative")
            if context["alignment"] == "strong" and info["exp_type"] in ("inner", "scratch"):
                info["notes"].append("LLM fallback: alignment=strong + non-outer -> KEEP")
                info["yellow"] = False
            else:
                info["delete"] = True
                info["yellow"] = False
                info["notes"].append("LLM fallback: conservative DELETE")

    return placements_info


def main():
    if len(sys.argv) < 6:
        print("Usage: python3 ai_review.py <plan.json> <market.json> <exposure.json> <strategy.json> <rec.json>")
        sys.exit(1)

    plan_path = sys.argv[1]
    market_path = sys.argv[2]
    exposure_path = sys.argv[3]
    strategy_path = sys.argv[4]
    rec_path = sys.argv[5]

    plan = load_json(plan_path)
    market = load_json(market_path)
    exposure = load_json(exposure_path)
    strategy = load_json(strategy_path)
    rec = load_json(rec_path) if os.path.exists(rec_path) else {}

    current_price = float(market.get("last", 0))
    gap = float(strategy.get("adjusted_gap", 10))
    alignment = strategy.get("trend_alignment", "weak")
    imbalance = strategy.get("imbalance_score", 0)
    recommendation = rec.get("recommendation", "proceed")
    trend = strategy.get("trend", "sideways")
    funding_bias = strategy.get("funding_bias", "neutral")
    volatility = market.get("volatility_1h", 0)
    confidence = rec.get("confidence", 0.7)
    daily_pnl = market.get("daily_pnl", 0)

    context = {
        "current_price": current_price,
        "gap": gap,
        "alignment": alignment,
        "imbalance": imbalance,
        "exposure": exposure,
        "recommendation": recommendation,
        "trend": trend,
        "funding_bias": funding_bias,
        "volatility_1h": volatility,
        "confidence": confidence,
        "daily_pnl": daily_pnl,
        "consecutive_losses": read_consecutive_losses(),
    }

    reasoning = plan.get("reasoning", {})
    placements = plan.get("placements", [])

    placements_info = []
    for p in placements:
        pos_side = p.get("posSide")
        reasoning_side = reasoning.get("long" if pos_side == "long" else "short", {})
        delete, yellow, notes, exp_type, heavy, distance = review_single(p, reasoning_side, context)
        placements_info.append({
            "placement": p,
            "delete": delete,
            "yellow": yellow,
            "notes": notes,
            "exp_type": exp_type,
            "heavy": heavy,
            "distance": distance,
            "pos_side": pos_side,
        })

    placements_info = apply_cross_placement_rules(placements_info, context)
    placements_info = llm_judge(placements_info, context, plan)

    final_placements = []
    ai_actions = []
    for info in placements_info:
        p = info["placement"]
        if info["delete"]:
            ai_actions.append(
                f"Deleted {p['side']}+{p['posSide']} @ {p['px']} ({info['exp_type']}): " + "; ".join(info["notes"])
            )
        else:
            base_sz = float(p.get("sz", ORDER_SIZE))
            new_sz = calc_dynamic_sz(base_sz, context)
            if new_sz != base_sz:
                p["sz"] = str(new_sz)
                info["notes"].append(f"Dynamic sizing: {base_sz} -> {new_sz}")
            final_placements.append(p)
            if info["notes"]:
                ai_actions.append(
                    f"Kept {p['side']}+{p['posSide']} @ {p['px']} with notes: " + "; ".join(info["notes"])
                )

    cancellations = plan.get("cancellations", [])
    if cancellations:
        ai_actions.append(f"Preserved cancellation of {len(cancellations)} far order(s)")

    summary = plan.get("summary", {})
    orig_actions = summary.get("actions", "")
    if ai_actions:
        summary["actions"] = f"[AI] {orig_actions} | " + " | ".join(ai_actions)
    else:
        summary["actions"] = f"[AI] {orig_actions}"

    final_plan = {
        "cancellations": cancellations,
        "placements": final_placements,
        "original_placements": placements,
        "ai_review": {
            "original_placements_count": len(placements),
            "final_placements_count": len(final_placements),
            "deleted_count": len(placements) - len(final_placements),
            "alignment": alignment,
            "imbalance": imbalance,
            "recommendation": recommendation,
            "ai_actions": ai_actions,
        },
        "summary": summary,
    }

    if reasoning:
        final_plan["reasoning"] = reasoning

    print(json.dumps(final_plan, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
