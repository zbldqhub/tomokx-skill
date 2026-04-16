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
- 🧠 **自我学习系统**: 每次决策和每个订单的生命周期都会被记录，AI 每周读取报告后可自主微调策略参数（gap 表、target 分配）
- 🖥️ **双平台支持**: Windows 手动版 + Linux/openclaw 定时版
- 📡 **ATR 动态网格**: gap 由 1h ATR(14) × 0.8 主导，低波动时自动收缩、高波动时自动防御
- 🧠 **AI 深度审核**: `ai_review.py` 硬规则 + LLM yellow-rules gate + dynamic sizing，自动检测 openclaw → fallback 到本地 `kimi.exe`
- 🔗 **系统 Skill 集成**: `tomokx` / `tomokx-openclaw` 已注册为 Agent 系统 Skill，且两套 SKILL 内容已统一

## 📦 版本说明

本项目技能文档已统一：

| 版本 | 路径 | 适用场景 | 调度方式 |
|------|------|---------|----------|
| **Windows 手动版** | `skills/tomokx/` | 本地 Windows 开发/测试 | 手动触发 / Task Scheduler |
| **Linux/openclaw 版** | `skills/tomokx-openclaw/` | 服务器/Linux 定时运行 | crontab / 每 30 分钟 |

> **注意**: 两个版本的 `SKILL.md` 已合并为统一策略 V2.0，核心规则（趋势判定、AI 决策边界、逐单 Checklist、调参权限）完全一致。
> 代理自动切换逻辑（`hysteria-switcher.py`、`proxy-switcher.py`）已被移除，当前版本依赖系统级网络连通性。

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

