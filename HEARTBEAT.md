# Heartbeat

## ETH 自动交易

ETH 自动交易检查已通过 **cron** 精确调度，不再通过本 Heartbeat 文件执行：
- **任务名**: ETH交易检查_每小时
- **调度表达式**: `0 * * * *` (Asia/Shanghai)
- **执行时间**: 每小时的 00 分（1 小时一次）
- **下次执行**: 参见 `openclaw cron list`

当收到常规 heartbeat 时，此处无额外手动任务需要执行。如需立即执行交易检查，请直接发送消息：“执行一次skill”。
