# Heartbeat - openclaw 调度版

## System Event 处理规则

当收到 **system event `tomokx-trading-check`** 时，**立即执行以下操作，不要回复 `HEARTBEAT_OK`**。

### 执行内容

1. **读取 skill**: 读取 `skills/tomokx-openclaw/SKILL.md`
2. **完整执行交易检查**: 严格按照 SKILL.md 的 Step 0-10 执行：
   - **Step 0**: 加载环境变量 `source ~/.openclaw/workspace/.env.trading`
   - **Step 1**: 检查 `~/.openclaw/workspace/.trading_stopped`（已废弃，仅保留兼容读取）
   - **Step 1.2**: 运行 `python3 ~/.openclaw/workspace/scripts/get_bills.py --today`，检查 ETH-USDT-SWAP 日亏损是否超过 -40 USDT
   - **Step 1.5**: 运行 `python3 ~/.openclaw/workspace/scripts/eth_market_analyzer.py` 获取市场快照
   - **Step 2**: 判断趋势（Bullish/Bearish/Sideways），优先采用 1h 趋势
   - **Step 3**: 统计 live `sell+short` 和 `buy+long` 订单数量
   - **Step 4**: 统计 10x isolated ETH-USDT-SWAP 持仓数量
   - **Step 5**: 计算总暴露 `total = orders + positions`
   - **Step 6**: 取消价格偏离当前价 >100 USDT 的订单
   - **Step 7**: 根据趋势表确定目标分布
   - **Step 8**: 下单/补单（纯开仓，per-side ≤ 6，价格间隔 ≥ gap）
   - **Step 8.5**: （止损计数器已移除，仅保留日亏损上限作为风控）
   - **Step 10**: 记录日志到 `~/.openclaw/workspace/auto_trade.log`，发送执行摘要

3. **输出格式**: 最后一条消息必须是执行摘要，格式如下：
   ```
   📊 ETH Trader 执行完成
   趋势: <trend> | 价格: <price> | 挂单: <orders>/30 | 持仓: <positions> | 总暴露: <total>/30
   操作: <actions>
   ```

## 常规 Heartbeat

如果没有收到 `tomokx-trading-check`，只是普通 heartbeat 轮询，则回复 `HEARTBEAT_OK`。
