from __future__ import annotations

from datetime import timedelta

from crypto_strategy_analyst.analysis import analyze_frames_at_time
from crypto_strategy_analyst.backtest import run_backtest
from crypto_strategy_analyst.config import AppConfig


def test_realtime_and_backtest_use_identical_evaluation(market_frames):
    config = AppConfig()
    observed = []
    start = market_frames["1d"].index[220] + timedelta(days=1)

    run_backtest(
        market_frames,
        "BTC/USDT",
        config,
        start=start.to_pydatetime(),
        end=(start + timedelta(hours=12)).to_pydatetime(),
        decision_observer=lambda timestamp, evaluation: observed.append((timestamp, evaluation)),
    )

    assert observed
    timestamp, replay_evaluation = observed[0]
    realtime_report = analyze_frames_at_time(
        "BTC/USDT",
        market_frames,
        config,
        evaluated_at=timestamp,
    )
    decision = replay_evaluation.decision
    assert realtime_report.signal == decision.label
    assert realtime_report.signal_score == decision.score
    assert realtime_report.stop_loss == (decision.stop_loss or "not_available")
    assert realtime_report.take_profit_1 == (decision.take_profit_1 or "not_available")
    assert realtime_report.take_profit_2 == (decision.take_profit_2 or "not_available")
    assert realtime_report.daily_trend == replay_evaluation.trends["1d"]
    assert realtime_report.four_hour_trend == replay_evaluation.trends["4h"]
