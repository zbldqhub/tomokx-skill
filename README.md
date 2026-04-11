# TomoKX - ETH 永续合约自动交易系统

基于 OpenClaw 的 ETH-USDT-SWAP 永续合约自动化网格交易系统。

## 🌟 核心特性

- 🤖 **Agent 原生执行**: 所有交易逻辑由 Agent 逐步执行，非脚本自动化
- 📊 **智能网格策略**: 动态价格间隔（5-14 USDT），根据仓位和波动率调整
- 📈 **多时间框架趋势分析**: 结合 1h 和 24h 数据判断趋势
- 🛡️ **多重风控**: 
  - 连续止损 3 次自动暂停
  - 日亏损限制 40 USDT
  - 最大 20 张总仓位
  - 价格偏离 >60 USDT 自动取消
- 🔔 **实时通知**: 每次执行后自动发送执行摘要
- 🌐 **智能代理切换**: 12 个代理节点自动故障转移

## 🚀 快速开始

### 1. 环境要求

- Linux/macOS/WSL
- `okx` CLI 工具 (v1.2.7+)
- `proxychains4`
- `python3`
- `curl`

### 2. 安装

```bash
# 克隆仓库
git clone https://github.com/zbldqhub/tomokx-skill.git
cd tomokx-skill

# 配置环境
mkdir -p ~/.openclaw/workspace
cp scripts/* ~/.openclaw/workspace/scripts/
```

### 3. 配置环境变量

创建 `~/.openclaw/workspace/.env.trading`:

```bash
# ============================================
# OKX API 凭证（必需）
# ============================================
export OKX_API_KEY="your-api-key"
export OKX_SECRET_KEY="your-secret-key"
export OKX_PASSPHRASE="your-passphrase"

# ============================================
# 代理密码（必需）
# ============================================
# Hysteria2 代理密码（用于 hysteria-switcher.py）
export HYSTERIA_PASSWORD="your-hysteria-password"

# Shadowsocks 代理密码（用于 proxy-switcher.py）
export SS_PASSWORD="your-shadowsocks-password"

# ============================================
# 交易参数（可选，使用默认值可省略）
# ============================================
export MAX_ORDERS=20        # 最大挂单数
export MAX_TOTAL=20         # 最大总仓位（挂单+持仓）
export ORDER_SIZE=0.1       # 每张订单合约数
export LEVERAGE=10          # 杠杆倍数
export DAILY_LOSS_LIMIT=40  # 日亏损限制（USDT）
```

**⚠️ 安全提示：**
- 此文件包含敏感信息，**永远不要提交到 Git**
- 已自动添加到 `.gitignore`，不会被跟踪
- 建议设置文件权限：`chmod 600 ~/.openclaw/workspace/.env.trading`

### 4. 验证环境

```bash
# 检查环境
./scripts/env-check.sh

# 测试代理连接
python3 ~/.openclaw/workspace/scripts/hysteria-switcher.py
```

### 5. 开始交易

对 Agent 说：
- `"开始交易"` / `"start trading"`
- `"运行交易检查"` / `"run trading check"`

## 📋 交易策略参数

### 趋势判断

| 24h 涨跌 | 趋势 | 多单目标 | 空单目标 |
|---------|------|---------|---------|
| > +2% | 看涨 | 2 | 1 |
| < -2% | 看跌 | 1 | 2 |
| -2% ~ +2% | 横盘 | 1 | 2 |

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
- 高波动 (ATR > 5): +20%
- 宽 spread (> 0.5 USDT): +10%
- 强趋势 (|change| > 5%): +15%

### 风险控制

| 参数 | 值 | 说明 |
|-----|---|------|
| 最大挂单 | 20 | 同时存在的限价单 |
| 最大总仓位 | 20 | 挂单 + 持仓 |
| 取消阈值 | 60 USDT | 价格偏离超过此值取消 |
| 连续止损 | 3 次 | 触发暂停 |
| 日亏损限制 | 40 USDT | 触发停止 |
| 单次下单 | 0.1 张 | 约 2 USDT 保证金 |
| 杠杆 | 10x | 逐仓模式 |
| 每周期最大下单 | 5 张 | 防止过度交易 |

## 🎯 执行流程

```
Step 0: 环境设置 → 加载配置 + 代理检查
Step 1: 交易状态检查 → 止损计数 + 日亏损检查
Step 1.5: 市场快照 → 聚合所有数据
Step 2: 市场数据分析 → 趋势判断
Step 3: 检查当前挂单
Step 4: 检查当前持仓
Step 5: 计算总仓位
Step 6: 取消远离订单
Step 7: 确定目标分布
Step 8: 管理订单 → 开新单/补单
Step 9: 计算 TP/SL
Step 10: 日志记录 + 通知
```

## 💡 常用命令

### 查询状态
```bash
# 查看交易状态
"交易状态" / "show trading status"

# 生成日报
"生成日报" / "generate daily report"
```

### 重置计数器
```bash
# 重置止损计数（交易暂停后）
echo 0 > ~/.openclaw/workspace/.trading_stopped
```

### 手动检查
```bash
# 环境检查
./scripts/env-check.sh

# 市场分析
python3 ~/.openclaw/workspace/scripts/eth_market_analyzer.py
```

## 🌐 代理节点池

12 个全球节点自动切换：
- 香港: hk1, hk2
- 日本: jp1, jp2
- 新加坡: sg1, sg2
- 韩国: kr1, kr2
- 美国: us1
- 印度: in1
- 英国: gb1
- 泰国: th1

## 📁 项目结构

```
tomokx/
├── skills/
│   └── tomokx/
│       └── SKILL.md          # 核心 Skill 定义
├── scripts/
│   ├── eth-trader-run.sh     # 环境验证包装器
│   ├── env-check.sh          # 环境检查
│   ├── eth_market_analyzer.py # 市场数据聚合器
│   ├── hysteria-switcher.py  # 代理切换器
│   └── ...                   # 其他辅助脚本
├── logs/                     # 交易日志
└── README.md                 # 本文件
```

## ⚠️ 风险提示

**重要提示：**
- 10x 杠杆意味着 10% 价格波动 = 100% 仓位损失
- 止损单不保证在确切价格执行
- 市场跳空可能导致超出预期的损失
- 过往表现不代表未来结果

**交易有风险，入市需谨慎。只投入您能承受损失的资金。**

## 🔧 故障排除

### API 连接失败
```bash
# 测试代理
python3 ~/.openclaw/workspace/scripts/hysteria-switcher.py

# 手动测试 API
source ~/.openclaw/workspace/.env.trading
proxychains4 -f /etc/proxychains.conf okx swap orders
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

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📞 支持

如有问题：
1. 查看日志: `~/.openclaw/workspace/auto_trade.log`
2. 检查 [SKILL.md](skills/tomokx/SKILL.md) 详细逻辑
3. 提交 GitHub Issue

---

**免责声明**: 本系统仅供学习研究使用，不构成投资建议。使用本系统进行交易产生的任何损失由使用者自行承担。
