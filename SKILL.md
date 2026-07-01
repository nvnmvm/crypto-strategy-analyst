---
name: crypto-strategy-analyst
description: Analyze any Binance spot pair with BTC/ETH/BNB/SOL asset profiles, independent short/swing/long plans, no-lookahead backtests, paper portfolio, manual journal, and an opt-in human-confirmed Spot adapter.
metadata: {"openclaw":{"emoji":"📊","homepage":"https://github.com/nvnmvm/crypto-strategy-analyst","requires":{"bins":["python3"]}}}
---

# Crypto Strategy Analyst

Use this Skill for public-market analysis, cross-asset comparison, deterministic historical replay, a local paper account, or a manual trade journal. OpenClaw chooses symbols, frequency and message delivery. This Skill never schedules itself and never sends Telegram messages.

## Required workflow

1. Verify Python 3.11+ and package availability. If missing, ask the operator to install this directory; do not silently install dependencies.
2. Select `auto` unless the user explicitly overrides the profile. Auto maps BTC, ETH, BNB and SOL to dedicated profiles and every other symbol to `generic`.
3. Require closed spot candles, current price, trading rules, timestamp and volume. Missing required data means `no_trade`; missing important auxiliary context lowers confidence; background data is `not_available`.
4. Call the same `evaluate_setup_at_time` engine for live and historical work. Never expose a candle whose close time is later than the evaluation time.
5. Report separate short (4h/1h/optional 15m), swing (1d/4h/1h), and long (1w/1d/4h) plans. Preserve hard filters even when the score is high.
6. Never place a target through key resistance. If resistance leaves less than 2R, return `watch` or `no_trade`; if TP2 is not honest, downgrade instead of inventing 3R.
7. Return schema 2.0 JSON or concise Chinese Markdown with profile, market, data availability, component scores, confidence, levels, relative strength, plans, events, warnings and limitations.
8. State that output is research only, is not a profit guarantee, and is not investment advice.

## Commands

```bash
crypto-strategy-analyst analyze BTC/USDT --profile auto --format json
crypto-strategy-analyst compare BTC/USDT ETH/USDT BNB/USDT SOL/USDT
crypto-strategy-analyst fetch-dataset BTC/USDT ./data/btc.json
crypto-strategy-analyst backtest ./data/btc.json --profile auto
crypto-strategy-analyst validate-entry ./outputs/report.json --horizon swing
crypto-strategy-analyst portfolio show
crypto-strategy-analyst journal list
```

Read `{baseDir}/references/analysis-engine.md`, `{baseDir}/references/asset-profiles.md`, `{baseDir}/references/risk-and-execution.md`, and `{baseDir}/references/backtesting.md` when explaining or changing the rules.

## Real-order boundary

Real Binance Spot access is optional and disabled by default. Never ask a user to paste credentials. Keys must be in the configured environment variables. Futures, margin, leverage, short selling, transfers and withdrawals are unsupported.

Only continue from `exchange draft` to `exchange place` after OpenClaw shows the complete draft and the user explicitly confirms it. Enforce testnet-first, whitelist, notional/risk limits, price-deviation limits, expiring one-time confirmation tokens, client order IDs, duplicate checks, status checks and emergency stop. On timeout, query status and do not blindly retry.
