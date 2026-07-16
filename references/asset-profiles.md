# Asset Profiles

Every Profile implements context evaluation, score adjustment, hard filters, strategy filtering, parameter adjustment and risk adjustment.

- BTC emphasizes weekly/daily structure. Crowded positive funding plus open-interest expansion reduces confidence; ETF outflows and macro risk affect swing/long plans; liquidation context is secondary only.
- ETH combines ETH/BTC, BTC context, gas, staking, ETF flow and on-chain activity. Relative weakness or conflicting BTC context reduces confidence and risk.
- BNB prioritizes support rebound and range/breakout structure. Severe Binance platform risk is a hard filter; Launchpool activity never creates a signal alone.
- SOL uses wider structural buffers, stricter volume/breakout requirements and lower risk suggestions. Severe network status is a hard filter; SOL/BTC and SOL/ETH confirmation strengthens relative score.
- Generic verifies pair/listing context, data integrity, liquidity, spread and volatility where supplied. It has limited confidence and does not borrow dedicated-asset rules.

Unavailable context is reported, not fabricated. Callers may provide external context as typed JSON data points.
