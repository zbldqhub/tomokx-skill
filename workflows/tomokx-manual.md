# tomokx 手动执行 Workflow

本文件定义 AI Agent（包括 Kimi Code CLI）手动执行 tomokx 交易 skill 的完整操作步骤。
策略规则参见 `skills/tomokx/SKILL.md`，AI 决策边界也定义于该文件。

---

## 前置检查

- 确认 `~/.openclaw/workspace/.env.trading` 已配置 OKX API 密钥
- 确认 `risk.should_stop == false`，否则立即停止并通知用户

---

## Step 1 · 数据采集

调用 `fetch_all_data.py` 一次性并发拉取所有数据：

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\fetch_all_data.py"
```

**输出检查**：
- 若顶层包含 `"error"`，查看 `diagnostics` 定位失败子任务
- 失败时重试最多 2 次（间隔 2 秒）
- 若仍失败，停止并通知用户具体异常

**提取关键字段**：
- `market.last`（当前价格）
- `strategy.trend`, `strategy.trend_alignment`, `strategy.adjusted_gap`
- `exposure.total`, `exposure.remaining_capacity`
- `risk.should_stop`, `risk.daily_pnl`
- `far_orders.far_orders`（远单列表）

**保存中间文件**（推荐做法）：
```powershell
$tmp = "$env:TEMP\tomokx_manual_$PID"
New-Item -ItemType Directory -Force -Path $tmp
# 将 market / exposure / strategy / far_orders / orders / history 分别保存为 $tmp\xxx.json
```

---

## Step 2 · 策略基线

运行 `calc_strategy.py`：

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\calc_strategy.py" `
  "$tmp\market.json" <total_exposure> "$tmp\exposure.json"
```

读取 `base_gap`、`adjusted_gap`、`target_long`、`target_short`、`trend_alignment`、`funding_bias`。

---

## Step 3a · 量化决策参考

运行 `calc_recommendation.py`：

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\calc_recommendation.py" `
  "$tmp\market.json" "$tmp\exposure.json" `
  "$tmp\strategy.json" "$tmp\history.json"
```

读取 `recommendation`、`confidence`、`suggested_targets`、`suggested_gap`、`risk_flags`。

> **Windows 编码注意**：`calc_recommendation.py` 偶尔输出含控制字符的字符串。若直接通过管道重定向到文件出现 JSON 解析失败，请使用 Python `io.StringIO` 捕获 stdout 再落盘，或手动清理后再解析。

---

## Step 3b · 生成交易草案

运行 `calc_plan.py`：

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\calc_plan.py" `
  "$tmp\market.json" "$tmp\exposure.json" `
  "$tmp\strategy.json" "$tmp\far_orders.json" `
  "$tmp\orders.json"
```

输出包含 `cancellations`、`placements`、`reasoning`、`summary`。

---

## Step 3c · AI 审核

对 `calc_plan.py` 输出的每一单，执行 `SKILL.md` 中的"默认决策规则"和"逐单复核 Checklist"。

若需要调用脚本辅助审核（hard rules + LLM yellow-rules gate）：

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\ai_review.py" `
  "$tmp\plan.json" "$tmp\market.json" "$tmp\exposure.json" `
  "$tmp\strategy.json" "$tmp\recommendation.json"
```

参数顺序：**plan → market → exposure → strategy → rec**

AI 仍需独立验证结果，不能完全依赖脚本输出。

---

## Step 4 · 执行交易计划

将最终审核后的计划保存为 JSON（例如 `$tmp\ai_review_plan.json`），然后执行：

```powershell
python "$env:USERPROFILE\.openclaw\workspace\scripts\execute_and_finalize.py" `
  "$tmp\ai_review_plan.json"
```

**执行失败处理**（脚本内部已处理部分）：
- **余额不足 / 价格已失效**：从失败订单开始，重新调用 `calc_plan.py` 生成修正计划，再次执行。
- **Rate limit (429)**：等待 10s 后自动重试一次。
- **其他错误**：跳过该单，记录原因到日志，继续执行剩余订单。

---

## 常见异常处理

### JSON 文件带 UTF-8 BOM
若 `json.load()` 报错 `Unexpected UTF-8 BOM`：
```python
with open(path, 'r', encoding='utf-8-sig') as f:
    data = json.load(f)
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
```

### `calc_recommendation.py` 输出不可解析
使用 Python 内嵌捕获：
```python
import sys, io, os
sys.path.insert(0, os.path.expanduser('~/.openclaw/workspace/scripts'))
from calc_recommendation import main as rec_main
old_stdout = sys.stdout
sys.stdout = io.StringIO()
sys.argv = ['calc_recommendation.py', market_path, exposure_path, strategy_path, history_path]
try:
    rec_main()
except SystemExit:
    pass
output = sys.stdout.getvalue()
sys.stdout = old_stdout
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(output)
```

---

## 快速命令参考

```bash
# 查看市场 ticker
okx market ticker ETH-USDT-SWAP --json

# 查看挂单
okx swap orders --json

# 查看持仓
okx swap positions --json

# 下单示例
okx swap place --instId ETH-USDT-SWAP --tdMode isolated --side buy --ordType limit --sz 0.1 --px=2345.0 --posSide long --tpTriggerPx=2375.0 --tpOrdPx=-1 --slTriggerPx=2230.0 --slOrdPx=-1
```
