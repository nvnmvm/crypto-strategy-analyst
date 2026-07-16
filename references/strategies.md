# Strategies

All strategy detectors are pure functions and return `matched`, structural confirmations, secondary confirmations, failed conditions, entry range, structural stop, targets, reward/risk and invalidation.

- `support_rebound`: confirmed support proximity, valid reaction structure, secondary evidence and target space.
- `breakout_retest`: closed breakout beyond the ATR threshold, volume expansion, a later retest that holds, and renewed upward confirmation. The breakout candle alone never qualifies.
- `trend_pullback`: bullish higher timeframe, meaningful pullback, intact swing structure, trend-support proximity and recovery confirmation.
- `range_reversal`: an identified range, reacted lower boundary, no valid downside break and reversal confirmation with space to midpoint/high.
- `bear_reversal`: deep drawdown, higher low, local downtrend break and improving secondary evidence. Oversold RSI alone is insufficient.
- `bear_accumulation`: long horizon only and disabled by default. Confirmation-only mode requires new structure evidence; it never appears as a short plan.

Entry upper bounds are solved from target, stop and minimum reward/risk. One reliable target is valid; TP2 may be absent. Targets never cross known resistance without being capped or explained.
