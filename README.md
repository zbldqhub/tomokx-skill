# TomoKX - ETH 永续合约自动交易系统

基于 Agent 的 ETH-USDT-SWAP 永续合约自动化网格交易系统。支持 **Windows 手动执行** 和 **Linux/openclaw 定时调度** 两种模式。

## 🌟 核心特性

- 🤖 **Agent 原生执行**: 所有交易逻辑由 Agent 逐步执行、分析、决策，非硬编码脚本自动化
- 📊 **纯开仓双向网格**: 只下开仓单 (`buy+long` / `sell+short`)，平仓完全交给每单自带的 TP/SL
- 📈 **多时间框架趋势分析**: 结合 1h 和 24h 数据判断趋势
- 🛡️ **多重风控**: 
  - 连续止损 3 次自动暂停（有完整执行路径 Step 8.5）
  - 日亏损限制 40 USDT（仅统计 ETH-USDT-SWAP）
  - 最大 20 张总仓位
  - 单侧最多 4 张 live 订单
  - 价格偏离 >100 USDT 自动取消
- 🔔 **实时通知**: 每次执行后自动发送执行摘要
- 🖥️ **双平台支持**: Windows 手动版 + Linux/openclaw 定时版

## 📦 版本说明

本项目包含两个独立版本：

| 版本 | 路径 | 适用场景 | 调度方式 |
|------|------|---------|----------|
| **Windows 手动版** | `skills/tomokx/` | 本地 Windows 开发/测试 | 手动触发 |
| **Linux/openclaw 版** | `skills/tomokx-openclaw/` | 服务器/Linux 定时运行 | openclaw cron / 每 30 分钟 |

> **注意**: 代理自动切换逻辑（`hysteria-switcher.py`、`proxy-switcher.py`）已被移除，当前版本依赖系统级网络连通性。
>
> **CLI 1.3.0 适配说明**: `okx account bills` 在 1.3.0 中不再支持 `--type` / `--begin` 等过滤参数，因此使用自定义 `get_bills.py` 直接调用 REST API 获取账单数据。`eth_market_analyzer.py` 也已适配 CLI 1.3.0 的 `--json` 输出格式（raw data）。

---

## 🚀 快速开始

### 环境要求

**Windows 手动版:**
- Windows 10/11
- `okx` CLI 工具 (v1.3.0+)
- `python` (3.12+)
- `curl`
- `node`（用于自动 patch OKX CLI 的 ProxyAgent TLS）

**Linux/openclaw 版:**
- Linux / macOS / WSL
- `okx` CLI 工具 (v1.3.0+)
- `python3`
- `curl`
- `bash`

### 1. 克隆仓库

```bash
git clone https://github.com/zbldqhub/tomokx-skill.git
cd tomokx-skill
```

### 2. 安装与部署

#### Windows 手动版

```powershell
# 创建目录并复制脚本
$workspace = "$env:USERPROFILE\.openclaw\workspace"
New-Item -ItemType Directory -Force -Path "$workspace\scripts"
Copy-Item scripts\* "$workspace\scripts\" -Recurse -Force

# 运行环境检查（会自动 patch OKX CLI）
& "$workspace\scripts\env-check.ps1"
```

#### Linux / openclaw 版

```bash
# 创建目录并复制脚本
mkdir -p ~/.openclaw/workspace/scripts
cp scripts-openclaw/* ~/.openclaw/workspace/scripts/

# 运行环境检查
bash ~/.openclaw/workspace/scripts/env-check.sh
```

### 3. 配置 API 密钥

**此文件永远不会进入 Git 仓库**，`.gitignore` 已将其排除。

#### Windows
创建 `C:\Users\<你的用户名>\.openclaw\workspace\.env.trading`：
```powershell
# 用记事本创建，填入你的子账户 API
notepad "$env:USERPROFILE\.openclaw\workspace\.env.trading"
```

#### Linux
创建 `~/.openclaw/workspace/.env.trading`：
```bash
cat > ~/.openclaw/workspace/.env.trading << 'EOF'
# OKX API 凭证（必需）
export OKX_API_KEY="your-api-key"
export OKX_SECRET_KEY="your-secret-key"
export OKX_PASSPHRASE="your-passphrase"

# 交易参数（可选，使用默认值可省略）
export MAX_ORDERS=20
export MAX_TOTAL=20
export ORDER_SIZE=0.1
export LEVERAGE=10
export DAILY_LOSS_LIMIT=40
EOF
chmod 600 ~/.openclaw/workspace/.env.trading
```

