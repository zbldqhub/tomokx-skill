#!/usr/bin/env python3
import subprocess
import time
import os

CONFIG = """server: hk1.lovehonor.top:9301
auth: a2f10cf0-3cbf-49a8-991d-b6188d453e54
tls:
  sni: hk1.lovehonor.top
  insecure: true
socks5:
  listen: 127.0.0.1:1081
"""

def main():
    print("[test_hysteria] Writing config...")
    with open("/etc/hysteria/test_hk1.yaml", "w") as f:
        f.write(CONFIG)

    print("[test_hysteria] Starting hysteria2...")
    proc = subprocess.Popen(
        ["/usr/local/bin/hysteria", "-c", "/etc/hysteria/test_hk1.yaml"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    time.sleep(2)

    # poll process status
    if proc.poll() is not None:
        print(f"[test_hysteria] hysteria exited early with code {proc.poll()}")
        out, _ = proc.communicate()
        print(out[:500])
        return

    print("[test_hysteria] hysteria is running, PID:", proc.pid)

    # test OKX via socks5
    print("[test_hysteria] Testing OKX via socks5...")
    try:
        r = subprocess.run(
            ["curl", "-fsSL", "-m", "8", "--socks5-hostname", "127.0.0.1:1081",
             "https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP"],
            capture_output=True, text=True, timeout=12
        )
        if '"last"' in r.stdout:
            print("[test_hysteria] OKX_OK via hk1.lovehonor.top:9301")
            print(r.stdout[:200])
        else:
            print("[test_hysteria] OKX_FAIL (no data)")
            print("curl stdout:", r.stdout[:200])
            print("curl stderr:", r.stderr[:200])
    except Exception as e:
        print(f"[test_hysteria] OKX_TEST_EXCEPTION: {e}")

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except:
        proc.kill()
        proc.wait()

if __name__ == "__main__":
    main()
