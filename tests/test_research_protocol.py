from __future__ import annotations

from dataclasses import replace

import pandas as pd

from crypto_strategy_analyst.backtest import run_backtest
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.levels import detect_zones
from crypto_strategy_analyst.models import Trend
from crypto_strategy_analyst.signal import generate_signal
from crypto_strategy_analyst.structure import detect_confirmed_swings


def test_backtest_reports_predefined_single_parameter_set(market_frames, trading_rules):
    start = market_frames["1d"].index[220] + pd.Timedelta(days=1)
    result = run_backtest(
        market_frames,
        "BTC/USDT",
        AppConfig(),
        start=start.to_pydatetime(),
        end=(start + pd.Timedelta(hours=12)).to_pydatetime(),
        trading_rules=trading_rules,
    )
    dumped = result.model_dump(mode="json")
    assert "chronological_holdout_split" in dumped
    assert "time_splits" not in dumped
    assert result.research_protocol.parameter_search_performed is False
    assert result.research_protocol.number_of_parameter_sets_evaluated == 1
    assert result.research_protocol.selection_rule == "predefined"


def test_signal_function_has_no_wall_clock_or_hidden_randomness(enriched):
    swings = detect_confirmed_swings(enriched)
    supports, resistances = detect_zones(enriched, swings, "4h")
    kwargs = {
        "daily_trend": Trend.SIDEWAYS,
        "four_hour_trend": Trend.SIDEWAYS,
        "one_hour_frame": enriched,
        "four_hour_frame": enriched,
        "supports": supports,
        "resistances": resistances,
        "data_is_complete": True,
        "config": AppConfig(),
    }
    first = generate_signal(**kwargs)
    second = generate_signal(**{**kwargs, "one_hour_frame": enriched.copy(deep=True)})
    assert first == second
    assert "datetime" not in generate_signal.__code__.co_names
    assert "random" not in generate_signal.__code__.co_names
    assert replace(first) == first
