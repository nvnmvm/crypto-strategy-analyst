# Analysis engine

`evaluate_setup_at_time` is the sole strategy entry point for current analysis and historical replay. A `MarketSnapshot` exposes only candles whose `close_time <= as_of`; future auxiliary observations are also excluded.

The engine calculates EMA, RSI, MACD histogram, ATR, volume ratio and trend strength; classifies `strong_bull`, `bullish`, `bull_pullback`, `range`, `bearish`, `capitulation` or `recovery`; constructs multi-source price zones; evaluates every enabled strategy independently; then produces separate short, swing and long plans.

Market regime changes allowed strategies, confidence, minimum reward/risk and risk suggestions. Scores rank and explain plans but cannot bypass missing required data, absent structural confirmation, hard Profile filters, invalid stops or insufficient target space.

Missing auxiliary data is represented by `null` component scores. Data completeness constrains confidence rather than silently assigning a neutral 50.
# Analysis engine

## Chart-pattern rules

The engine recognizes five compact patterns: double bottom, double top, inverse
head-and-shoulders, head-and-shoulders and a confirmed compressed-triangle breakout.
Detection is swing based, uses a fixed ATR-scaled tolerance for comparable highs/lows,
and reads completed candles only.

- `forming` means the geometry exists but price has not closed through its neckline.
- `confirmed` requires a completed close beyond the neckline by 0.3 ATR.
- `invalidated` means price crossed the structural invalidation point before confirmation.

Bullish confirmed patterns may add a structural confirmation, but never replace trend,
target-space, stop or reward/risk checks. Confirmed bearish patterns create a risk alert
and suppress long candidates. The Skill remains analysis-only and does not create short
orders.
