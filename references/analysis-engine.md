# Analysis engine

`evaluate_setup_at_time(snapshot, config, profile)` is the sole strategy evaluator. Live analysis and replay both call it. `MarketSnapshot.completed(timeframe)` excludes every bar with `close_time > as_of`.

The engine emits independent `short`, `swing`, and `long` plans and the statuses `no_trade`, `watch`, `near_key_level`, `candidate`, `entry_validated`, `entry_cancelled`, `position_management`, `exit_signal`, and `risk_alert`. Component scores are technical, derivatives, on-chain, macro, relative strength, and asset-specific. Scores never bypass required-data or asset hard filters.

Support/resistance candidates are pivot clusters. Adjacent touches inside the configured cooldown count once; merged multi-timeframe levels keep the strongest representation instead of adding the same price action repeatedly.

Targets respect both R multiples and observed resistance. Less than 2R room is not tradable. TP2 may be absent, but then the signal is downgraded; the engine never fabricates a 3R target.
