# TomoKX Setup Guide

Complete setup guide for TomoKX automated trading system.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Verification](#verification)
5. [Usage](#usage)
6. [Troubleshooting](#troubleshooting)

## Prerequisites

Before you begin, ensure you have:

- [ ] OKX account with API trading enabled
- [ ] Linux/macOS environment (or WSL on Windows)
- [ ] Git installed
- [ ] Internet connection with proxy support (if required)

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/tomokx-skill.git
cd tomokx-skill
```

### 2. Install Dependencies

#### Install proxychains4

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install proxychains4
```

**macOS:**
```bash
brew install proxychains-ng
```

#### Install OKX CLI

Download and install the OKX CLI tool from the official source.

### 3. Configure Proxy (if needed)

Edit `/etc/proxychains4.conf`:

```
[ProxyList]
socks5 127.0.0.1 7890
```

Replace `7890` with your proxy port.

## Configuration

### 1. Create Environment File

Create `.env.trading` in `~/.openclaw/workspace/`:

```bash
mkdir -p ~/.openclaw/workspace
cat > ~/.openclaw/workspace/.env.trading << 'EOF'
# OKX API Credentials
export OKX_API_KEY="your-api-key-here"
export OKX_SECRET_KEY="your-secret-key-here"
export OKX_PASSPHRASE="your-passphrase-here"

# Proxy Settings
export PROXY_HOST="127.0.0.1"
export PROXY_PORT="7890"

# Trading Parameters (optional - defaults shown)
export MAX_ORDERS=5
export MAX_POSITIONS=20
export ORDER_SIZE=0.1
export LEVERAGE=10
export DAILY_LOSS_LIMIT=40
EOF
```

### 2. Get OKX API Credentials

1. Log in to your OKX account
2. Go to "API" in account settings
3. Create a new API key with permissions:
   - Read
   - Trade
4. Copy the API Key, Secret Key, and Passphrase
5. Paste them into `.env.trading`

**⚠️ Security Warning:** Never share your API credentials or commit them to Git!

### 3. Set File Permissions

```bash
chmod 600 ~/.openclaw/workspace/.env.trading
```

## Verification

### Run Environment Check

```bash
./scripts/env-check.sh
```

Expected output:
```
🔍 TomoKX Environment Check
================================

1. Environment Variables
✅ Environment file exists
✅ OKX_API_KEY is set
✅ OKX_SECRET_KEY is set
✅ OKX_PASSPHRASE is set

2. Dependencies
✅ git is installed
✅ proxychains4 is installed
✅ okx CLI is installed

3. API Connectivity
✅ OKX API connection successful
   💰 Available Balance: 1234.56 USDT

4. Workspace
✅ Workspace directory exists
✅ Workspace directory is writable

5. Trading Status
✅ Trading is active (no stop file)

================================
🎉 All checks passed! (9/9)
```

## Usage

### Manual Trading Cycle

```bash
./scripts/eth-trader-run.sh
```

This will:
1. Load environment variables
2. Check API connectivity
3. Verify trading status
4. Execute trading workflow
5. Log results

### Check Status Only

```bash
./scripts/env-check.sh
```

### Reset Stop Counter

If trading was paused due to consecutive losses:

```bash
echo 0 > ~/.openclaw/workspace/.trading_stopped
```

### View Logs

```bash
tail -f ~/.openclaw/workspace/auto_trade.log
```

## Automation

### Set Up Cron Job

Run trading check every 5 minutes:

```bash
# Edit crontab
crontab -e

# Add line:
*/5 * * * * cd /path/to/tomokx-skill && ./scripts/eth-trader-run.sh >> /dev/null 2>&1
```

### Using Systemd (Linux)

Create service file `/etc/systemd/system/tomokx.service`:

```ini
[Unit]
Description=TomoKX ETH Trader
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/tomokx-skill
ExecStart=/path/to/tomokx-skill/scripts/eth-trader-run.sh
Restart=on-failure
RestartSec=300

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable tomokx
sudo systemctl start tomokx
sudo systemctl status tomokx
```

## Troubleshooting

### API Connection Failed

**Symptom:** `❌ OKX API connection failed`

**Solutions:**
1. Check proxy configuration
2. Verify API credentials
3. Ensure API key has trade permissions
4. Check if OKX API is accessible from your region

### Permission Denied

**Symptom:** `Workspace directory is not writable`

**Solution:**
```bash
chmod 755 ~/.openclaw
chmod 755 ~/.openclaw/workspace
```

### Trading Paused

**Symptom:** `🛑 Trading is paused (consecutive stops: 3)`

**Solution:**
```bash
echo 0 > ~/.openclaw/workspace/.trading_stopped
```

Then investigate why stops occurred in the logs.

### Missing Dependencies

**Symptom:** `git is not installed` or similar

**Solution:**
```bash
# Ubuntu/Debian
sudo apt-get install git proxychains4

# macOS
brew install git proxychains-ng
```

## Safety Checklist

Before running live trading:

- [ ] Test with small amount first
- [ ] Verify API credentials are correct
- [ ] Check account balance is sufficient
- [ ] Understand all risk controls
- [ ] Set up monitoring/notifications
- [ ] Have a plan for manual intervention
- [ ] Never trade with money you can't afford to lose

## Support

For issues and questions:
1. Check logs: `~/.openclaw/workspace/auto_trade.log`
2. Review [SKILL.md](../SKILL.md) for detailed logic
3. Open an issue on GitHub

## Updates

To update to the latest version:

```bash
cd tomokx-skill
git pull origin main
```

Always review changes before updating, especially if they affect trading logic.
