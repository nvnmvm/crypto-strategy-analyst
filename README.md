# crypto-strategy-analyst

一个只做研究、不做下单的 OpenClaw Skill。它使用 Binance 公开现货 K 线，对 BTC/USDT、ETH/USDT 做日线/4 小时/1 小时分析，输出确定性候选信号、持久化风控仓位、中文 Markdown、JSON 和严格三周期时间重放回测。实时分析与回测共用 `evaluate_setup_at_time`，不维护第二套简化策略。

## 安全边界

- 不读取或要求交易所密钥。
- 不调用私有接口，不下单。
- 不使用合约、杠杆、借币、做空。
- 不由大模型自由打分或绕过规则。
- 研究结果不保证收益，不构成投资建议。

## 环境与安装

需要 Python 3.11+。开发安装：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

从 GitHub 安装为当前 OpenClaw workspace Skill：

```bash
openclaw skills install git:nvnmvm/crypto-strategy-analyst@v0.1.3
python3 -m pip install ~/.openclaw/workspace/skills/crypto-strategy-analyst
openclaw skills list
```

全局安装时使用 `--global`，代码通常位于 `~/.openclaw/skills/crypto-strategy-analyst`。Git 安装不会由 `openclaw skills update` 自动更新；升级时重新安装明确的 tag。

## 使用

```bash
crypto-strategy-analyst analyze --symbol BTC/USDT --output-dir outputs
crypto-strategy-analyst analyze --symbol ETH/USDT --output-dir outputs
crypto-strategy-analyst compare --symbols BTC/USDT ETH/USDT --output-dir outputs
crypto-strategy-analyst research diagnose --dataset-dir data/btc --output-dir outputs/diagnosis
crypto-strategy-analyst research compare-strategies --dataset-dir data/btc --output-dir outputs/research
crypto-strategy-analyst fetch-dataset --symbol BTC/USDT --start 2021-01-01 --end 2025-12-31 --output-dir data/btc
crypto-strategy-analyst backtest --dataset-dir data/btc --output-dir outputs
crypto-strategy-analyst backtest --symbol BTC/USDT --start 2021-01-01 --end 2025-12-31 --output-dir outputs
crypto-strategy-analyst risk initialize --equity-cny 1000
crypto-strategy-analyst risk status
crypto-strategy-analyst risk update-equity --equity-cny 950
crypto-strategy-analyst risk record-trade --trade-id manual-btc-20260701-001 --pnl-cny -10 --stopped-out
crypto-strategy-analyst risk history --limit 20
crypto-strategy-analyst risk reset-daily
crypto-strategy-analyst position --symbol BTC/USDT --entry 100000 --stop 97000 --risk-state state/account-state.json
crypto-strategy-analyst latest --output-dir outputs
```

默认参数在 `config/default.yaml`，示例覆盖在 `config/example.yaml`。核心逻辑在 `src/crypto_strategy_analyst`；`scripts` 只提供薄入口。

所有策略请求先对齐到最近一个已完成的 UTC 4 小时收盘点；日线、4 小时线和 1 小时线统一裁剪到该时刻，并逐周期核对预期与实际最新收盘。边界后 90 秒宽限期内最多重试 3 次、间隔 20 秒；仍陈旧则强制 `no_trade`。索引始终表示开盘时间，收盘时间为开盘时间加周期长度。

v0.1.3 将行情确定性分为六种环境，并分开短期（突破回踩/趋势延续，14 日）、中期（支撑反弹，90 日）与长期（熊市结构反转，180 日）计划。确认采用强 2 分、普通 1 分、辅助 0.5 分；至少一个强确认或合计 2 分。A级需要两个目标和开盘至少 2R；B级允许一个目标和至少 1.6R，但风险减半。熊市试探仓风险乘数为 0.25，最多两笔，第二笔不得摊低成本且必须有新的结构确认。

`support_zone`、`allowed_entry_range` 和 `planned_entry_price` 分别表示技术依据、可接受成交区和固定计划价。pending 可配置为 1 或 2 根 4h K线；每个开盘都按不变的 stop/TP 重新验证等级最低R、跳空、环境和失效条件。

账户物化状态默认保存到 `state/account-state.json`，追加式事实记录为 `state/account-events.jsonl`。状态 v3 统一保存现金、保留现金、BTC/ETH 持仓、pending 计划、每日风险、峰值权益、回撤和已处理命令。所有变化经带 `command_id` 与期望版本的统一命令处理器完成；相同命令只生效一次。写入使用 POSIX 文件锁、WAL、`fsync` 和原子替换，崩溃后可恢复且事件不会重复追加；旧 v2 风险文件迁移前备份。

仓位建议从 Binance 公共 `exchangeInfo` 读取价格 tick、数量 step、最小数量和最小名义金额；模拟买价向上取 tick、卖价向下取 tick，数量向下取 step。现金、单币种/总投入和 2% 组合开放风险共同限制仓位。离线 manifest 的 SHA-256 覆盖全部元数据、1d/4h/1h 文件、交易规则、数据源和软件版本；离线回测不会联网。

回测默认按 2019–2021、2022–2023、2024–最新输出固定 `chronological_holdout_split`，并报告冻结参数的 365 日滚动窗口；两者都不冒充自动滚动调参。结果还包含成本敏感度、买入持有、固定总资金月度定投、环境/策略收益和单笔/年度集中度。少于 30 笔会明确标记样本不足。

生产分析与账户仍只允许 BTC/USDT、ETH/USDT。SOL/USDT、BNB/USDT 若出现在研究报告中，只是离线跨资产验证，不会生成实时候选或持久化仓位。

## 质量检查

```bash
ruff check .
pytest
python -m pip check
python -m build
python /path/to/skill-creator/scripts/quick_validate.py .
```

版本采用 SemVer；发行记录见 `CHANGELOG.md`。建议每次 GitHub Release 使用不可变 tag，并在升级前复跑回测与无未来函数测试。
