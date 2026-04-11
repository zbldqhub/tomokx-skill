# Heartbeat

## ETH 自动交易 (openclaw 调度版)

ETH 自动交易检查通过 **openclaw cron/heartbeat** 精确调度执行：
- **任务名**: ETH交易检查_每半小时
- **调度频率**: 每 30 分钟执行一次
- **执行时间**: 每小时的 00 分和 30 分
- **触发消息**: "开始交易" / "执行一次skill" / "run trading check"

**执行要求**: 当收到本 heartbeat 时，请完整执行 `tomokx-openclaw` skill 的 Steps 0-10：
1. 检查 `~/.openclaw/workspace/.trading_stopped` 和日亏损限制
2. 运行 `python3 ~/.openclaw/workspace/scripts/eth_market_analyzer.py` 获取市场快照
3. 按 Sideways/Bullish/Bearish 判断趋势，决定目标分布 (target_long / target_short)
4. 管理 ETH-USDT-SWAP 网格订单（只下纯开仓单：`sell+short` 和 `buy+long`）
5. 单侧最多 4 个 live 订单，同周期内价格间隔 ≥ gap
6. 记录日志到 `~/.openclaw/workspace/auto_trade.log`
7. 向用户汇报执行结果

**紧急停止**: 如果连续 3 次止损或日 ETH 亏损 > 40 USDT，立即停止交易并通知用户。

**环境检查**（如失败则跳过交易）：
```bash
bash ~/.openclaw/workspace/scripts/env-check.sh
```
