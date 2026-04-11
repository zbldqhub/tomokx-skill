#!/usr/bin/env bash
set -uo pipefail

SUB_URL='https://abc.xhonor.top:9066/v2b/ant/api/v1/client/subscribe?token=0d9c28410352e569a2b3f19c00ddc9bc'
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

curl -fsSL "$SUB_URL" | base64 -d | grep -oE '@[^#]+' | sed 's/^@//' | sort -u > "$TMPDIR/nodes.txt"

echo "=== TCP connect test (timeout 5s) ==="
while IFS= read -r node; do
  (
    host="${node%:*}"
    port="${node#*:}"
    if timeout 5 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null; then
      echo "[TCP_OK]   $node"
    else
      echo "[TCP_FAIL] $node"
    fi
  ) &
done < "$TMPDIR/nodes.txt"
wait

echo ""
echo "=== Socks5 -> OKX test via ss-local (sample: first 6 nodes, timeout 10s) ==="
count=0
while IFS= read -r node; do
  count=$((count+1))
  [ $count -gt 6 ] && break
  host="${node%:*}"
  port="${node#*:}"
  ss-local -s "$host" -p "$port" -k "a2f10cf0-3cbf-49a8-991d-b6188d453e54" -m "chacha20-ietf-poly1305" -l 10800 &
  SS_PID=$!
  sleep 1
  if curl -fsSL -m 10 --socks5-hostname 127.0.0.1:10800 https://www.okx.com >/dev/null 2>&1; then
    echo "[OKX_OK]   $node"
  else
    echo "[OKX_FAIL] $node"
  fi
  kill $SS_PID 2>/dev/null
  wait $SS_PID 2>/dev/null
  sleep 0.5
done < "$TMPDIR/nodes.txt"
