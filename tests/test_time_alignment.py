from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from crypto_strategy_analyst.analysis import analyze_frames_at_time
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.report import analysis_markdown
from crypto_strategy_analyst.strategy import (
    align_evaluation_time,
    evaluate_setup_at_time,
    prepare_market_frames,
)


def test_request_at_1530_aligns_to_1200():
    requested = datetime(2026, 6, 30, 15, 30, tzinfo=UTC)
    assert align_evaluation_time(requested) == datetime(2026, 6, 30, 12, tzinfo=UTC)


def test_request_at_1601_aligns_to_1600():
    requested = datetime(2026, 6, 30, 16, 1, tzinfo=UTC)
    assert align_evaluation_time(requested) == datetime(2026, 6, 30, 16, tzinfo=UTC)


def test_exact_boundary_is_a_completed_close_instant():
    requested = datetime(2026, 6, 30, 16, 0, tzinfo=UTC)
    assert align_evaluation_time(requested) == requested


def test_all_timeframes_stop_at_shared_evaluation_time(market_frames):
    config = AppConfig()
    requested = (market_frames["1d"].index[220] + pd.Timedelta(hours=15, minutes=30))
    evaluation = evaluate_setup_at_time(
        prepare_market_frames(market_frames, config),
        config,
        requested_at=requested.to_pydatetime(),
    )

    assert evaluation.evaluation_time.hour == 12
    durations = {"1d": pd.Timedelta(days=1), "4h": pd.Timedelta(hours=4), "1h": pd.Timedelta(hours=1)}
    for timeframe, duration in durations.items():
        close_times = evaluation.frames[timeframe].index + duration
        assert close_times.max() <= pd.Timestamp(evaluation.evaluation_time)
    assert evaluation.frames["1h"].index[-1] + pd.Timedelta(hours=1) == pd.Timestamp(
        evaluation.evaluation_time
    )
    assert evaluation.frames["1d"].index[-1] + pd.Timedelta(days=1) <= pd.Timestamp(
        evaluation.evaluation_time
    )


def test_report_exposes_request_evaluation_and_cutoffs(market_frames):
    requested = market_frames["1d"].index[220] + pd.Timedelta(hours=15, minutes=30)
    report = analyze_frames_at_time(
        "BTC/USDT",
        market_frames,
        AppConfig(),
        evaluated_at=requested.to_pydatetime(),
    )

    assert report.requested_at == requested.to_pydatetime()
    assert report.evaluation_time == requested.floor("4h").to_pydatetime()
    assert report.evaluation_timeframe == "4h"
    assert report.time_alignment_applied is True
    assert all(
        cutoff <= report.evaluation_time
        for cutoff in report.latest_completed_candle_close.values()
    )
    markdown = analysis_markdown(report)
    assert "请求分析时间（UTC）" in markdown
    assert "实际策略评估时间（UTC）" in markdown
    assert "最新完整日线截止" in markdown
    assert "最新完整 4 小时线截止" in markdown
    assert "最新完整 1 小时线截止" in markdown


def test_one_hour_bars_after_common_time_cannot_change_signal(market_frames):
    config = AppConfig()
    requested = market_frames["1d"].index[220] + pd.Timedelta(hours=15, minutes=30)
    baseline = evaluate_setup_at_time(
        prepare_market_frames(market_frames, config),
        config,
        requested_at=requested.to_pydatetime(),
    )
    changed_frames = {timeframe: frame.copy() for timeframe, frame in market_frames.items()}
    evaluation_time = pd.Timestamp(baseline.evaluation_time)
    hidden_one_hour = changed_frames["1h"].index + pd.Timedelta(hours=1) > evaluation_time
    changed_frames["1h"].loc[hidden_one_hour, ["open", "high", "low", "close"]] *= 100
    changed_frames["1h"].loc[hidden_one_hour, "volume"] *= 100
    changed = evaluate_setup_at_time(
        prepare_market_frames(changed_frames, config),
        config,
        requested_at=requested.to_pydatetime(),
    )

    assert changed.decision == baseline.decision
    assert changed.trends == baseline.trends
