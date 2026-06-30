---
name: crypto-strategy-analyst
description: Analyze BTC/ETH public spot data, support/resistance, deterministic candidate signals, risk sizing, reports, and no-lookahead backtests; never place trades.
metadata: {"openclaw":{"emoji":"📊","homepage":"https://github.com/nvnmvm/crypto-strategy-analyst","requires":{"bins":["python3"]}}}
---

# Crypto Strategy Analyst

Use this Skill for public-data cryptocurrency spot research: multi-timeframe BTC/USDT or ETH/USDT analysis, support/resistance zones, candidate signals, position sizing, historical backtests, latest-report retrieval, and BTC-vs-ETH comparison.

Do not use it for live orders, private exchange APIs, API keys, leverage, futures, borrowing, short selling, high-frequency execution, guaranteed-return claims, or discretionary model-generated trade instructions.

## Required workflow

1. Check Python and dependencies with `python3 -c "import sys, crypto_strategy_analyst; assert sys.version_info >= (3, 11)"`. If unavailable, stop and ask the operator to use Python 3.11+ and run `python3 -m pip install '{baseDir}'`; never install packages silently.
2. Fetch only public Binance spot OHLCV through `{baseDir}/scripts/fetch_market_data.py` or run the complete pipeline with `{baseDir}/scripts/analyze_market.py`.
3. Validate UTC ordering, duplicates, OHLC consistency, time gaps, and minimum history before analysis. If any required timeframe is invalid or has a gap, stop trade-candidate generation and report the data problem.
4. Evaluate in fixed order: daily trend, daily levels, four-hour setup, one-hour confirmation, deterministic score, reward/risk, risk controls, position size, then report.
5. Treat 1h only as confirmation. Never let it override a bearish daily trend.
6. Require at least two entry confirmations, reward/risk of at least 2:1, sufficient space to resistance, no daily stop, no daily loss lock, and no drawdown lock.
7. Save a timestamped JSON and Chinese Markdown report. Include UTC generation time, Binance public-data provenance, missing optional sources as `not_available`, and the disclaimer “策略研究结果，不是收益保证，也不是投资建议”。

## Commands

Run a full analysis:

```bash
python3 "{baseDir}/scripts/analyze_market.py" --symbol BTC/USDT --config "{baseDir}/config/default.yaml" --output-dir ./outputs
```

Compare supported symbols:

```bash
crypto-strategy-analyst compare --symbols BTC/USDT ETH/USDT --config "{baseDir}/config/default.yaml" --output-dir ./outputs
```

Run a strict time-forward backtest:

```bash
python3 "{baseDir}/scripts/run_backtest.py" --symbol BTC/USDT --start 2021-01-01 --end 2025-12-31 --config "{baseDir}/config/default.yaml" --output-dir ./outputs
```

Return the last saved report without reinterpreting it:

```bash
python3 "{baseDir}/scripts/generate_report.py" --latest --output-dir ./outputs
```

Read `{baseDir}/references/strategy-rules.md`, `{baseDir}/references/risk-rules.md`, and `{baseDir}/references/backtest-rules.md` when explaining results or changing rules. Validate machine output against `{baseDir}/schemas/analysis-report.schema.json`.

Never turn a score or candidate into an order. State timestamps, sources, missing data, invalidation conditions, and limitations. Do not claim profit is likely or guaranteed.
