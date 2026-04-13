# TomoKX - ETH 永续合约自动交易系统

基于 Agent 的 ETH-USDT-SWAP 永续合约自动化网格交易系统。支持 **Windows 手动执行** 和 **Linux/openclaw 定时调度** 两种模式。

## 🌟 核心特性

- 🤖 **Agent 决策 + 脚本执行**: AI 负责审核与最终决策，脚本负责数据采集、草案生成和订单执行
- 📊 **纯开仓双向网格**: 只下开仓单 (`buy+long` / `sell+short`)，平仓完全交给每单自带的 TP/SL
- 📈 **多时间框架趋势分析**: 结合 4h（主趋势）、1h（确认）、15m（共振）判断趋势，并引入趋势对齐度评分
- 💰 **Funding Rate 纠偏**: 自动读取资金费率，当多头/空头付费显著偏向一侧时动态调整 target 分布
- 🛡️ **多重风控**: 
  - 日亏损限制 40 USDT（仅统计 ETH-USDT-SWAP）
  - 最大 30 张总仓位
  - 单侧最多 6 张 live 订单
  - 价格偏离 >100 USDT 自动取消
- 🧠 **自我学习系统**: 每次决策和每个订单的生命周期都会被记录，支持数据驱动的策略优化
- 🖥️ **双平台支持**: Windows 手动版 + Linux/openclaw 定时版
- 🔗 **系统 Skill 集成**: `tomokx` / `tomokx-openclaw` 已注册为 Agent 系统 Skill

## 📦 版本说明

本项目包含两个独立版本：

| 版本 | 路径 | 适用场景 | 调度方式 |
|------|------|---------|----------|
| **Windows 手动版** | `skills/tomokx/` | 本地 Windows 开发/测试 | 手动触发 |
| **Linux/openclaw 版** | `skills/tomokx-openclaw/` | 服务器/Linux 定时运行 | crontab / 每 30 分钟 |

> **注意**: 代理自动切换逻辑（`hysteria-switcher.py`、`proxy-switcher.py`）已被移除，当前版本依赖系统级网络连通性。

---

## 🚀 快速开始

### 环境要求

