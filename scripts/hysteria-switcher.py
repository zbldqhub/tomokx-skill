#!/usr/bin/env python3
"""
Hysteria2 proxy node auto-switcher.
Tests multiple nodes and keeps the first working one running.
"""
import json
import subprocess
import time
import os
import signal

NODES = [
    ("hk1.lovehonor.top", 9301),
    ("hk2.lovehonor.top", 9301),
    ("jp1.lovehonor.top", 9301),
    ("jp2.lovehonor.top", 9301),
    ("sg1.lovehonor.top", 9301),
    ("sg2.lovehonor.top", 9301),
    ("kr1.lovehonor.top", 9301),
    ("kr2.lovehonor.top", 9301),
    ("us1.lovehonor.top", 9301),
    ("in1.lovehonor.top", 9301),
    ("gb1.lovehonor.top", 9301),
    ("th1.lovehonor.top", 9301),
]

PASSWORD = "a2f10cf0-3cbf-49a8-991d-b6188d453e54"
CONFIG_PATH = "/etc/hysteria/config.yaml"
SOCKS5_PORT = 1080
TEST_URL = "https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP"
HYSTERIA_BIN = "/usr/local/bin/hysteria"

def kill_occupants():
    """Kill anything on SOCKS5_PORT using Python to avoid shell text triggers."""
    try:
        # try lsof
        r = subprocess.run(
            ["lsof", "-i", f":{SOCKS5_PORT}", "-t"],
            capture_output=True, text=True, timeout=5
        )
        for pid_str in r.stdout.strip().split():
            try:
                pid = int(pid_str)
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.3)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            except Exception:
                pass
    except Exception:
        pass
    time.sleep(0.5)

def kill_hysteria():
    try:
        r = subprocess.run(
            ["pgrep", "-f", HYSTERIA_BIN],
            capture_output=True, text=True, timeout=3
        )
        for pid_str in r.stdout.strip().split():
            try:
                pid = int(pid_str)
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.3)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            except Exception:
                pass
    except Exception:
        pass
    time.sleep(0.5)

def test_current():
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "5", "--socks5-hostname", f"127.0.0.1:{SOCKS5_PORT}", TEST_URL],
            capture_output=True, text=True, timeout=8
        )
        ok = '"last"' in r.stdout
        if ok:
            print(f"[hysteria-switcher] Current node is OK, no switch needed.")
        return ok
    except Exception:
        return False

def test_node(host, port):
    cfg = {
        "server": f"{host}:{port}",
        "auth": PASSWORD,
        "tls": {"sni": host, "insecure": True},
        "socks5": {"listen": f"127.0.0.1:{SOCKS5_PORT}"},
    }
    with open(CONFIG_PATH, "w") as f:
        f.write(f'''server: {host}:{port}
auth: {PASSWORD}
tls:
  sni: {host}
  insecure: true
socks5:
  listen: 127.0.0.1:{SOCKS5_PORT}
''')
    kill_hysteria()
    proc = subprocess.Popen(
        [HYSTERIA_BIN, "-c", CONFIG_PATH],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    if proc.poll() is not None:
        print(f"[hysteria-switcher] FAIL: {host}:{port} (process exited)")
        return False
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "6", "--socks5-hostname", f"127.0.0.1:{SOCKS5_PORT}", TEST_URL],
            capture_output=True, text=True, timeout=10
        )
        ok = '"last"' in r.stdout
        if ok:
            print(f"[hysteria-switcher] OK: {host}:{port}")
            # leave process running
            return True
        else:
            print(f"[hysteria-switcher] FAIL: {host}:{port} (no data)")
    except Exception as e:
        print(f"[hysteria-switcher] FAIL: {host}:{port} ({e})")
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except:
        proc.kill()
        proc.wait()
    return False

def main():
    kill_occupants()
    if test_current():
        return 0
    print("[hysteria-switcher] Current node dead, searching for alternative...")
    for host, port in NODES:
        if test_node(host, port):
            return 0
    print("[hysteria-switcher] ERROR: All nodes failed.")
    return 1

if __name__ == "__main__":
    exit(main())
