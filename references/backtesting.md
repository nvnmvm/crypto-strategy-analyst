# Backtesting

Backtests replay 4h decision times and call the same public evaluator as current analysis. At each timestamp, 1w, 1d, 4h, 1h and optional 15m inputs are cropped to already-closed bars. Tests compare live and replay output at the same historical timestamp and inject future spikes to detect leakage.

Default cost assumptions are 10 bps fee and 5 bps one-way slippage. Entries and exits use conservative adverse slippage. The 60%/20%/20% chronological report field is named `time_splits`; it is not described as walk-forward. The `research walk-forward` command is a diagnostic surface and does not automatically optimize parameters.

Backtests are research evidence, not a profit forecast. A small trade count, missing delisted-symbol history, survivor bias, external-data gaps, venue changes and simplified fill logic must be disclosed.
