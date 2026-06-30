from __future__ import annotations

from dataclasses import replace

import crypto_strategy_analyst.backtest as backtest_module
from crypto_strategy_analyst.backtest import run_backtest
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.execution import validate_pending_entry_at_open
from crypto_strategy_analyst.models import PriceZone, ScoreBreakdown, SignalLabel
from crypto_strategy_analyst.signal import SignalDecision


def _signal() -> SignalDecision:
    zone = PriceZone(
        lower_price=99,
        upper_price=101,
        center_price=100,
        level_type="support",
        timeframe="4h",
        touch_count=2,
        last_touch_time="2026-07-01T00:00:00Z",
        strength_score=70,
        evidence=["test"],
    )
    return SignalDecision(
        label=SignalLabel.BUY_CANDIDATE,
        score=70,
        breakdown=ScoreBreakdown(
            higher_timeframe_trend=15,
            support_resistance=20,
            candlestick_confirmation=15,
            volume_confirmation=10,
            indicator_confirmation=10,
            reward_risk_space=10,
        ),
        confirmations=["test"],
        blockers=[],
        entry_zone=zone,
        stop_loss=95,
        take_profit_1=110,
        take_profit_2=115,
        reward_risk=2,
        planned_entry_price=100,
    )


def test_normal_next_open_is_valid():
    result = validate_pending_entry_at_open(_signal(), 100, 4, AppConfig())
    assert result.is_valid
    assert result.reward_risk_at_open == 2


def test_gap_target_reward_risk_and_expiration_cancel():
    signal = _signal()
    assert "open_above_entry_tolerance" in validate_pending_entry_at_open(signal, 103, 4, AppConfig()).reasons
    assert "open_above_target_1" in validate_pending_entry_at_open(signal, 111, 30, AppConfig()).reasons
    weak_reward = replace(signal, entry_zone=signal.entry_zone.model_copy(update={"upper_price": 108}))
    assert "reward_risk_invalid_after_gap" in validate_pending_entry_at_open(weak_reward, 107, 20, AppConfig()).reasons
    assert validate_pending_entry_at_open(signal, 100, 4, AppConfig(), age_bars=2).reasons == ["signal_expired"]


def test_cancelled_pending_signal_creates_no_trade_record(market_frames, monkeypatch):
    original = backtest_module.evaluate_setup_at_time
    impossible = replace(
        _signal(),
        entry_zone=_signal().entry_zone.model_copy(
            update={"lower_price": 0.5, "upper_price": 1.0, "center_price": 0.75}
        ),
        stop_loss=0.25,
        take_profit_1=2.0,
        take_profit_2=3.0,
        planned_entry_price=0.75,
    )

    def candidate(*args, **kwargs):
        return replace(original(*args, **kwargs), decision=impossible)

    monkeypatch.setattr(backtest_module, "evaluate_setup_at_time", candidate)
    start = market_frames["1d"].index[220] + backtest_module.pd.Timedelta(days=1)
    result = run_backtest(
        market_frames,
        "BTC/USDT",
        AppConfig(),
        start=start.to_pydatetime(),
        end=(start + backtest_module.pd.Timedelta(hours=12)).to_pydatetime(),
    )

    assert result.generated_signal_count > 0
    assert result.cancelled_entry_count > 0
    assert result.executed_entry_count == 0
    assert result.trades == []
