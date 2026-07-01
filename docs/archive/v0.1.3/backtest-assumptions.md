# 回测假设

## 时间与成交

- K 线索引代表开盘时间；收盘时间为开盘时间加周期长度。
- 决策只在已完成 4h 收盘发生；1d/4h/1h 均截断到同一 `evaluation_time`，只保留其收盘时间不晚于该时刻的数据。
- 信号成为 pending 计划，最早在下一根 4h 开盘验证并成交；决策 K 线内部不得成交。
- 买入原始成交：`market_open × (1 + buy_slippage)`，随后按价格 tick **向上**舍入；卖出：`reference_price × (1 - sell_slippage)`，随后按 tick **向下**舍入。任何舍入不得改善成交价。
- 买入数量按 step 向下取整；手续费也必须纳入现金约束，不允许负现金。
- 开盘跳过止损时按 `min(open, stop)` 作为卖出参考再施加不利滑点；开盘高于 TP1、低于止损、越过 entry zone 或 gap 超限时取消 pending。

## K 线内路径

- OHLC 不能说明同一根内的先后顺序；同根同时触及止损和止盈时一律先止损。
- 入场 K 线允许保护性止损，不允许在同一入场 K 线兑现 TP1/TP2。
- 下一根起先检查止损，再 TP1，再 TP2；该顺序是保守近似，不声称重建真实逐笔路径。
- TP1 卖原始数量 30%，TP2 再卖 30%，其余 40% 由移动止损；数量舍入后残余在最终退出处理。

## 成本与市场规则

- 默认单边手续费 0.1%，单边滑点 0.05%；报告必须包含至少基准、零成本、双倍手续费、双倍滑点固定情景，不能从中选优参数。
- 使用数据快照中的 Binance spot tick、step、minimum quantity、maximum quantity 和 minimum notional；规则缺失时禁止仓位/成交模拟，而不是填猜测值。
- `position_notional` 与风险损失不同；初始风险为 `quantity × (entry-stop)`，剩余开放风险随退出数量和保护止损变化。

## 数据、缺失与期末

- 数据集必须含 BTC/ETH 对应研究所需的 1d、4h、1h CSV 和公共交易规则快照。
- manifest 的完整性摘要覆盖 symbol、exchange、market type、start/end、三个文件及 SHA-256、交易规则、下载时间、数据源、软件版本和其他影响重放的元数据；任一 CSV 或元数据改变必须验证失败。
- 重复、非单调、OHLC 非法或陈旧行情失败关闭。Binance 历史中的时间缺口必须在 manifest 逐项列出；任何 500 根回看窗口仍含缺口的决策点强制 `no_trade`，不得插值、前向填充或拼接其他交易所。缺口离开回看窗口后才可恢复评估。
- 指标暖机至少 210 根已收盘 K 线；不足则不评估。
- 回测结束仍有仓位时，在最后一个可用 4h 收盘以不利卖出滑点和手续费强制平仓，退出原因 `forced_end_of_test`；不得把未实现盈利直接当现金收益。

## 研究与可重复性

- 默认固定日历切分为训练 2019–2021、验证 2022–2023、测试 2024–最新；字段名为 `chronological_holdout_split`，不是 walk-forward。
- 另以冻结参数报告 365 日窗口、每 180 日步进的 `rolling_window_results`；它不进行窗口内参数再优化。
- 参数在运行前固定；默认 `parameter_search_performed=false`、`number_of_parameter_sets_evaluated=1`、`selection_rule=predefined`。
- 报告保存软件版本、策略配置 hash、完整 dataset manifest hash、参数集 ID 和随机种子。
- BTC 从 Binance BTC/USDT spot 可核验历史起回放；早于交易对可用期的数据不拼接其他交易所。最终结果应说明实际起止日期，不把“BTC 诞生”与“Binance 上市”混为一谈。
- 600 USDT 是模拟初始现金；不包含税费、资金出入、利息或机会成本。历史收益不保证未来结果。
