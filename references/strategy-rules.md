# 策略规则速查

完整机械定义见 `strategy-definition.md`。

- 市场环境：bull trend、bull pullback、sideways、bear trend、bear capitulation、bear recovery。
- 短期：突破回踩/趋势延续，14 日时间退出；中期：支撑反弹，90 日；长期：熊市结构反转，180 日。
- 趋势策略不在普通熊市做多；熊市策略必须有深度回撤与结构恢复，只有超卖不得开仓。
- 强确认 2 分、普通 1 分、辅助 0.5 分；至少一个强确认或合计 2 分。
- A 级要求两个目标和开盘至少 2R；B 级允许一个目标和至少 1.6R，风险减半。
- `support_zone`、`allowed_entry_range`、`planned_entry_price` 分开；下一开盘不得移动原 stop/TP 挽救计划。
- 熊市最多两笔；第二笔不得低于第一笔平均价，必须有独立结构确认并沿用原止损。
- 实时分析和回测唯一入口均为 `evaluate_setup_at_time`；1d/4h/1h 只使用当时已收盘数据。
