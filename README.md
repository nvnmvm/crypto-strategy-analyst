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
openclaw skills install git:nvnmvm/crypto-strategy-analyst@v0.1.2
python3 -m pip install ~/.openclaw/workspace/skills/crypto-strategy-analyst
openclaw skills list
```

全局安装时使用 `--global`，代码通常位于 `~/.openclaw/skills/crypto-strategy-analyst`。Git 安装不会由 `openclaw skills update` 自动更新；升级时重新安装明确的 tag。

## 使用

```bash
crypto-strategy-analyst analyze --symbol BTC/USDT --output-dir outputs
crypto-strategy-analyst analyze --symbol ETH/USDT --output-dir outputs
crypto-strategy-analyst compare --symbols BTC/USDT ETH/USDT --output-dir outputs
crypto-strategy-analyst fetch-dataset --symbol BTC/USDT --start 2021-01-01 --end 2025-12-31 --output-dir data/btc
crypto-strategy-analyst backtest --dataset-dir data/btc --output-dir outputs
crypto-strategy-analyst backtest --symbol BTC/USDT --start 2021-01-01 --end 2025-12-31 --output-dir outputs
crypto-strategy-analyst risk initialize --equity-cny 1000
crypto-strategy-analyst risk status
crypto-strategy-analyst risk update-equity --equity-cny 950
crypto-strategy-analyst risk record-trade --trade-id manual-btc-20260701-001 --pnl-cny -10 --stopped-out
crypto-strategy-analyst risk history --limit 20
crypto-strategy-analyst risk reset-daily
crypto-strategy-analyst position --symbol BTC/USDT --entry 100000 --stop 97000 --risk-state state/risk-state.json
crypto-strategy-analyst latest --output-dir outputs
```

默认参数在 `config/default.yaml`，示例覆盖在 `config/example.yaml`。核心逻辑在 `src/crypto_strategy_analyst`；`scripts` 只提供薄入口。

所有策略请求先对齐到最近一个已完成的 UTC 4 小时收盘点；日线、4 小时线和 1 小时线统一裁剪到该时刻，并逐周期核对预期与实际最新收盘。边界后 90 秒宽限期内最多重试 3 次、间隔 20 秒；仍陈旧则强制 `no_trade`。索引始终表示开盘时间，收盘时间为开盘时间加周期长度。回测信号只在下一根 4 小时线有效，并按实际开盘价重新验证入场区间、跳空和至少 2R 空间。

风险状态默认保存到 `state/risk-state.json`，追加式审计日志为 `state/risk-events.jsonl`。状态 v2 保存最近 1000 个已处理 trade-id；重复提交在同一文件锁事务内拒绝。旧状态迁移前自动备份。写入采用带超时的 POSIX 文件锁、`fsync` 和原子替换，支持 Linux/macOS 多进程并发；文件损坏时失败关闭。配置中的 `account_equity_cny` 只用于首次安全初始化，不会覆盖后续实际权益。

仓位建议从 Binance 公共 `exchangeInfo` 读取价格 tick、数量 step、最小数量和最小名义金额，只向下取整且不会突破风险上限；不使用 API Key。离线数据集以 SHA-256 manifest 固化 1d/4h/1h 数据与交易规则，离线回测不会联网。

回测输出的 `time_splits` 只是固定 60%/20%/20% 时间切分，不是滚动 walk-forward，也不进行自动参数优化。少于 30 笔交易会明确标记样本不足；报告同时给出基础、双倍手续费、双倍滑点和两者同时翻倍的敏感度结果。

## 质量检查

```bash
ruff check .
pytest
python -m pip check
python -m build
python /path/to/skill-creator/scripts/quick_validate.py .
```

版本采用 SemVer；发行记录见 `CHANGELOG.md`。建议每次 GitHub Release 使用不可变 tag，并在升级前复跑回测与无未来函数测试。
