from __future__ import annotations

from itertools import pairwise

from crypto_strategy_analyst.backtest import run_backtest
from crypto_strategy_analyst.config import AppConfig


def test_backtest_is_finite_and_time_forward(ohlcv):
    result = run_backtest(ohlcv, "BTC/USDT", AppConfig())
    metrics = result.metrics
    assert result.final_equity_cny > 0
    assert -1 <= metrics.total_return < 100
    assert 0 <= metrics.max_drawdown <= 1
    assert metrics.total_fees >= 0
    assert metrics.slippage_cost >= 0
    for trade in result.trades:
        assert trade.exit_time >= trade.entry_time
        assert trade.quantity > 0


def test_backtest_trades_do_not_overlap(ohlcv):
    result = run_backtest(ohlcv, "ETH/USDT", AppConfig())
    ordered = sorted(result.trades, key=lambda item: item.entry_time)
    for previous, current in pairwise(ordered):
        assert current.entry_time >= previous.exit_time
    assert set(result.walk_forward_splits) == {"train", "validation", "test"}
