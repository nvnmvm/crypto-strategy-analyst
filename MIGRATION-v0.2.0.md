# Migration to v0.2.0

v0.2.0 replaces the v0.1.x research application with a smaller OpenClaw-oriented public engine.

## Breaking changes

- Top-level CLI is now exactly: `analyze`, `compare`, `validate-entry`, `fetch-dataset`, `backtest`, `research`, `portfolio`, `journal`, `exchange`.
- Removed top-level `fetch`, `indicators`, `structure`, `levels`, `position`, `latest`, and `risk` commands and all standalone `scripts/` wrappers.
- Removed named frozen strategy variants. Strategies are now modular toggles: support rebound, breakout retest, trend pullback, range reversal, bear reversal and bear accumulation.
- Account WAL, event-sourced materialization, expected versions, duplicate risk stores and processed-command cache are gone. Paper state uses `state/paper-account.json` plus `state/paper-trades.jsonl` with locking, fsync, backup and atomic replacement.
- Old reference material is preserved under `docs/archive/v0.1.3/` but is not loaded by OpenClaw by default.
- Configuration is split across default, asset profiles and optional local override. Never copy API keys into these files.

## Measured baseline

The v0.1.3 baseline at `793d65d5387214f38dec8ba1c15a2148b9e9c91b` had 6,956 physical production Python lines, 23 source modules, 12 top-level commands (20 including nested commands), 81 recursive configuration leaf fields, 112 collected tests, and a 117,230-byte wheel. Final v0.2.0 measurements are produced by CI/release checks and recorded in the release report.

The v0.2.0 release candidate has 1,697 physical production Python lines, 25 deliberately smaller source modules, 9 top-level commands (24 including nested commands), 39 configuration leaf fields, 45 collected tests, and a 40,082-byte wheel. Production lines fell 75.6%, configuration fields fell 51.9%, and wheel size fell 65.8%. The module count rose by two because the required five Profile files and five exchange-adapter files are isolated safety boundaries rather than merged monoliths.

## Trading compatibility

Unlike v0.1.x, v0.2.0 includes a generic exchange contract and Binance Spot implementation. It remains fail-closed: real trading is disabled, testnet is on, human confirmation is mandatory, futures are rejected, and no withdrawal or transfer interface exists.
