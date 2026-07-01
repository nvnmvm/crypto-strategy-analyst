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
3. Load the v3 materialized account state before analysis. Use its cash, reserved cash, positions, aggregate open risk, and current equity for sizing. Every mutation must go through the idempotent command handler and append an account event; never edit state directly. Treat corrupt state or WAL as a hard error, and reset only daily fields when the UTC date changes.
4. Validate UTC ordering, duplicates, OHLC consistency, time gaps, minimum history, and the expected latest close for every timeframe. If any required timeframe is stale, missing, invalid, or has a gap, stop trade-candidate generation and report the data problem.
5. Align every request to the latest completed UTC 4h close, then call the shared `evaluate_setup_at_time` workflow: six-state market regime, closed daily trend/levels, closed 4h setup, closed 1h confirmation, deterministic weighted score, tiered targets, risk controls, position size, then report. Backtests must call the same evaluator.
6. Route bull trend/pullback/range to trend pullback, breakout-retest, or continuation; ordinary bear trend is `no_trade`. Bear reversal is allowed only after deep drawdown plus a strong higher-low/reclaim structure; oversold RSI alone never qualifies.
7. Require one strong confirmation or 2 weighted points. A-tier plans need two targets and at least 2R; B-tier plans may use one target at 1.6R, must be reduced risk, and cannot be a strong candidate. Derive the allowed entry range from immutable stop/targets and revalidate every pending open. Bear accumulation is capped at two independently confirmed entries and may never average down.
8. Save a timestamped JSON and Chinese Markdown report. Include UTC generation time, Binance public-data provenance, missing optional sources as `not_available`, and the disclaimer “策略研究结果，不是收益保证，也不是投资建议”。

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

Diagnose the exact blocker funnel or compare the four preregistered versions:

```bash
crypto-strategy-analyst research diagnose --dataset-dir ./data/btc --output-dir ./outputs/diagnosis
crypto-strategy-analyst research compare-strategies --dataset-dir ./data/btc --output-dir ./outputs/research --with-cost-sensitivity
```

Initialize and maintain the locked persistent risk state:

```bash
crypto-strategy-analyst risk initialize --equity-cny 1000
crypto-strategy-analyst risk status
crypto-strategy-analyst risk update-equity --equity-cny 950
crypto-strategy-analyst risk record-trade --trade-id manual-btc-20260701-001 --pnl-cny -10 --stopped-out
crypto-strategy-analyst risk history --limit 20
```

Return the last saved report without reinterpreting it:

```bash
python3 "{baseDir}/scripts/generate_report.py" --latest --output-dir ./outputs
```

Read `{baseDir}/references/strategy-definition.md`, `{baseDir}/references/strategy-selection-v0.1.3.md`, `{baseDir}/references/parameter-registry.md`, `{baseDir}/references/backtest-assumptions.md`, `{baseDir}/references/risk-rules.md`, and `{baseDir}/references/evidence-register.md` when explaining results or changing rules. Validate machine output against `{baseDir}/schemas/analysis-report.schema.json`.

Never turn a score or candidate into an order. State timestamps, sources, missing data, invalidation conditions, and limitations. Do not claim profit is likely or guaranteed.
