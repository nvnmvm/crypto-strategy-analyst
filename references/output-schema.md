# 输出字段

分析 JSON 由 Pydantic 模型生成，并由 `schemas/analysis-report.schema.json` 约束。除时间、数据质量、三周期趋势、区域、指标和风险字段外，v1.3 还输出 `market_regime`、`regime_evidence`、`selected_strategy`、`strategy_horizon`、`entry_setup`、`candidate_tier`、`risk_multiplier`、加权确认、`support_zone`、`allowed_entry_range`、`planned_entry_price` 与 `target_sources`。回测包含固定日历 `chronological_holdout_split`、冻结参数滚动窗口、基准、集中度与 `research_protocol`；不把固定切分称为 walk-forward。

缺失的新闻、恐惧贪婪、链上、资金流和机器学习数据必须写为 `not_available`，不得用 `0` 或“中性”替代。