**设置定时任务（可选）**:
```powershell
# 安装每 4 小时自动运行的计划任务（需要管理员权限）
# 右键以管理员身份运行:
scripts\install_trading_task_admin.bat
```
或卸载：
```powershell
powershell -File "$env:USERPROFILE\.openclaw\workspace\scripts\uninstall_trading_task.ps1"
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
| **strong** | 4h / 1h / 15m 三者同向 | 同向趋势 | 4 / 1 | 1 / 4 |
| **moderate** | 4h 与 1h 同向，15m 可能不同 | 4h/1h 方向 | 3 / 1 | 1 / 3 |
| **mixed** | 4h 与 15m 同向，1h 不同 | Sideways | 0 | 0 |
| **weak** | 三者均不同向 | Sideways | 0 | 0 |

- **4h** 作为中期过滤器，决定主方向
- **1h** 用于确认或否定 4h 信号
- **15m** 识别短期反转噪音
- 当 `mixed` 或 `weak` 时，系统会自动压缩 target（两侧各 -1，**sideways 时强制归零**），降低暴露等待方向明确

### Funding Rate 纠偏

系统额外读取 ETH-USDT-SWAP 的资金费率：
- `funding_rate > +0.01%`（多头付空头）→ `short_favored` → short target +1，long target -1
- `funding_rate < -0.01%`（空头付多头）→ `long_favored` → long target +1，short target -1
- `-0.01% ~ +0.01%` → `neutral`，不调整

这为趋势判断增加了一个**市场情绪的量化纠偏信号**。

### 动态价格间隔

| 总仓位 | Base Gap (USDT) |
|--------|----------------|
| 0 | 5 |
| 1 | 6 |
| 2 | 7 |
| 3 | 8 |
| 4 | 9 |
| 5-6 | 10 |
| 7-10 | 11 |
| 11-15 | 12 |
| 16-30 | 14 |

**ATR 动态主导:**
- `adjusted_gap = max(base_gap, round(ATR(14) × 0.8))`
- 当市场波动小时，gap 自动收缩回 base table（交易频率更高）
- 当市场波动大时，gap 自动放宽（避免被震荡扫损）
- Soft cap: `adjusted_gap ≤ base_gap + 6`，防止极端行情下 gap 失控

**间隔微调:**
- `volatility_1h` > 15: +2
- `volatility_1h` > 25: +4
- `spread > 0.5`: +1

### 关键规则

1. **纯开仓网格**：只下 `buy+long`（开多）和 `sell+short`（开空），**禁止**主动下平仓单。平仓由每单自带的 TP/SL 自动处理。
2. **单侧上限**：long 侧和 short 侧各自最多 **6 个 live 订单**。
3. **序列递进**：同一周期内多个新单必须像梯子一样逐级排列，禁止价格差 < gap 的订单。
4. **TP/SL 盈亏比**: `TP = max(12, gap×1.5)`, `SL = max(20, gap×2.5)`，盈亏比约 **1:2.5**
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
Step 1+2: 并发数据采集 → 市场/订单/持仓/风险/历史/微观结构一次性拉取
Step 3a:  典型场景默认决策 → 最高优先级规则（重侧外扩删除等）
Step 3b:  AI 决策参考  → calc_recommendation.py 提供量化建议
Step 3c:  生成交易草案 → calc_plan.py 基于策略生成 placements + reasoning
Step 3d:  AI 审核决策  → ai_review.py 硬规则 + LLM yellow-rules gate + dynamic sizing
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

**AI 调参安全边界**:
- **可调参数**：`base_gap_table`、`volatility_*_boost` 阈值、`trend_targets`
- **禁止触碰**：`max_total`、`daily_loss_limit`、`per-side max`、`cancel_threshold`
- **调整幅度**：单次变动 **≤ ±2**
- **调参频率**：**≥ 7 天一次**
- **必须记录**：任何修改都要写入 `~/.openclaw/workspace/tuning_log.jsonl`

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
tomokx/
├── skills/
│   ├── tomokx/                  # Windows 手动版（与 openclaw 版已统一）
│   │   └── SKILL.md
│   └── tomokx-openclaw/         # Linux / openclaw 定时版
│       └── SKILL.md
├── scripts/                      # Windows 配套脚本
│   ├── config.py                # 统一配置 + 策略常量
│   ├── fetch_all_data.py        # 并发数据采集 (Step 1+2)
│   ├── calc_recommendation.py   # AI 决策参考 (Step 3b)
│   ├── calc_plan.py             # 交易草案生成 (Step 3c)
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

### v2.6.0 (2026-04-16)
- **ATR 动态主导 Gap**: base_gap 回调为 5-14，实际 `adjusted_gap = max(base_gap, round(ATR(14)×0.8))`，soft cap = base+6
- **TP/SL 大盈亏比**: `TP=max(12, gap×1.5)`, `SL=max(20, gap×2.5)`，盈亏比约 **1:2.5**
- **Strict Sideways**: `mixed/weak + sideways` 时两侧 target 强制归零，禁止 outer expansion
- **微观结构惩罚减半**: `rules.json` 中 depth_ratio/price_velocity/large_trade 等 penalty 减半，避免高波动市场过度保守
- **AI 审核链路硬化**: `ai_review.py` 自动检测 openclaw gateway → fallback 到本地 `kimi.exe`，hard rules + LLM yellow-rules gate + dynamic sizing
- **微观结构数据**: `fetch_all_data.py` 新增 order book 1%/live trades/5m candles/funding history，输出 depth_ratio、pressure_ratio、whale_activity 等信号
- **Trailing Stop 修复**: `trailing_stop_manager.py` 修正 OKX API 路径 (`amend-algos-order`)，增加容错
- **Windows 定时任务脚本**: 新增 `install_trading_task_admin.bat` / `install_trading_task.ps1` / `uninstall_trading_task.ps1`

### v2.5.0 (2026-04-15)
- **P0 重构 TP/SL 比例**：SL 从固定 85–115 收紧为 `gap×1.8`（最低 16），TP 放宽为 `gap×1.2`（最低 8），盈亏比从 1:4+ 改善到约 1:1.5
- **P1 禁止逆势/重侧外扩**：`calc_plan.py` 在机器生成阶段就禁止 bullish 下的 short outer、bearish 下的 long outer、mixed/weak 下的全部 outer，以及 imbalance≥2 时的重侧 outer
- **P2 提高趋势明确时 target 上限**：strong bullish → long target 4，strong bearish → short target 4，moderate 对应 3；sideways 修复为 (1,1)
- **P3 移动保本止损**：新增 `trailing_stop_manager.py`，持仓盈利 ≥ TP 距离 50% 时自动将 SL 移到开仓价 ±1 USDT，由 `execute_and_finalize.py` 自动调用
- **P4 事件/时间过滤**：`calc_recommendation.py` 支持读取 `events.json` 进行高影响事件过滤，并在 UTC 14:00–15:00 及 00:00–01:00 高波动窗口自动降级 confidence

### v2.4.0 (2026-04-14)
- **统一两套 SKILL.md**: `tomokx` 与 `tomokx-openclaw` 合并为统一策略 V2.0，内容完全一致
- **新增 AI 决策边界**: 明确 AI 为"审核员与仲裁者"，前置"默认决策"和"禁止事项"
- **新增逐单复核 Checklist**: 8 项前置检查，防止 TP 贴当前价、重侧外扩等硬伤
- **恢复 AI 调参权**: 每周读取报告后，AI 可在安全边界内自主微调 `config.py`
- **删除重复代码目录**: 移除 `tomokx-skill/` 子目录下的过时副本，统一以根目录为 source of truth
- **修复 CRLF 换行符**: `.sh` 脚本全部转换为 LF，确保 Linux/openclaw 环境可正常执行
- **同步 workspace 脚本**: 根目录最新脚本已覆盖到 `~/.openclaw/workspace/scripts/`

### v2.3.1 (2026-04-14)
- **修复硬编码暴露上限**: `calc_recommendation.py`、`execute_and_finalize.py` 中总暴露字符串的 `/20` 改为引用 `config.MAX_TOTAL`
- **同步根目录配置**: `scripts/config.py` 与 `scripts-openclaw/config.py` 的 `MAX_TOTAL` 统一为 `30`，`MAX_PER_SIDE` 统一为 `6`

### v2.3.0 (2026-04-13)
- **调整总暴露与单侧上限**: 20 -> 30 张总仓位，单侧 4 -> 6 张
- **压缩网格间距**: base gap 从 5-14 调整为 3-12 USDT
- **优化 TP/SL**: 止盈更紧凑（TP 6-28），止损保持旧值（SL 85-115）
- **移除连续止损限制**: 取消 3 次止损计数器，仅保留 40 USDT 日亏损上限作为停机条件

### v2.2.0 (2026-04-12)
- **新增多时间框架趋势分析**: 4h（主趋势）+ 1h（确认）+ 15m（共振），引入 `trend_alignment`
- **新增 Funding Rate 纠偏**: 根据资金费率动态调整 target 分布
- **calc_strategy.py 重构**: 基于 4h 主趋势、对齐度压缩 target、funding bias 调整 target 分布

### v2.1.0 (2026-04-12)
- **新增自我学习系统**: `decisions.jsonl` + `order_tracking.jsonl` + `analyze_decisions.py` + `analyze_trades.py`
- **增强 calc_plan.py reasoning**: 新增 `expansion_type`、`target_deviation`、`hole_to_current` 等字段
- **完善 AI 决策框架**: SKILL.md 增加结构化决策权重和逐单复核 Checklist
- **优化 boost 逻辑**: 仅在内扩候选存在或 under-target 时才触发
- **统一执行入口**: `execute_and_finalize.py` 取代原来的多个分散脚本
- **并发数据采集**: `fetch_all_data.py` 一次性并发拉取 Step 1+2 的所有数据

### v2.0.0 (2026-04)
- **重大架构重构**: 从 20+ 个零散脚本精简为 11 个核心脚本
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

### .sh 脚本无法执行
- 确保脚本为 LF 换行符。已修复，若仍有问题，重新从根目录复制即可

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
