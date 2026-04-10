# TomoKX Skill

OpenClaw skill for automated ETH perpetual swap trading on OKX.

## 🌟 Features

- 🤖 Automated grid trading strategy
- 📊 Dynamic price gap adjustment (8-45 USDT)
- 🛡️ Risk control:
  - Stop-loss protection (3 consecutive losses)
  - Daily loss limit (40 USDT)
  - Max 20 total positions
- 🔔 Real-time execution notifications
- 📈 Trend-based order distribution

## 🚀 Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/YOUR_USERNAME/tomokx-skill.git
cd tomokx-skill
```

### 2. Configure Environment

Create `.env.trading` file:

```bash
# OKX API Credentials
export OKX_API_KEY="your-api-key"
export OKX_SECRET_KEY="your-secret-key"
export OKX_PASSPHRASE="your-passphrase"

# Proxy Settings
export PROXY_HOST="127.0.0.1"
export PROXY_PORT="7890"

# Trading Parameters (optional overrides)
export MAX_ORDERS=5
export MAX_POSITIONS=20
export ORDER_SIZE=0.1
export LEVERAGE=10
export DAILY_LOSS_LIMIT=40
```

### 3. Run Trading Check

```bash
# Check environment
./scripts/env-check.sh

# Run trading cycle
./scripts/eth-trader-run.sh
```

## 📋 Trading Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Max Orders | 5 | Maximum open orders |
| Max Positions | 20 | Maximum total positions (orders + holdings) |
| Order Size | 0.1 | Contracts per order |
| Leverage | 10x | Isolated margin |
| Daily Loss Limit | 40 USDT | Stop trading if exceeded |
| Price Gap | 8-45 USDT | Dynamic based on position count |
| Cancellation Threshold | 50 USDT | Cancel orders too far from price |

## 📖 Documentation

- [SKILL.md](SKILL.md) - Complete skill documentation and trading logic
- [Setup Guide](docs/setup-guide.md) - Detailed setup instructions

## 🎯 Trading Strategy

### Trend Detection

| 24h Change | Trend | Long Orders | Short Orders |
|------------|-------|-------------|--------------|
| > +2% | Bullish | 2 | 1 |
| < -2% | Bearish | 1 | 2 |
| -2% to +2% | Sideways | 1 | 2 |

### Dynamic Price Gap

| Total Positions | Gap (USDT) |
|-----------------|------------|
| 0 | 8 |
| 1 | 10 |
| 2 | 12 |
| 3 | 15 |
| 4 | 20 |
| 5 | 25 |
| 6 | 28 |
| 7 | 32 |
| 8 | 35 |
| 9 | 38 |
| 10 | 40 |
| 11-15 | 42 |
| 16-20 | 45 |

## 🛡️ Risk Controls

- **Stop Protection**: Pause after 3 consecutive stop-losses
- **Daily Loss Limit**: Stop if daily loss > 40 USDT
- **Position Limits**: Max 20 total positions (orders + holdings)
- **Price Monitoring**: Cancel orders >50 USDT away from current price
- **Per-Order TP/SL**: Each order has built-in take-profit and stop-loss

## 📁 Project Structure

```
tomokx-skill/
├── README.md              # This file
├── LICENSE                # MIT License
├── .gitignore            # Git ignore rules
├── SKILL.md              # OpenClaw skill definition
├── setup-github.sh       # GitHub setup script
├── scripts/              # Helper scripts
│   ├── eth-trader-run.sh
│   └── env-check.sh
└── docs/                 # Documentation
    └── setup-guide.md
```

## 🔧 Requirements

- OKX API Key with trading permissions
- proxychains4 for proxy support
- Bash environment
- OpenClaw or compatible agent system

## ⚠️ Risk Warning

Trading involves significant risk of loss. This system uses 10x leveraged trading which can amplify both gains and losses. Never trade with money you cannot afford to lose. Monitor positions regularly.

**Important:**
- 10x leverage means 10% price move = 100% position loss
- Stop-losses are not guaranteed to execute at exact price
- Market gaps can cause larger losses than expected
- Past performance does not guarantee future results

## 📄 License

MIT License - See [LICENSE](LICENSE) file

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📞 Support

For issues and questions, please open an issue on GitHub.
