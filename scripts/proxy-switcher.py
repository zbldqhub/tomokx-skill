#!/usr/bin/env python3
"""
Proxy node auto-switcher for shadowsocks-libev.
Tests multiple nodes and updates config to the first working one.
"""
import json
import subprocess
import time
import os

NODES = [
    ("x2.good2026.com", 11011),
    ("x2.good2026.com", 11021),
    ("x2.good2026.com", 11031),
    ("x2.good2026.com", 11041),
    ("x2.good2026.com", 11051),
    ("x2.good2026.com", 11061),
]

# Get password from environment variable
PASSWORD = os.environ.get("SS_PASSWORD", "")
if not PASSWORD:
    print("[proxy-switcher] ERROR: SS_PASSWORD environment variable not set")
    print("[proxy-switcher] Please set it in ~/.openclaw/workspace/.env.trading")
    exit(1)

METHOD = "chacha20-ietf-poly1305"
CONFIG_PATH = "/etc/shadowsocks-libev/config.json"
PID_FILE = "/var/run/ss-local.pid"
TEST_URL = "https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP"

def kill_sslocal():
    try:
        with open(PID_FILE) as f:
            pid = f.read().strip()
        subprocess.run(["kill", pid], capture_output=True)
    except Exception:
        subprocess.run(["pkill", "-f", "ss-local"], capture_output=True)
    time.sleep(0.5)

def start_sslocal():
    subprocess.Popen([
        "/usr/bin/ss-local",
        "-c", CONFIG_PATH,
        "-l", "1080",
        "-f", PID_FILE
    ])
    time.sleep(1.5)

def test_node(host, port):
    cfg = {
        "server": host,
        "server_port": port,
        "local_port": 1080,
        "password": PASSWORD,
        "timeout": 60,
        "method": METHOD
    }
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f)
    kill_sslocal()
    start_sslocal()
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "8", "--socks5-hostname", "127.0.0.1:1080", TEST_URL],
            capture_output=True, text=True, timeout=12
        )
        ok = '"last"' in r.stdout
        if ok:
            print(f"[proxy-switcher] OK: {host}:{port}")
        else:
            print(f"[proxy-switcher] FAIL: {host}:{port} (no data)")
        return ok
    except Exception as e:
        print(f"[proxy-switcher] FAIL: {host}:{port} ({e})")
        return False

def main():
    # quick test current node first
    try:
        with open(CONFIG_PATH) as f:
            current = json.load(f)
        current_key = (current.get("server"), current.get("server_port"))
    except Exception:
        current_key = (None, None)

    # try current node
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "5", "--socks5-hostname", "127.0.0.1:1080", TEST_URL],
            capture_output=True, text=True, timeout=8
        )
        if '"last"' in r.stdout:
            print(f"[proxy-switcher] Current node {current_key[0]}:{current_key[1]} is OK, no switch needed.")
            return 0
    except Exception:
        pass

    print(f"[proxy-switcher] Current node dead, searching for alternative...")
    for host, port in NODES:
        if (host, port) == current_key:
            continue
        if test_node(host, port):
            return 0

    print("[proxy-switcher] ERROR: All nodes failed.")
    return 1

if __name__ == "__main__":
    exit(main())
