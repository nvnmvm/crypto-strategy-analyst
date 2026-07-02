---
name: crypto-strategy-analyst
description: Analyze caller-selected crypto markets with dedicated BTC/ETH/BNB/SOL profiles, independent short/swing/long plans, strict historical replay, entry validation, research diagnostics, and OpenClaw events.
---

# Crypto Strategy Analyst

Use this Skill when OpenClaw needs public-market structure, key levels, near-level alerts, candidate plans, immutable next-bar validation, historical replay, or strategy research for caller-selected symbols.

OpenClaw owns symbol selection, scheduling, alert deduplication, follow-up timing and message delivery. This Skill does not schedule itself or send messages.

## Workflow

1. Use `--profile auto` unless the caller explicitly overrides it. BTC, ETH, BNB and SOL use dedicated Profiles; every other symbol uses Generic with limited confidence.
2. Require completed 1w, 1d, 4h and 1h candles plus public trading rules. Missing required data forces `no_trade`.
3. Treat missing derivatives, relative-strength, macro, ETF or on-chain context as `not_available`; never replace it with a neutral score.
4. Call the shared `evaluate_setup_at_time` path for current and historical analysis. Never expose a candle closed after the evaluation time.
5. Keep short, swing and long plans independent. A strategy name may appear only when its detector actually matches.
6. Require at least one structural confirmation. RSI, funding, flows or chain activity are secondary evidence only.
7. Respect structural stops, resistance-aware targets and the configured minimum reward/risk. Downgrade insufficient space to `watch`.
8. Return schema 3.0 JSON or concise Chinese Markdown, including data availability, scores, levels, horizon plans, warnings, limitations and OpenClaw events.

## Commands

```bash
crypto-strategy-analyst analyze BTC/USDT --horizons short swing long --format json
crypto-strategy-analyst compare BTC/USDT ETH/USDT SOL/USDT
crypto-strategy-analyst validate-entry ./outputs/BTC-USDT-report.json --dataset ./data/BTC-USDT --horizon swing
crypto-strategy-analyst fetch-dataset BTC/USDT ./data/BTC-USDT
crypto-strategy-analyst backtest ./data/BTC-USDT
crypto-strategy-analyst research diagnose ./data/BTC-USDT
```

Read `{baseDir}/references/analysis-engine.md`, `{baseDir}/references/asset-profiles.md`, `{baseDir}/references/strategies.md`, `{baseDir}/references/data-sources.md`, and `{baseDir}/references/backtesting.md` when explaining or changing rules.

Research output is not a profit guarantee or investment advice.
