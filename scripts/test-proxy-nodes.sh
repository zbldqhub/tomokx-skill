#!/usr/bin/env bash
set -euo pipefail

SUB_URL='https://abc.xhonor.top:9066/v2b/ant/api/v1/client/subscribe?token=0d9c28410352e569a2b3f19c00ddc9bc'
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

echo "Fetching subscription..."
curl -fsSL "$SUB_URL" | base64 -d > "$TMPDIR/sub.txt"

# extract host:port
grep -oE '@[^#]+' "$TMPDIR/sub.txt" | sed 's/^@//' | sort -u > "$TMPDIR/nodes.txt"

echo ""
echo "Testing nodes (TCP connect timeout 5s):"
echo "========================================="

while IFS= read -r node; do
  host="${node%:*}"
  port="${node#*:}"
  if timeout 5 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null; then
    echo "[OK]   $node"
  else
    echo "[FAIL] $node"
  fi
done < "$TMPDIR/nodes.txt"

echo ""
echo "Testing direct OKX reachability:"
echo "=================================="
if curl -fsSL -m 10 https://www.okx.com > /dev/null 2>&1; then
  echo "[OK]   Direct https://www.okx.com reachable"
else
  echo "[FAIL] Direct https://www.okx.com NOT reachable"
fi
