#!/bin/bash
set -e
cd /root/.openclaw/workspace
source .env.trading
python3 scripts/get_bills.py
