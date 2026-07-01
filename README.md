# crypto-strategy-analyst v0.2.0

面向 OpenClaw 的主流加密货币现货分析 Skill。公共引擎对 BTC、ETH、BNB、SOL 使用独立资产 Profile，对其他交易对使用受限置信度的 Generic Profile；短线、波段、长线计划分别输出。实时分析与回测共用 `evaluate_setup_at_time`，历史回放只读取当时已收盘的 1w/1d/4h/1h（可选 15m）K 线。

## 安装

```bash
openclaw skills install git:nvnmvm/crypto-strategy-analyst@v0.2.0
python3 -m pip install ~/.openclaw/workspace/skills/crypto-strategy-analyst
crypto-strategy-analyst --help
```

开发环境需要 Python 3.11–3.13：

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=crypto_strategy_analyst --cov-fail-under=80
python -m build
```

## 九个公共命令

```bash
crypto-strategy-analyst analyze BTC/USDT --format markdown
crypto-strategy-analyst compare BTC/USDT ETH/USDT SOL/USDT
crypto-strategy-analyst validate-entry outputs/report.json --horizon swing
crypto-strategy-analyst fetch-dataset BTC/USDT data/btc.json
crypto-strategy-analyst backtest data/btc.json
crypto-strategy-analyst research diagnose
crypto-strategy-analyst portfolio show
crypto-strategy-analyst journal add '{"symbol":"BTCUSDT","pnl":12}'
crypto-strategy-analyst exchange draft BTCUSDT BUY 0.001 60000
```

配置合并顺序为：代码默认值 < `config/default.yaml` < `config/profiles/*.yaml` < 用户配置 < CLI。OpenClaw 负责选择币种、调用频率和 Telegram 投递；Skill 自身不调度、不发送消息。

## 安全边界

- 默认 `trading_enabled: false`、`testnet: true`、`require_human_confirmation: true`。
- v0.2.0 仅提供 Binance Spot 适配器；不支持合约、杠杆、借币、做空、提现或划转。
- 密钥只从配置指定的环境变量读取，禁止写入 YAML、日志、报告或仓库。
- 真实委托必须按 candidate → validate-entry → draft → 用户确认 → place → query status → record 流程执行。
- 超时后只查询状态，不盲目重试；客户端订单号用于防重复。
- 所有输出仅供研究，不保证收益，不构成投资建议。

迁移说明见 [MIGRATION-v0.2.0.md](MIGRATION-v0.2.0.md)，详细规则见 `references/`。
