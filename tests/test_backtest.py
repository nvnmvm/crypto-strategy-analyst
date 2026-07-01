from crypto_strategy_analyst.backtest import run_backtest
from crypto_strategy_analyst.config import AppConfig


def test_backtest_uses_time_splits_not_fake_walk_forward(snapshot_factory):
    result = run_backtest(snapshot_factory(), AppConfig())
    assert set(result.time_splits) == {"train", "validation", "test"}
    assert "walk_forward" not in result.as_dict()
    assert result.start_equity == 600


def test_backtest_is_deterministic(snapshot_factory):
    snapshot = snapshot_factory()
    assert (
        run_backtest(snapshot, AppConfig()).as_dict()
        == run_backtest(snapshot, AppConfig()).as_dict()
    )
