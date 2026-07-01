# Asset profiles

- BTC: weekly/daily emphasis; dominance, funding, open interest, liquidations, ETF flow and macro context; wider stops and stricter chasing.
- ETH: ETH/BTC, gas, staking, ETF, on-chain and BTC context.
- BNB: BNB/BTC, Binance platform risk, Launchpool and chain activity. Severe Binance platform risk is a hard filter.
- SOL: SOL/BTC, SOL/ETH, on-chain, network health, ecosystem/memecoin activity, funding and open interest. Severe network events are a hard filter; sizing is lower and stops wider.
- Generic: listing/pair status, data sufficiency, liquidity, spread and ATR. Confidence is capped and size reduced; unsupported symbols never block supported assets.

`auto` selection is deterministic. A user may force a profile, but the report records the selected profile.
