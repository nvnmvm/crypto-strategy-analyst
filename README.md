# crypto-strategy-analyst

一个只做研究、不做下单的 OpenClaw Skill。它使用 Binance 公开现货 K 线，对 BTC/USDT、ETH/USDT 做日线/4 小时/1 小时分析，输出确定性候选信号、风控仓位、中文 Markdown、JSON 和严格时间推进回测。

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
openclaw skills install git:nvnmvm/crypto-strategy-analyst@v0.1.0
python3 -m pip install ~/.openclaw/workspace/skills/crypto-strategy-analyst
openclaw skills list
```

全局安装时使用 `--global`，代码通常位于 `~/.openclaw/skills/crypto-strategy-analyst`。Git 安装不会由 `openclaw skills update` 自动更新；升级时重新安装明确的 tag。

## 使用

```bash
crypto-strategy-analyst analyze --symbol BTC/USDT --output-dir outputs
crypto-strategy-analyst analyze --symbol ETH/USDT --output-dir outputs
crypto-strategy-analyst compare --symbols BTC/USDT ETH/USDT --output-dir outputs
crypto-strategy-analyst backtest --symbol BTC/USDT --start 2021-01-01 --end 2025-12-31 --output-dir outputs
crypto-strategy-analyst latest --output-dir outputs
```

默认参数在 `config/default.yaml`，示例覆盖在 `config/example.yaml`。核心逻辑在 `src/crypto_strategy_analyst`；`scripts` 只提供薄入口。

## 质量检查

```bash
ruff check .
pytest
python /path/to/skill-creator/scripts/quick_validate.py .
```

版本采用 SemVer；发行记录见 `CHANGELOG.md`。建议每次 GitHub Release 使用不可变 tag，并在升级前复跑回测与无未来函数测试。
