# 风控规则

- 默认单笔最大风险为权益 1%，配置硬上限 3%。
- 单日两次止损后停止新候选；单日亏损达到 2% 停止新候选。
- 账户回撤达到 10% 时暂停。
- 仓位按 `当前持久化权益 × risk_per_trade / 止损距离比例` 计算，再受当前权益和最大投入比例限制。配置权益只用于首次初始化。
- `position_notional_cny` 是投入金额；`maximum_loss_amount` 是止损触发时预计最大亏损，两者不可混用。
- 默认 `cny_per_usdt` 只是可配置的账户计价换算参数，不冒充实时外汇报价。
- 账户状态 v3 以 `account-state.json` 物化，统一保存 UTC 日期、每日止损/实现亏损、当前/峰值权益、回撤、现金、保留现金、BTC/ETH 持仓、pending 计划、组合开放风险和已处理 command-id；`account-events.jsonl` 保存追加事实。
- UTC 日期切换只重置每日字段；峰值权益和最大回撤状态跨日保留。
- 所有生产状态变化通过 `apply_command(current_state, command)`；命令含唯一 `command_id`、时间和 `expected_state_version`。重复 command-id 是不重复修改的成功 no-op；版本冲突和非法转换失败关闭。
- 使用带超时的 POSIX 文件锁覆盖完整事务；先写 WAL，再追加事件并 `fsync`，最后原子替换物化状态。恢复按 event-id 去重。超时、损坏状态或损坏 WAL 必须报错停止。
- 旧 v2 风险文件迁移前创建备份并保留权益、每日字段、峰值和历史 ID；迁移失败即停止。
- `position` 默认读取持久化当前权益；文件不存在时要求先初始化。显式 `--equity-cny` 覆盖必须输出警告。建议还受可用现金、单币种/总投入上限和 2% aggregate open risk 限制。
