# Backtesting and research

The strict replay sequence is: primary timeframe close → shared analysis engine → candidate → next primary bar actual open validation → fill or cancellation → subsequent OHLC evaluation.

Validation never moves the original stop, targets or entry range. It cancels expired plans, out-of-range opens, opens beyond stop/target, low reward/risk or new hard risk.

Replay handles adverse fees/slippage, gap cancellation, partial targets, optional break-even stop after TP1, time exits and end-of-data closure. If a bar touches stop and target without lower-timeframe ordering evidence, stop is applied first.

Time splits use configured calendar dates. Data through 2026-07-01 is labeled historical replay, not a pristine unseen test set. Post-freeze observations are separated for genuine forward validation.

Research commands return real candidate funnels, grouped attribution, component/strategy ablation, frozen-parameter rolling windows, cost scenarios, parameter neighborhoods and a finite preregistered configuration comparison. They do not optimize parameters automatically.

Metrics include return, annualized return, drawdown, trade count, win rate, win/loss averages, payoff, expectancy R, Profit Factor, Sharpe, Sortino, Calmar, fees, holding time, MFE, MAE and concentration. Fewer than the configured minimum trades is marked `sample_size_insufficient`.
