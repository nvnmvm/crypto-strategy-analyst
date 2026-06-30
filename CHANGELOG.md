# Changelog

All notable changes follow Keep a Changelog. Versions use Semantic Versioning.

## [0.1.0] - 2026-06-30

### Added

- Public Binance spot OHLCV ingestion for BTC/USDT and ETH/USDT.
- Deterministic multi-timeframe analysis, support/resistance zones, signals, risk sizing, reports, and time-forward backtests.
- OpenClaw Skill metadata, install instructions, tests, static checks, and CI.
- Shared `evaluate_setup_at_time` path for current-time analysis and strict 1d/4h/1h replay.
- Atomic JSON persistence for daily loss locks and cross-day drawdown state.
- Touch cooldowns with separate reaction and break evidence.

### Fixed

- Prevented TP1/TP2 from crossing the nearest resistance and downgraded setups without a feasible second target.
- Renamed fixed chronological output from `walk_forward_splits` to `time_splits`.
