#!/usr/bin/env bash
set -uo pipefail

PASS="a2f10cf0-3cbf-49a8-991d-b6188d453e54"
METHOD="chacha20-ietf-poly1305"
TEST_URL="https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP"
SUB="https://abc.xhonor.top:9066/v2b/ant/api/v1/client/subscribe?token=0d9c28410352e569a2b3f19c00ddc9bc"
TMP=$(mktemp)
curl -fsSL "$SUB" | base64 -d | grep -oE '@[^#]+' | sed 's/^@//' | sort -u > "$TMP"

echo "=== Parallel TCP test (timeout 5s) ==="
while read node; do
  IFS=':' read -r h p <<< "$node"
  ( timeout 5 bash -c "exec 3<>/dev/tcp/$h/$p" 2>/dev/null && echo "TCP_OK $node" || echo "TCP_FAIL $node" ) &
done < "$TMP"
wait

echo ""
echo "=== ss-local -> OKX test (sample: all x2 nodes, timeout 8s) ==="
for node in x2.good2026.com:11011 x2.good2026.com:11021 x2.good2026.com:11031 x2.good2026.com:11041 x2.good2026.com:11051 x2.good2026.com:11061; do
  IFS=':' read -r h p <<< "$node"
  pkill -f "ss-local.*$h.*$p" 2>/dev/null || true
  /usr/bin/ss-local -s "$h" -p "$p" -k "$PASS" -m "$METHOD" -l 1080 -f /tmp/ss-test.pid >/dev/null 2>&1
  sleep 1
  if curl -fsSL -m 8 --socks5-hostname 127.0.0.1:1080 "$TEST_URL" 2>/dev/null | grep -q '"last"'; then
    echo "OKX_OK $node"
  else
    echo "OKX_FAIL $node"
  fi
  kill $(cat /tmp/ss-test.pid 2>/dev/null) 2>/dev/null || true
  sleep 0.3
done

rm -f "$TMP"
