# 鲁棒性研究协议

## 目的与禁止事项

本协议判断预定义策略对小幅参数、成本和时间区间变化是否脆弱，不寻找“最赚钱组合”。禁止在看过 test 段后改规则再重跑同一 test 并把它称为样本外；禁止只保存最佳结果；禁止自动参数优化。

## 固定流程

1. 为策略版本冻结参数集 ID、代码 SHA、dataset manifest hash 和研究假设。
2. 只在 train 段提出或修正规则；validation 用于一次方向性检查；test 在冻结后只运行一次。
3. 基准参数集与每个单参数邻域分别运行；一次只改变一个参数，其他保持基准。
4. 保存每一次运行，不按收益过滤；`number_of_parameter_sets_evaluated` 等于真实运行数量。
5. 报告全样本仅用于描述，不用于重新选择参数。

## v0.1.3 预登记邻域

- `support_proximity_atr`: 0.8 / 1.0 / 1.2
- `volume_ratio_threshold`: 1.1 / 1.2 / 1.3
- `max_entry_gap_atr`: 0.3 / 0.5 / 0.7
- `touch_cooldown_bars`: 4 / 6 / 8
- `reaction_atr_multiple`: 0.5 / 0.75 / 1.0
- `target_resistance_buffer_atr`: 0.10 / 0.15 / 0.20
- 成本：基准、手续费×2、滑点×2、二者×2

这些值是事前邻域，不构成笛卡尔积搜索。若未来需要组合试验，必须先登记总组合数和选择规则。

## 必报指标

- 交易次数、生成/执行/取消数量
- 总收益与年化收益（仅描述）
- 最大回撤、Profit Factor、每笔期望值、平均/中位 R
- chronological train/validation/test 各段表现
- 暴露率、平均资金利用率、总手续费与滑点
- 成本翻倍后的收益、回撤和 Profit Factor
- 与 buy-and-hold 的差异，但不把后者当无风险基准

## 判断规则

- `stable`: 相邻值没有符号翻转式崩溃，交易数足够，test 与 validation 方向一致，双倍成本下无灾难性恶化。
- `fragile`: 仅一个精确值盈利、相邻值大幅转负，或表现由极少数交易支配。
- `insufficient_evidence`: 任一关键区段少于 `minimum_sample_trades`，或数据质量不足。

阈值在首次运行前登记；在有数据前不凭空给“允许下降百分比”。结果为 fragile 时暂停新增复杂度，优先审查数据、时间对齐、成交模型和规则冗余。

## Walk-Forward backlog（v0.2.0）

v0.1.3 已报告冻结参数的 365 日窗口、每 180 日步进的 `rolling_window_results`，用于检查不同时段的方向一致性；它不在窗口内重新选参数，因此不称为 walk-forward optimization。真正滚动估计窗选参与随后未见测试窗的拼接协议仍为 v0.2.0 backlog；任何固定日历切分或冻结参数滚动结果均不得使用 `walk_forward` 名称。

## 用户要求的“发现问题后优化”

600 USDT BTC 全历史研究先按冻结的 v0.1.3 运行。只有当问题被归类为实现缺陷、数据缺陷、假设不现实或预登记规则脆弱时才提出修正；修正后提升策略版本和 parameter_set_id，并在新的未见区段或后续数据验证。不得把同一完整历史反复用作优化和最终证明。