**Windows 手动版:**
- Windows 10/11
- `okx` CLI 工具 (v1.3.0+)
- `python` (3.12+)
- `curl`

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
```

#### Linux / openclaw 版

```bash
# 创建目录并复制脚本
mkdir -p ~/.openclaw/workspace/scripts
cp scripts-openclaw/* ~/.openclaw/workspace/scripts/
```

### 3. 配置 API 密钥

**此文件永远不会进入 Git 仓库**，`.gitignore` 已将其排除。

#### Windows
创建 `C:\Users\<你的用户名>\.openclaw\workspace\.env.trading`：
```powershell
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

趋势不再只看 24h 涨跌幅，而是采用 **4h 主趋势 + 1h 确认 + 15m 共振** 的三重时间框架：

| 对齐度 | 条件 | 最终趋势 | Long | Short |
|--------|------|---------|------|-------|
| **strong** | 4h / 1h / 15m 三者同向 | 同向趋势 | 2 / 1 / 1 | 1 / 2 / 2 |
| **moderate** | 4h 与 1h 同向，15m 可能不同 | 4h/1h 方向 | 同上 | 同上 |
| **mixed** | 4h 与 15m 同向，1h 不同 | Sideways | 1 | 1 |
| **weak** | 三者均不同向 | Sideways | 1 | 1 |

- **4h** 作为中期过滤器，决定主方向
- **1h** 用于确认或否定 4h 信号
- **15m** 识别短期反转噪音
- 当 `mixed` 或 `weak` 时，系统会自动压缩 target（两侧各 -1），降低暴露等待方向明确

### Funding Rate 纠偏

系统额外读取 ETH-USDT-SWAP 的资金费率：
- `funding_rate > +0.01%`（多头付空头）→ `short_favored` → short target +1，long target -1
- `funding_rate < -0.01%`（空头付多头）→ `long_favored` → long target +1，short target -1
- `-0.01% ~ +0.01%` → `neutral`，不调整

这为趋势判断增加了一个**市场情绪的量化纠偏信号**。

### 动态价格间隔

| 总仓位 | 间隔 (USDT) |
|--------|------------|
| 0 | 3 |
| 1 | 4 |
| 2 | 5 |
| 3 | 6 |
| 4 | 7 |
| 5-6 | 8 |
| 7-10 | 9 |
| 11-15 | 10 |
| 16-30 | 12 |

**间隔调整因子:**
- `volatility_1h` < 8: 可减 1–2
- `volatility_1h` 8–15: 使用 base gap
- `volatility_1h` > 15: +2–4
- `volatility_1h` > 25: 再增或暂停

### 关键规则

1. **纯开仓网格**：只下 `buy+long`（开多）和 `sell+short`（开空），**禁止**主动下平仓单。平仓由每单自带的 TP/SL 自动处理。
2. **单侧上限**：long 侧和 short 侧各自最多 **6 个 live 订单**。
3. **序列递进**：同一周期内多个新单必须像梯子一样逐级排列，禁止价格差 < gap 的订单。
4. **止损计数器（已移除）**：不再设置连续/累计止损次数限制，仅保留日亏损 40 USDT 上限作为风控停机条件。
5. **日亏损**：只统计 `ETH-USDT-SWAP` 平仓类记录的 **pnl 净值**（盈利可冲抵亏损），净值 < -40 USDT 时停止。

### 风险控制

| 参数 | 值 | 说明 |
|-----|---|------|
| 最大总仓位 | 30 | 挂单 + 持仓 |
| 取消阈值 | 100 USDT | 价格偏离超过此值取消 |
| 日亏损限制 | 40 USDT | 仅 ETH-USDT-SWAP |
| 单次下单 | 0.1 张 | 约 2 USDT 保证金 |
| 杠杆 | 10x | 逐仓模式 |
| 单侧最大挂单 | 6 张 | 避免过度延伸 |

---

## 🎯 执行流程

```
Step 1+2: 并发数据采集 → 市场/订单/持仓/风险/历史一次性拉取
Step 3a:  AI 决策参考  → calc_recommendation.py 提供量化建议
Step 3b:  生成交易草案 → calc_plan.py 基于策略生成 placements + reasoning
Step 3c:  AI 审核决策  → 阅读 reasoning，修改或否决草案
Step 4:   执行交易计划 → execute_and_finalize.py 统一执行撤单/下单/日志/学习记录
```

---

## 🧠 自我学习与策略优化

系统内置了两层学习机制，帮助持续优化策略参数。

### 决策日志 (`decisions.jsonl`)

每次执行后自动记录：
- 市场状态（趋势、价格、波动率）
- 策略参数（gap、target_long、target_short）
- 实际动作（撤销/新建数量、expansion_type）
- 决策时刻 baseline_pnl 与后续 outcome_pnl delta

### 订单生命周期跟踪 (`order_tracking.jsonl`)

每个成功下单都会记录 ordId、价格、TP/SL、expansion_type、placed_at 等。

### 分析工具

每周运行一次，评估策略效果：

```bash
# 粗粒度：决策级盈亏归因
python3 ~/.openclaw/workspace/scripts/analyze_decisions.py

# 细粒度：订单级真实盈亏与胜率
python3 ~/.openclaw/workspace/scripts/analyze_trades.py
```

**示例输出**：
```json
{
  "top_setups": [
    {
      "trend": "bullish",
      "gap": "14",
      "expansion_type": "inner",
      "posSide": "short",
      "count": 5,
      "avg_pnl": 0.92,
      "win_rate": 0.8
    }
  ],
  "recommendations": [
    "Best setup: short inner in bullish with gap=14 -> avg_pnl=0.92 win_rate=0.8 (n=5)",
    "Worst setup: long outer in bullish with gap=14 -> avg_pnl=-0.34 win_rate=0.25 (n=4); consider avoiding"
  ]
}
```

---

## 💡 常用命令

### 对 Agent 说的话
- `"开始交易"` / `"start trading"`
- `"交易状态"` / `"show trading status"`
- `"生成日报"` / `"generate daily report"`

### 手动操作

#### 快速运行完整交易循环（Linux / openclaw）
```bash
python3 ~/.openclaw/workspace/scripts/run_trade_cycle.py
```

#### 分析历史表现
```bash
python3 ~/.openclaw/workspace/scripts/analyze_decisions.py
python3 ~/.openclaw/workspace/scripts/analyze_trades.py
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
│   ├── config.py                # 统一配置 + 策略常量
│   ├── fetch_all_data.py        # 并发数据采集 (Step 1+2)
│   ├── calc_recommendation.py   # AI 决策参考 (Step 3a)
│   ├── calc_plan.py             # 交易草案生成 (Step 3b)
│   ├── calc_strategy.py         # 策略参数计算
│   ├── execute_and_finalize.py  # 统一执行 + 日志 + 学习记录 (Step 4)
│   ├── analyze_history.py       # 近期历史盈亏分析
│   ├── analyze_decisions.py     # 决策日志分析器
│   ├── analyze_trades.py        # 订单生命周期分析器
│   ├── fetch_orders.py          # 获取挂单
│   ├── fetch_positions.py       # 获取持仓
│   ├── filter_far_orders.py     # 筛选远离订单
│   └── run_trade_cycle.py       # 完整交易循环入口
├── scripts-openclaw/             # Linux 配套脚本
│   └── (与 scripts/ 对应，适配 Linux/openclaw 环境)
├── run_trade_cycle.py            # 顶层入口（调用 skills/ 逻辑）
├── HEARTBEAT.md                  # Windows 手动版 heartbeat
├── HEARTBEAT-openclaw.md         # openclaw 定时调度 heartbeat
├── .gitignore                    # 已排除 .env.trading 等敏感文件
├── README.md                     # 本文件
├── CHANGELOG.md                  # 更新日志
└── LICENSE
```

---

## 📝 近期更新

### v2.3.1 (2026-04-14)
- **修复硬编码暴露上限**: `calc_recommendation.py`、`execute_and_finalize.py` 中总暴露字符串的 `/20` 改为引用 `config.MAX_TOTAL`，确保日志与建议理由随配置同步
- **同步根目录配置**: `scripts/config.py` 与 `scripts-openclaw/config.py` 的 `MAX_TOTAL` 统一为 `30`，`MAX_PER_SIDE` 统一为 `6`

### v2.3.0 (2026-04-13)
- **调整总暴露与单侧上限**: 20 -> 30 张总仓位，单侧 4 -> 6 张
- **压缩网格间距**: base gap 从 5-14 调整为 3-12 USDT
- **优化 TP/SL**: 止盈更紧凑（TP 6-28），止损保持旧值（SL 85-115）
- **移除连续止损限制**: 取消 3 次止损计数器，仅保留 40 USDT 日亏损上限作为停机条件

### v2.2.0 (2026-04-12)
- **新增多时间框架趋势分析**: 4h（主趋势）+ 1h（确认）+ 15m（共振），引入 `trend_alignment`（strong/moderate/mixed/weak）
- **新增 Funding Rate 纠偏**: 根据资金费率动态调整 target 分布
- **calc_strategy.py 重构**: 基于 4h 主趋势、对齐度压缩 target、funding bias 调整 target 分布

### v2.1.0 (2026-04-12)
- **新增自我学习系统**: `decisions.jsonl` + `order_tracking.jsonl` + `analyze_decisions.py` + `analyze_trades.py`
- **增强 calc_plan.py reasoning**: 新增 `expansion_type`（内扩/外扩）、`target_deviation`、`hole_to_current` 等字段
- **完善 AI 决策框架**: SKILL.md 增加结构化决策权重和逐单复核 Checklist
- **优化 boost 逻辑**: 仅在内扩候选存在或 under-target 时才触发，避免生成无意义的重侧外扩单
- **统一执行入口**: `execute_and_finalize.py` 取代原来的 `execute_orders.py` + `update_stop_counter.py` + `log_trade.py`
- **并发数据采集**: `fetch_all_data.py` 一次性并发拉取 Step 1+2 的所有数据

### v2.0.0 (2026-04)
- **重大架构重构**: 从 20+ 个零散脚本精简为 11 个核心脚本
- **删除历史脚本**: `trade_cycle_check.py`、`eth_market_analyzer.py`、`run_*.py`、`hysteria-switcher.py`、`proxy-switcher.py` 等
- **新增 AI 决策支持**: `calc_recommendation.py` 提供 proceed/pause/reduce_exposure 建议
- **修复 Windows 编码问题**: `calc_recommendation.py` 和 `calc_plan.py` 强制 UTF-8 输出

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
