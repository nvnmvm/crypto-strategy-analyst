from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from crypto_strategy_analyst.backtest import run_backtest
from crypto_strategy_analyst.config import AppConfig


def test_backtest_is_finite_and_time_forward(market_frames):
    result = run_backtest(market_frames, "BTC/USDT", AppConfig())
    metrics = result.metrics
    assert result.final_equity_cny > 0
    assert -1 <= metrics.total_return < 100
    assert 0 <= metrics.max_drawdown <= 1
    assert metrics.total_fees >= 0
    assert metrics.slippage_cost >= 0
    for trade in result.trades:
        assert trade.exit_time >= trade.entry_time
        assert trade.quantity > 0


def test_backtest_trades_do_not_overlap(market_frames):
    result = run_backtest(market_frames, "ETH/USDT", AppConfig())
    ordered = sorted(result.trades, key=lambda item: item.entry_time)
    for previous, current in pairwise(ordered):
        assert current.entry_time >= previous.exit_time
    assert set(result.time_splits) == {"train", "validation", "test"}
    assert "walk_forward_splits" not in result.model_dump()
    assert result.config["parameter_optimization"] is False


def test_backtest_has_no_independent_entry_setup():
    source = (
        Path(__file__).parents[1] / "src" / "crypto_strategy_analyst" / "backtest.py"
    ).read_text(encoding="utf-8")
    assert "_entry_setup" not in source
    assert "evaluate_setup_at_time" in source