> **⚠️ 安全提示**：真实的 API 密钥**只应**保存在 `~/.openclaw/workspace/.env.trading` 或 `C:\Users\<user>\.openclaw\workspace\.env.trading` 中，**永远不要提交到本仓库**。

### 4. 开始交易

对 Agent 说：
- `"开始交易"` / `"start trading"`
- `"运行交易检查"` / `"run trading check"`

---

## 📋 交易策略参数

### 趋势判断

| 24h 涨跌 | 趋势 | 多单目标 | 空单目标 |
|---------|------|---------|---------|
| > +2% | 看涨 (Bullish) | 2 | 1 |
| < -2% | 看跌 (Bearish) | 1 | 2 |
| -2% ~ +2% | 横盘 (Sideways) | 1 | 2 |

### 动态价格间隔

| 总仓位 | 间隔 (USDT) |
|--------|------------|
| 0 | 5 |
| 1 | 6 |
| 2 | 7 |
| 3 | 8 |
| 4 | 9 |
| 5 | 10 |
| 6 | 10 |
| 7-10 | 11 |
| 11-15 | 12 |
| 16-20 | 14 |

**间隔调整因子:**
- `volatility_1h` < 8: 可减 1–2（但更密）
- `volatility_1h` 8–15: 使用 base gap
- `volatility_1h` > 15: +2–4
- `volatility_1h` > 25: 再增或暂停

### 关键规则

1. **纯开仓网格**：只下 `buy+long`（开多）和 `sell+short`（开空），**禁止**主动下平仓单（`sell+long` / `buy+short`）。平仓由每单自带的 TP/SL 自动处理。
2. **单侧上限**：long 侧和 short 侧各自最多 **4 个 live 订单**。
3. **序列递进**：同一周期内多个新单必须像梯子一样逐级排列，禁止同一周期内出现价格差 < gap 的订单。
4. **止损计数器**：Step 8.5 会检测平仓/减仓/TP/SL/强平（`subType ∈ {4,6,110,111,112}`）且 `pnl < 0` 的账单，递增 `.trading_stopped`，≥3 时自动暂停交易。
5. **日亏损**：只统计 `ETH-USDT-SWAP` 平仓类记录（`subType ∈ {4,6,110,111,112}`）的 **pnl 净值**（盈利可冲抵亏损），净值 < -40 USDT 时停止。

### 风险控制

| 参数 | 值 | 说明 |
|-----|---|------|
| 最大挂单 | 20 | 同时存在的开仓限价单 |
| 最大总仓位 | 20 | 挂单 + 持仓 |
| 取消阈值 | 100 USDT | 价格偏离超过此值取消 |
| 连续止损 | 3 次 | 触发暂停 |
| 日亏损限制 | 40 USDT | 仅 ETH-USDT-SWAP |
| 单次下单 | 0.1 张 | 约 2 USDT 保证金 |
| 杠杆 | 10x | 逐仓模式 |
| 每周期最大下单 | 5 张 | 防止过度交易 |
| 单侧最大挂单 | 4 张 | 避免过度延伸 |

---

## 🎯 执行流程

```
Step 0:  环境设置 → 加载配置
Step 1:  交易状态检查 → 止损计数 + 日亏损检查
Step 1.5: 市场快照 → 聚合所有数据
Step 2:  市场数据分析 → 趋势判断
Step 3:  检查当前挂单（只计开仓方向）
Step 4:  检查当前持仓
Step 5:  计算总仓位（remaining_capacity = floor(20 - total)）
Step 6:  取消远离订单（>100 USDT）
Step 7:  确定目标分布
Step 8:  管理订单 → 开新单/补单（纯开仓 + 序列递进）
Step 8.5: 更新止损计数器
Step 9:  计算 TP/SL
Step 10: 日志记录 + 通知
```

---

## 💡 常用命令

### 对 Agent 说的话
- `"开始交易"` / `"start trading"`
- `"交易状态"` / `"show trading status"`
- `"生成日报"` / `"generate daily report"`
- `"重置止损计数"` / `"reset stop counter"`

### 手动操作

