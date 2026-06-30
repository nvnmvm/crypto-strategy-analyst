# Changelog

All notable changes follow Keep a Changelog. Versions use Semantic Versioning.

## [0.1.2] - 2026-07-01

### Added

- Per-timeframe data-freshness gates with bounded live retries and fail-closed reports.
- Next-4h-open candidate revalidation and explicit cancellation counters/reasons.
- Risk state v2 trade-id idempotency, migration backups, and append-only JSONL audit history.
- Public Binance spot precision/minimum-notional constraints for analysis, sizing, and backtests.
- Checksummed 1d/4h/1h dataset snapshots, fully offline backtests, reproducibility hashes, extended metrics, and cost sensitivity scenarios.
- Wheel asset verification and install smoke tests across Python 3.11, 3.12, and 3.13.

### Security

- The package remains research-only and contains no order placement, private account, API-key, leverage, futures, borrowing, shorting, or withdrawal functionality.

## [0.1.1] - 2026-06-30

### Added

- Shared 4h decision-time alignment with explicit request, evaluation, and per-timeframe cutoff reporting.
- `risk initialize`, `status`, `update-equity`, `record-trade`, and `reset-daily` commands.
- Current account equity, daily starting equity, process-safe file locking, and concurrent update tests.
- Manual GitHub Actions dispatch alongside main pushes and pull requests.

### Fixed

- Prevented 1h confirmations after the common 4h close from leaking into live decisions.
- Sized analysis positions from persisted current equity instead of repeatedly restoring configured equity.

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
