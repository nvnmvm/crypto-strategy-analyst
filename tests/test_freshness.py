from __future__ import annotations

from datetime import timedelta

import pandas as pd

from crypto_strategy_analyst.analysis import analyze_frames_at_time, analyze_symbol
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.freshness import check_data_freshness, expected_latest_close
from crypto_strategy_analyst.models import FreshnessStatus, SignalLabel


def _closed_frames(market_frames, evaluation_time):
    durations = {"1d": pd.Timedelta(days=1), "4h": pd.Timedelta(hours=4), "1h": pd.Timedelta(hours=1)}
    return {
        timeframe: frame.loc[frame.index + durations[timeframe] <= evaluation_time].copy()
        for timeframe, frame in market_frames.items()
    }


def test_required_close_times_are_fresh_and_daily_uses_utc_midnight(market_frames):
    evaluation = market_frames["1d"].index[220] + pd.Timedelta(days=1)
    frames = _closed_frames(market_frames, evaluation)

    result = check_data_freshness(frames, evaluation.to_pydatetime(), ("1d", "4h", "1h"))

    assert all(item.status == FreshnessStatus.FRESH for item in result.timeframes.values())
    assert expected_latest_close("1d", (evaluation + pd.Timedelta(hours=16)).to_pydatetime()) == evaluation.to_pydatetime()


def test_missing_latest_four_hour_and_one_hour_bars_are_stale(market_frames):
    evaluation = market_frames["1d"].index[220] + pd.Timedelta(days=1)
    frames = _closed_frames(market_frames, evaluation)

    four_hour_stale = {**frames, "4h": frames["4h"].iloc[:-1]}
    one_hour_stale = {**frames, "1h": frames["1h"].iloc[:-1]}

    assert check_data_freshness(four_hour_stale, evaluation.to_pydatetime(), ("4h",)).timeframes["4h"].status == FreshnessStatus.STALE
    assert check_data_freshness(one_hour_stale, evaluation.to_pydatetime(), ("1h",)).timeframes["1h"].status == FreshnessStatus.STALE


class _RetryClient:
    def __init__(self, frames, trading_rules, *, always_stale=False):
        self.frames = frames
        self.trading_rules = trading_rules
        self.always_stale = always_stale
        self.four_hour_calls = 0

    def fetch_klines(self, symbol, timeframe, *, limit):
        del symbol, limit
        frame = self.frames[timeframe]
        if timeframe == "4h":
            self.four_hour_calls += 1
            if self.always_stale or self.four_hour_calls == 1:
                return frame.iloc[:-1].copy()
        return frame.copy()

    def fetch_symbol_trading_rules(self, symbol):
        del symbol
        return self.trading_rules


def test_live_retry_refetches_and_recovers(market_frames, trading_rules):
    evaluation = market_frames["1d"].index[220] + pd.Timedelta(days=1)
    frames = _closed_frames(market_frames, evaluation)
    config = AppConfig.model_validate(
        {"market": {"freshness_retry_count": 1, "freshness_retry_delay_seconds": 0}}
    )
    client = _RetryClient(frames, trading_rules)

    report = analyze_symbol(
        "BTC/USDT",
        config,
        client=client,
        requested_at=(evaluation + pd.Timedelta(seconds=5)).to_pydatetime(),
    )

    assert report.freshness_retry_attempts == 1
    assert client.four_hour_calls == 2
    assert report.data_freshness["4h"].status == FreshnessStatus.FRESH


def test_retry_exhaustion_and_offline_stale_data_fail_closed(market_frames, trading_rules):
    evaluation = market_frames["1d"].index[220] + pd.Timedelta(days=1)
    frames = _closed_frames(market_frames, evaluation)
    config = AppConfig.model_validate(
        {"market": {"freshness_retry_count": 1, "freshness_retry_delay_seconds": 0}}
    )
    client = _RetryClient(frames, trading_rules, always_stale=True)

    retried = analyze_symbol(
        "BTC/USDT",
        config,
        client=client,
        requested_at=(evaluation + timedelta(seconds=5)).to_pydatetime(),
    )
    offline = analyze_frames_at_time(
        "BTC/USDT",
        {**frames, "4h": frames["4h"].iloc[:-1]},
        config,
        evaluated_at=evaluation.to_pydatetime(),
        trading_rules=trading_rules,
    )

    for report in (retried, offline):
        assert report.signal == SignalLabel.NO_TRADE
        assert report.entry_zone == "not_available"
        assert report.suggested_position_size == "not_available"
        assert report.data_freshness["4h"].status == FreshnessStatus.STALE
