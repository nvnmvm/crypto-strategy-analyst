# 参数登记表

参数来源等级见 `evidence-register.md`。敏感度范围用于稳定性报告，不代表搜索空间；不得自动保留收益最高组合。修改历史初始项均为 `v0.1.3: 登记现有值或明确待实现值`。

| 参数名 | 默认值 | 允许范围 | 策略意义 | 来源 | 敏感度测试范围 | 修改历史 |
|---|---:|---:|---|---|---|---|
| `history_limit` | 500 | 250–1000 | 每周期最大历史窗口 | 工程约束 C | 300/500/750 | v0.1.3 登记 |
| `request_connect_timeout_seconds` | 5 | (0,30] | 公共请求连接超时 | Nygard B | 3/5/8 | v0.1.3 实现 |
| `request_read_timeout_seconds` | 15 | (0,60] | 公共请求读取超时 | Nygard B | 10/15/20 | v0.1.3 实现 |
| `request_max_total_seconds` | 45 | (0,120] | 单操作最大总耗时 | Nygard B | 30/45/60 | v0.1.3 实现 |
| `max_retries` | 3 | 1–5 | 最大尝试次数（含首次） | Nygard B | 2/3/4 | v0.1.3 登记 |
| `retry_backoff_base_seconds` | 0.5 | [0,10] | 指数退避基数 | Nygard B | 0.25/0.5/1 | v0.1.3 实现 |
| `circuit_failure_threshold` | 3 | 1–10 | 连续失败开路阈值 | Nygard B | 2/3/5 | v0.1.3 实现 |
| `circuit_cooldown_seconds` | 60 | 1–600 | 熔断冷却 | Nygard B | 30/60/120 | v0.1.3 实现 |
| `freshness_grace_seconds` | 90 | 0–600 | 收盘后的抓取宽限 | 数据语义 C | 60/90/120 | v0.1.3 登记 |
| `risk_per_trade` | 0.01 | (0,0.03] | 单笔初始风险/权益 | 安全约束 A | 0.005/0.01/0.015 | v0.1.3 登记 |
| `max_risk_per_trade` | 0.03 | (0,0.03] | 单笔硬上限 | 安全约束 A | 不搜索 | v0.1.3 登记 |
| `daily_stop_count` | 2 | 1–10 | 每日止损次数锁 | 安全约束 A | 2/3 | v0.1.3 登记 |
| `daily_max_loss` | 0.02 | (0,0.10] | 每日实现亏损锁 | 安全约束 A | 0.015/0.02 | v0.1.3 登记 |
| `max_drawdown` | 0.10 | (0,0.50] | 回撤暂停阈值 | 安全约束 A | 0.08/0.10/0.12 | v0.1.3 登记 |
| `aggregate_open_risk_limit` | 0.02 | (0,0.03] | BTC+ETH 剩余开放风险上限 | 安全约束 A | 0.015/0.02 | v0.1.3 实现 |
| `max_symbol_deployed_fraction` | 0.60 | (0,1] | 单币种投入上限 | 组合约束 C | 0.4/0.6/0.8 | v0.1.3 实现 |
| `max_total_deployed_fraction` | 1.00 | (0,1] | 总投入上限，无负现金 | 安全约束 A | 0.8/1.0 | v0.1.3 实现 |
| `reserved_cash_fraction` | 0.00 | [0,1) | 不可用于新仓的现金 | 账户约束 C | 0/0.1/0.2 | v0.1.3 实现 |
| `min_reward_risk` | 2.0 | [2,5] | TP1 最低 R 倍数 | 安全约束 A | 2.0/2.25/2.5 | v0.1.3 登记 |
| `strong_buy_score` | 75 | 60–90 | A级强候选标签阈值 | 预登记研究 C | 75/80 | v0.1.3 实现 |
| `buy_score` | 60 | 50–80 | 候选标签阈值 | 预登记研究 C | 58/60/65 | v0.1.3 实现 |
| `watch_score` | 45 | 30–60 | 观察标签阈值 | 预登记研究 C | 45/50 | v0.1.3 实现 |
| `b_tier_min_reward_risk` | 1.6 | 1.5–2.0 | B级开盘最低 R | 风险规则 C | 1.5/1.6/1.8/2.0 | v0.1.3 实现 |
| `execution_reward_risk_cushion` | 0.2 | 0.05–0.5 | 计划目标相对最低R的执行缓冲 | 执行约束 C | 0.1/0.2/0.3 | v0.1.3 实现 |
| `b_tier_risk_multiplier` | 0.5 | (0,0.5] | B级风险折扣 | 安全约束 A | 0.25/0.5 | v0.1.3 实现 |
| `sideways_risk_multiplier` | 0.5 | (0,1] | 横盘候选风险折扣 | 风险规则 C | 0.25/0.5 | v0.1.3 实现 |
| `bear_first_risk_multiplier` | 0.25 | 0.25–0.5 | 熊市试探仓风险折扣 | 安全约束 A | 0.25/0.5 | v0.1.3 实现 |
| `bear_drawdown_threshold` | 0.25 | 0.20–0.50 | 熊市反转最小365日回撤 | 预登记研究 C | 0.25/0.30/0.35 | v0.1.3 实现 |
| `bear_max_deployed_fraction` | 0.20 | 0.15–0.25 | 熊市单币最大投入 | 安全约束 A | 0.15/0.20/0.25 | v0.1.3 实现 |
| `trailing_atr_multiple` | 2.0 | 0.5–5 | TP1 后移动止损宽度 | Kaufman/Pardo C | 1.5/2.0/2.5 | v0.1.3 登记 |
| `swing_left` | 3 | 1–10 | 确认摆点左窗口 | 经验规则 C | 2/3/4 | v0.1.3 登记 |
| `swing_right` | 3 | 1–10 | 确认摆点右窗口 | 反前视约束 B | 2/3/4 | v0.1.3 登记 |
| `level_merge_percent` | 0.006 | (0,0.03] | 区域聚类价格容差 | 经验规则 C | 0.004/0.006/0.008 | v0.1.3 登记 |
| `support_proximity_atr` | 1.0 | (0,3] | 靠近支撑阈值 | 经验规则 C | 0.8/1.0/1.2 | v0.1.3 登记 |
| `entry_zone_depth_atr` | 0.25 | [0,1] | 入场区向支撑内部深度 | 经验规则 C | 0.15/0.25/0.35 | v0.1.3 实现 |
| `entry_zone_chase_atr` | 0.15 | [0,1] | 支撑上方允许追价范围 | 经验规则 C | 0.1/0.15/0.2 | v0.1.3 实现 |
| `stop_buffer_atr` | 0.50 | (0,2] | 支撑下方止损缓冲 | 风险规则 C | 0.35/0.50/0.75 | v0.1.3 实现 |
| `volume_ratio_threshold` | 1.2 | [1,5] | 最新量/前 20 根均量 | 经验规则 C | 1.1/1.2/1.3 | v0.1.3 登记 |
| `min_confirmations` | 2 | 2–7 | 独立确认最小数量 | 策略约束 C | 2/3 | v0.1.3 登记 |
| `touch_cooldown_bars` | 6 | 1–50 | 独立区域互动间隔 | 客观化规则 B | 4/6/8 | v0.1.3 登记 |
| `reaction_atr_multiple` | 0.75 | (0,5] | 有效反弹幅度 | 客观化规则 C | 0.5/0.75/1.0 | v0.1.3 登记 |
| `break_atr_multiple` | 0.25 | (0,2] | 有效跌破缓冲 | 客观化规则 C | 0.15/0.25/0.35 | v0.1.3 登记 |
| `target_resistance_buffer_atr` | 0.15 | [0,1] | 目标与阻力安全距离 | 安全约束 B | 0.1/0.15/0.2 | v0.1.3 登记 |
| `min_second_target_r_multiple` | 2.5 | (2,4] | TP2 目标 R | 经验规则 C | 2.5/3.0/3.5 | v0.1.3 登记 |
| `max_entry_gap_atr` | 0.5 | (0,3] | 下一开盘与计划价最大偏差 | 执行约束 B | 0.3/0.5/0.7 | v0.1.3 登记 |
| `pending_signal_valid_bars` | 1 | 1–6 | pending 有效 4h 根数 | 反前视约束 B | 1/2 | v0.1.3 登记 |
| `fee_rate` | 0.001 | [0,0.02] | 单边手续费 | 回测假设 C | 0.0005/0.001/0.002 | v0.1.3 登记 |
| `slippage_rate` | 0.0005 | [0,0.02] | 单边不利滑点 | 回测假设 C | 0/0.0005/0.001 | v0.1.3 登记 |
| `split_mode` | calendar | calendar/ratio | 研究报告时间切分方式 | 研究协议 B | 不优化 | v0.1.3 实现 |
| `train_end_date` | 2021-12-31 | ISO日期 | 训练段终点 | 研究协议 B | 不优化 | v0.1.3 实现 |
| `validation_end_date` | 2023-12-31 | ISO日期 | 验证段终点 | 研究协议 B | 不优化 | v0.1.3 实现 |
| `train_ratio/validation_ratio/test_ratio` | 0.6/0.2/0.2 | 合计1 | 仅兼容 ratio 模式；不得称 walk-forward | 研究协议 B | 不优化 | v0.1.3 保留兼容 |
| `minimum_sample_trades` | 30 | >=1 | 样本不足警告阈值，不代表统计充分 | 研究约束 C | 30/50/100 | v0.1.3 登记 |
| `random_seed` | 42 | 整数 | 可重复研究；当前策略不得消费随机数 | 工程约束 B | 固定 | v0.1.3 登记 |

`account_equity_cny` 与 `cny_per_usdt` 是账户初始化和计价配置，不是策略参数；在 600 USDT 研究中应显式以 USDT 为账户计价或记录固定换算，不得冒充实时汇率。
