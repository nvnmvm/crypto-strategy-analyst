from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

import crypto_strategy_analyst.adaptive_signal as adaptive
from crypto_strategy_analyst.adaptive_signal import ConfirmationAssessment
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.models import MarketRegime, PriceZone, SignalLabel
from crypto_strategy_analyst.regime import RegimeAssessment
from crypto_strategy_analyst.risk import RiskState
from crypto_strategy_analyst.structure import SwingPoint


def _zone(center: float) -> PriceZone:
    return PriceZone(
        lower_price=center - 1,
        upper_price=center + 1,
        center_price=center,
        level_type="support",
        timeframe="1d+4h",
        touch_count=2,
        reaction_count=1,
        last_touch_time=datetime(2026, 1, 1, tzinfo=UTC),
        strength_score=80,
        evidence=["test"],
    )


def _frame(periods: int, freq: str = "4h") -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=periods, freq=freq, tz="UTC")
    close = pd.Series(range(periods), dtype=float).to_numpy() * 0.02 + 100
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0,
            "volume_ratio": 1.0,
            "ema20": close - 0.2,
            "ema50": close - 1.0,
            "ema200": close - 5.0,
            "atr14": 2.0,
            "rsi14": 50.0,
            "macd_histogram": 0.0,
        },
        index=index,
    )


def _regime(kind: MarketRegime, *, accelerated: bool = False) -> RegimeAssessment:
    strategy = (
        "bear_reversal_accumulation"
        if kind in {MarketRegime.BEAR_CAPITULATION, MarketRegime.BEAR_RECOVERY}
        else "trend_pullback"
    )
    return RegimeAssessment(kind, [], strategy, 0.35, True, True, accelerated)


def test_one_strong_confirmation_replaces_two_normal(monkeypatch):
    frame = _frame(240)
    points = [
        SwingPoint(frame.index[-30], 95, "low", frame.index[-27]),
        SwingPoint(frame.index[-10], 97, "low", frame.index[-7]),
    ]
    monkeypatch.setattr(adaptive, "detect_confirmed_swings", lambda *args, **kwargs: points)
    monkeypatch.setattr(adaptive, "bullish_reversal_pattern", lambda frame: (False, "none"))
    result = adaptive.weighted_confirmations(
        _frame(240, "1d"),
        frame,
        _frame(240, "1h"),
        [],
        _regime(MarketRegime.BULL_TREND),
        AppConfig(),
    )
    assert result.strong_count == 1
    assert result.score >= 2


def test_only_auxiliary_confirmation_cannot_trigger(monkeypatch):
    frame = _frame(240)
    monkeypatch.setattr(adaptive, "detect_confirmed_swings", lambda *args, **kwargs: [])
    monkeypatch.setattr(adaptive, "bullish_reversal_pattern", lambda frame: (False, "none"))
    result = adaptive.weighted_confirmations(
        _frame(240, "1d"),
        frame,
        _frame(240, "1h"),
        [],
        _regime(MarketRegime.BULL_TREND),
        AppConfig(),
    )
    assert result.strong_count == 0
    assert result.score < 2


def test_breakout_entry_does_not_require_traditional_support():
    config = AppConfig.model_validate(
        {"strategy": {"strategy_variant": "relaxed_trend_plus_breakout"}}
    )
    setup, support, allowed, _ = adaptive._entry_zone(
        _frame(240),
        [],
        [],
        _regime(MarketRegime.BULL_TREND),
        ConfirmationAssessment(("strong:breakout_retest",), 2, 1, 103.0),
        config,
    )
    assert setup == "breakout_retest"
    assert support is None
    assert allowed is not None


def test_no_resistance_creates_reduced_risk_b_tier(monkeypatch):
    config = AppConfig.model_validate(
        {
            "strategy": {
                "strategy_variant": "relaxed_trend_plus_breakout",
                "buy_score": 50,
            }
        }
    )
    monkeypatch.setattr(
        adaptive,
        "weighted_confirmations",
        lambda *args, **kwargs: ConfirmationAssessment(("strong:test",), 4, 1, None),
    )
    frame = _frame(240)
    result = adaptive.generate_adaptive_signal(
        regime=_regime(MarketRegime.BULL_TREND),
        daily_frame=_frame(240, "1d"),
        four_hour_frame=frame,
        one_hour_frame=_frame(240, "1h"),
        supports=[_zone(float(frame["close"].iloc[-1]))],
        resistances=[],
        data_is_complete=True,
        config=config,
        risk_state=RiskState(
            daily_start_equity_cny=600,
            current_equity_cny=600,
            peak_equity_cny=600,
        ),
    )
    assert result.candidate_tier == "B"
    assert result.take_profit_1 is not None
    assert result.take_profit_2 is None
    assert result.risk_multiplier == 0.5
    assert result.label == SignalLabel.BUY_CANDIDATE


def test_accelerating_bear_market_blocks_catching_the_knife(monkeypatch):
    config = AppConfig.model_validate(
        {"strategy": {"strategy_variant": "relaxed_trend_plus_bear_reversal"}}
    )
    monkeypatch.setattr(
        adaptive,
        "weighted_confirmations",
        lambda *args, **kwargs: ConfirmationAssessment(("strong:higher_low",), 3, 1, None),
    )
    frame = _frame(240)
    result = adaptive.generate_adaptive_signal(
        regime=_regime(MarketRegime.BEAR_CAPITULATION, accelerated=True),
        daily_frame=_frame(240, "1d"),
        four_hour_frame=frame,
        one_hour_frame=_frame(240, "1h"),
        supports=[],
        resistances=[],
        data_is_complete=True,
        config=config,
        risk_state=RiskState(
            daily_start_equity_cny=600,
            current_equity_cny=600,
            peak_equity_cny=600,
        ),
    )
    assert result.label == SignalLabel.NO_TRADE
    assert "accelerated_decline_without_stabilization" in result.blockers
