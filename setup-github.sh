#!/bin/bash

# TomoKX Skill GitHub Setup Script
# Usage: ./setup-github.sh <github-username> <repo-name>

set -e

USERNAME=$1
REPO_NAME=${2:-"tomokx-skill"}

if [ -z "$USERNAME" ]; then
    echo "Usage: ./setup-github.sh <github-username> [repo-name]"
    echo "Example: ./setup-github.sh johndoe"
    exit 1
fi

echo "🚀 Setting up GitHub repository for TomoKX Skill..."
echo ""

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "❌ Git is not installed. Please install git first."
    exit 1
fi

# Check if GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    echo "⚠️  GitHub CLI (gh) not found. Install it from: https://cli.github.com/"
    echo "   Or create the repository manually on GitHub website."
    USE_WEB=true
else
    USE_WEB=false
    # Check if logged in
    if ! gh auth status &> /dev/null; then
        echo "🔑 Please login to GitHub first:"
        gh auth login
    fi
fi

# Initialize git if not already done
if [ ! -d ".git" ]; then
    echo "📦 Initializing git repository..."
    git init
fi

# Create README.md if not exists
if [ ! -f "README.md" ]; then
    echo "📝 Creating README.md..."
    cat > README.md << 'EOF'
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

## 📖 Documentation

- [SKILL.md](SKILL.md) - Complete skill documentation
- [Setup Guide](docs/setup-guide.md) - Detailed setup instructions

## ⚠️ Risk Warning

Trading involves significant risk of loss. This system uses 10x leveraged trading which can amplify both gains and losses. Never trade with money you cannot afford to lose.

## 📄 License

MIT License - See [LICENSE](LICENSE) file
EOF
fi

# Create LICENSE file (MIT)
if [ ! -f "LICENSE" ]; then
    echo "📄 Creating LICENSE (MIT)..."
    cat > LICENSE << EOF
MIT License

Copyright (c) $(date +%Y) $USERNAME

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF
fi

# Create .gitignore
if [ ! -f ".gitignore" ]; then
    echo "🚫 Creating .gitignore..."
    cat > .gitignore << 'EOF'
# Environment variables (contains secrets)
.env.trading
.env

# Logs
*.log
logs/

# Trading data
.trading_stopped

# OS files
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
*.swp
*.swo

# Dependencies
node_modules/
EOF
fi

# Add all files
echo "➕ Adding files to git..."
git add .

# Commit
echo "💾 Committing..."
git commit -m "Initial commit: Add TomoKX trading skill

- Automated ETH perpetual swap trading on OKX
- Grid trading strategy with dynamic price gaps
- Risk controls: stop-loss, daily loss limit, position limits
- Real-time notifications and logging
- Complete documentation and setup scripts"

# Create GitHub repository and push
if [ "$USE_WEB" = false ]; then
    echo "🌐 Creating GitHub repository via CLI..."
    gh repo create "$REPO_NAME" --public --description "OpenClaw skill for automated ETH trading on OKX" --source=. --remote=origin --push
else
    echo ""
    echo "📝 Manual GitHub Setup Required:"
    echo "================================"
    echo "1. Go to https://github.com/new"
    echo "2. Repository name: $REPO_NAME"
    echo "3. Description: OpenClaw skill for automated ETH trading on OKX"
    echo "4. Choose Public or Private"
    echo "5. DO NOT initialize with README"
    echo "6. Click 'Create repository'"
    echo ""
    echo "Then run these commands:"
    echo "   git remote add origin https://github.com/$USERNAME/$REPO_NAME.git"
    echo "   git branch -M main"
    echo "   git push -u origin main"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "📁 Repository: https://github.com/$USERNAME/$REPO_NAME"
echo ""
