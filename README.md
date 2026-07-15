# crypto-strategy-analyst v0.3.0

由 OpenClaw 调用的主流加密货币盘面分析 Skill。它获取调用者指定的公开市场数据，自动选择 BTC、ETH、BNB、SOL 或 Generic Profile，分别生成短线、波段和长期计划，并输出 JSON、中文 Markdown 和机器可读事件。

OpenClaw 决定分析币种、调用频率、监控升级、去重和通知。本项目不运行定时任务、不固定扫描列表、不发送 Telegram，也不管理账户或执行买卖。

## 安装

```bash
openclaw skills install git:nvnmvm/crypto-strategy-analyst@v0.3.0
python3 -m pip install ~/.openclaw/workspace/skills/crypto-strategy-analyst
crypto-strategy-analyst --help
```

开发环境支持 Python 3.11–3.13：

```bash
python -m pip install -e '.[dev]'
ruff check .
python -m compileall src
pytest --cov=crypto_strategy_analyst --cov-fail-under=85
python -m build
```

## 六个命令

```bash
crypto-strategy-analyst analyze BTC/USDT --profile auto --horizons short swing long --format json
crypto-strategy-analyst compare BTC/USDT ETH/USDT BNB/USDT SOL/USDT
crypto-strategy-analyst validate-entry outputs/BTC-USDT-report.json --dataset data/BTC-USDT --horizon swing
crypto-strategy-analyst fetch-dataset BTC/USDT data/BTC-USDT
crypto-strategy-analyst fetch-dataset BTC/USDT data/BTC-USDT-full --start 2017-08-01
crypto-strategy-analyst backtest data/BTC-USDT --horizons short swing long
crypto-strategy-analyst research diagnose data/BTC-USDT
```

`analyze` 同时支持 `--symbol BTC/USDT`、离线 `--dataset`、调用者提供的 `--external-data`、`--output-dir` 和 Markdown 输出。`compare` 只比较调用者传入的币种，不内置扫描列表。

## 分析规则

- 实时分析和回测共用 `evaluate_setup_at_time`。
- 历史评估只读取当时已经收盘的 K 线；候选只在下一根计划周期 K 线开盘验证。
- `fetch-dataset --start` 按 Binance 的公开 K 线分页从指定 UTC 日期开始下载；回放窗口仍使用与实时获取一致的每周期 `history_limit`，避免历史评估获得实时调用看不到的额外数据。
- 多周期候选先统一按入场时间排序，再使用一个不重叠的现金账户依次定仓；不同周期的循环顺序不会影响较早交易的权益。
- 六种策略独立检测并保留失败原因，不再选择“第一个已启用策略”。
- BTC Profile 的策略开关可由固定历史归因审查，但不会自动套用到其他资产；任何配置更新都必须再经过独立日期切分验证，不能为了单段历史收益自动调参。
- 候选必须有结构确认，辅助指标不能单独触发信号。
- 双顶、双底、头肩顶、倒头肩底和收敛三角突破由已收盘 K 线与 ATR 尺寸规则识别；只有颈线或边界有效突破才是确认，形成中的形态只作观察。已确认的看空形态会抑制多头候选，不会自动产生做空指令。
- 入场范围由结构止损、可靠目标、最低盈亏比和允许偏差反推。
- 同一根 K 线同时触发止损和止盈时，回测默认先止损。
- 缺失辅助数据不会伪造中性分，而是降低数据完整度和置信度上限。

配置合并顺序：代码默认 < `config/default.yaml` < Profile 配置 < 用户配置 < CLI 覆盖。详细规则见 `references/`，迁移说明见 [MIGRATION-v0.3.0.md](MIGRATION-v0.3.0.md)。

所有结果仅供研究，不保证收益，不构成投资建议。
