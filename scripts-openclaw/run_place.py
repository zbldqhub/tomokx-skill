import subprocess, os, sys, json

ENV_FILE = '/root/.openclaw/workspace/.env.trading'
env = os.environ.copy()
if os.path.exists(ENV_FILE):
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith('export '):
                line = line[7:]
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                v = v.strip().strip('"').strip("'")
                env[k] = v

def run_cmd(cmd_list):
    cmd_str = " ".join(cmd_list)
    full = f"source {ENV_FILE} && " + cmd_str
    r = subprocess.run(["bash", "-c", full], env=env, capture_output=True, text=True, timeout=20)
    return r.stdout or r.stderr or ""


cmd = sys.argv[1]
if cmd == "place":
    # args: instId tdMode side ordType sz px posSide tpTriggerPx slTriggerPx
    _, instId, tdMode, side, ordType, sz, px, posSide, tp, sl = sys.argv[:11]
    out = run_cmd([
        "okx", "swap", "place",
        f"--instId {instId}",
        f"--tdMode {tdMode}",
        f"--side {side}",
        f"--ordType {ordType}",
        f"--sz {sz}",
        f"--px={px}",
        f"--posSide {posSide}",
        f"--tpTriggerPx={tp}",
        "--tpOrdPx=-1",
        f"--slTriggerPx={sl}",
        "--slOrdPx=-1",
    ])
    print(out)
elif cmd == "cancel":
    # args: instId ordId
    _, instId, ordId = sys.argv[:4]
    out = run_cmd([
        "okx", "swap", "cancel",
        f"--instId {instId}",
        f"--ordId {ordId}",
    ])
    print(out)
else:
    print("unknown cmd")
