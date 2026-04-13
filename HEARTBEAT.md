# Heartbeat

## ETH 自动交易

ETH 自动交易检查通过本 Heartbeat 文件调度执行：
- **任务名**: ETH交易检查_每半小时
- **调度频率**: 每 30 分钟执行一次
- **执行时间**: 每小时的 00 分和 30 分
- **触发消息**: "执行一次skill" 或 "开始交易"

**执行要求**: 当收到本 heartbeat 时，请完整执行 `tomokx` skill 的 Steps 0-10：
1. 检查 `.trading_stopped` 和日亏损限制
2. 运行 `python $WORKSPACE/scripts/eth_market_analyzer.py` 获取市场快照
3. 按 Sideways/Bullish/Bearish 趋势判断目标分布
4. 管理 ETH-USDT-SWAP 网格订单（纯开仓方向：sell+short 和 buy+long）
5. 记录日志到 `$WORKSPACE/auto_trade.log`
6. 向用户汇报执行结果

**紧急停止**: 如果日亏损 > 40 USDT，立即停止交易并通知用户。