#### 重置止损计数
```bash
# Windows PowerShell
"0" | Out-File -FilePath "$env:USERPROFILE\.openclaw\workspace\.trading_stopped" -Encoding utf8

# Linux / macOS / WSL
echo 0 > ~/.openclaw/workspace/.trading_stopped
```

#### 环境检查
```bash
# Windows PowerShell
& "$env:USERPROFILE\.openclaw\workspace\scripts\env-check.ps1"

# Linux
bash ~/.openclaw/workspace/scripts/env-check.sh
```

#### 市场分析
```bash
# Windows
python C:\Users\<username>\.openclaw\workspace\scripts\eth_market_analyzer.py

# Linux
python3 ~/.openclaw/workspace/scripts/eth_market_analyzer.py
```

#### 账单查询（日亏损 / 止损检查）
```bash
# Windows
python C:\Users\<username>\.openclaw\workspace\scripts\get_bills.py --today

# Linux
python3 ~/.openclaw/workspace/scripts/get_bills.py --today
```

#### 交易周期诊断（只检查不下单）
```bash
# Windows
python C:\Users\<username>\.openclaw\workspace\scripts\trade_cycle_check.py

# Linux
python3 ~/.openclaw/workspace/scripts/trade_cycle_check.py
```

---

## 📁 项目结构

```
tomokx-skill/
├── skills/
│   ├── tomokx/                  # Windows 手动版
│   │   └── SKILL.md
│   └── tomokx-openclaw/         # Linux / openclaw 定时版
│       └── SKILL.md
├── scripts/                      # Windows 配套脚本
│   ├── eth-trader-run.sh
│   ├── env-check.sh
│   ├── env-check.ps1
│   ├── eth_market_analyzer.py   # 已适配 CLI 1.3.0 --json
│   ├── get_bills.py             # REST API 账单查询（替代 CLI bills）
│   ├── trade_cycle_check.py     # 交易周期诊断（只检查不下单）
│   ├── patch-okx-cli.js         # 修复 OKX CLI ProxyAgent TLS
│   ├── hysteria-switcher.py     # (已停用)
│   └── proxy-switcher.py        # (已停用)
├── scripts-openclaw/             # Linux 配套脚本
│   ├── eth-trader-run.sh
│   ├── env-check.sh
│   ├── eth_market_analyzer.py   # 已适配 CLI 1.3.0 --json
│   ├── get_bills.py             # REST API 账单查询（替代 CLI bills）
│   └── trade_cycle_check.py     # 交易周期诊断（只检查不下单）
├── HEARTBEAT.md                  # Windows 手动版 heartbeat
├── HEARTBEAT-openclaw.md         # openclaw 定时调度 heartbeat
├── .gitignore                    # 已排除 .env.trading 等敏感文件
├── README.md                     # 本文件
└── LICENSE
```

---

## ⚠️ 风险提示

**重要提示：**
- 10x 杠杆意味着 10% 价格波动 = 100% 仓位损失
- 止损单不保证在确切价格执行
- 市场跳空可能导致超出预期的损失
- 过往表现不代表未来结果

**交易有风险，入市需谨慎。只投入您能承受损失的资金。**

---

## 🔧 故障排除

### OKX CLI 连接失败（Windows + 代理）

如果你通过 Clash/V2Ray 等本地 HTTP 代理上网，OKX CLI 可能需要 patch：

```powershell
# 自动 patch
node "$env:USERPROFILE\.openclaw\workspace\scripts\patch-okx-cli.js"
```

### 交易暂停

```bash
# 检查止损计数
cat ~/.openclaw/workspace/.trading_stopped

# 重置
echo 0 > ~/.openclaw/workspace/.trading_stopped
```

### 日亏损限制
- 检查日志: `tail ~/.openclaw/workspace/auto_trade.log`
- 次日自动恢复，或手动重置（不推荐）

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📞 支持

如有问题：
1. 查看日志: `~/.openclaw/workspace/auto_trade.log`
2. 检查 Windows 版逻辑: [skills/tomokx/SKILL.md](skills/tomokx/SKILL.md)
3. 检查 Linux/openclaw 版逻辑: [skills/tomokx-openclaw/SKILL.md](skills/tomokx-openclaw/SKILL.md)
4. 提交 GitHub Issue

---

**免责声明**: 本系统仅供学习研究使用，不构成投资建议。使用本系统进行交易产生的任何损失由使用者自行承担。
