#!/usr/bin/env bash
set -uo pipefail

PASS="a2f10cf0-3cbf-49a8-991d-b6188d453e54"
METHOD="chacha20-ietf-poly1305"
TEST_URL="https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT-SWAP"
NODES=(
  "x1.good2026.com:11011:Hong Kong 01 IEPL S"
  "tt.good2026.com:11111:Hong Kong 01 S"
  "x2.good2026.com:11011:Hong Kong 02 IEPL S"
  "mm.good2026.com:11211:Hong Kong 02 S"
  "n1.good2026.com:11011:Hong Kong 03 S"
  "x1.good2026.com:11031:Japan 01 IEPL S"
  "tt.good2026.com:11131:Japan 01 S"
  "x2.good2026.com:11031:Japan 02 IEPL S"
  "mm.good2026.com:11231:Japan 02 S"
  "n1.good2026.com:11031:Japan 03 S"
  "x1.good2026.com:11041:Singapore 01 IEPL S"
  "tt.good2026.com:11141:Singapore 01 S"
  "x2.good2026.com:11041:Singapore 02 IEPL S"
  "mm.good2026.com:11241:Singapore 02 S"
  "n1.good2026.com:11041:Singapore 03 S"
)

echo "=== Testing OKX via ss-local for selected nodes ==="
for node in "${NODES[@]}"; do
  IFS=':' read -r host port name <<<"$node"
  # kill any lingering ss-local
  pkill -f "ss-local.*$host.*$port" 2>/dev/null || true
  sleep 0.2
  /usr/bin/ss-local -s "$host" -p "$port" -k "$PASS" -m "$METHOD" -l 1080 -f /tmp/ss-test.pid &>/tmp/ss-test.log
  sleep 1.5
  out=$(curl -fsSL -m 10 --socks5-hostname 127.0.0.1:1080 "$TEST_URL" 2>/dev/null || true)
  if echo "$out" | grep -q '"last"'; then
    printf "[OK ] %-30s %s\n" "$host:$port" "$name"
  else
    printf "[FAIL] %-30s %s\n" "$host:$port" "$name"
  fi
  kill $(cat /tmp/ss-test.pid 2>/dev/null) 2>/dev/null || true
  sleep 0.3
done

echo ""
echo "=== Direct TCP test to same nodes ==="
for node in "${NODES[@]}"; do
  IFS=':' read -r host port name <<<"$node"
  if timeout 4 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null; then
    printf "[TCP_OK ] %-30s %s\n" "$host:$port" "$name"
  else
    printf "[TCP_FAIL] %-30s %s\n" "$host:$port" "$name"
  fi
done

echo ""
echo "=== ss-local log tail ==="
cat /tmp/ss-test.log | tail -n 20
