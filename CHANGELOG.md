# Changelog

All notable changes follow Keep a Changelog. Versions use Semantic Versioning.

## [0.1.3] - 2026-07-01

### Added

- Book-to-requirement distillation, objective strategy definitions, parameter registry, backtest assumptions, robustness protocol, monitoring rules, and evidence levels.
- Unified v3 account materialized state, append-only account events, idempotent versioned commands, pending plans, portfolio cash/positions, aggregate open risk, WAL recovery, and v2 migration backups.
- Separate support and entry zones, bounded public-request timeouts/backoff/circuit breaking, explicit exchange-rule degradation, research audit fields, and full-manifest hashing.
- Six deterministic market regimes; separate short-, medium-, and long-horizon plans; weighted confirmations; support rebound, breakout-retest, continuation, and guarded bear-reversal setups.
- A/B target tiers, execution-R cushion, cost-derived allowed entry ranges, two-entry bear cap without averaging down, time exits, rolling frozen-parameter windows, concentration metrics, and cost-aware buy/hold and DCA benchmarks.
- `research diagnose` and `research compare-strategies` commands with candidate funnels, blockers by regime, cancellation reasons, fixed calendar holdouts, and all four preregistered strategy versions.

### Fixed

- Made simulated buy/sell tick rounding conservative and renamed fixed 60/20/20 output to `chronological_holdout_split`.
- Applied cash, per-symbol deployment, total deployment, exchange minimum, and portfolio-risk limits to position suggestions.
- Corrected B-tier next-open validation to use 1.6R and made two-bar pending plans actually survive only non-terminal first-open misses.
- Removed a backtest risk-state double count that could preserve a phantom peak equity after closing a marked-to-market position and falsely activate the drawdown lock.

### Security

- The package still has no private API, API keys, live orders, leverage, futures, margin, shorting, withdrawals, martingale, or grid averaging down.

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
