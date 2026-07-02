# Data sources

Implemented public sources:

- Binance public spot candles, ticker and exchange information.
- Binance public perpetual funding and open interest.
- Binance public ETH/BTC, BNB/BTC, SOL/BTC and SOL/ETH daily relative returns.
- CoinGecko public global BTC market-cap dominance.

Pluggable interfaces exist for ETF flows, macro events, aggregate liquidations, gas, staking, chain activity, SOL network status, BNB platform risk and ecosystem context. No stable unauthenticated provider is configured for these fields, so they return `not_available` and may be supplied by the caller through JSON.

Every data point carries status, source, observed time, freshness and value. Valid states are `available`, `stale`, `not_available` and `failed`. Stale or future observations are excluded from scoring.

Directory datasets contain a manifest, software version, source, time range, trading rules, auxiliary context, individual timeframe files and SHA-256 hashes.
