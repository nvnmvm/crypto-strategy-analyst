from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

import crypto_strategy_analyst.analysis as analysis_module
from crypto_strategy_analyst.analysis import analyze_frames_at_time
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.models import PriceZone, SignalLabel
from crypto_strategy_analyst.risk import RiskState
from crypto_strategy_analyst.strategy import evaluate_setup_at_time, prepare_market_frames


@pytest.mark.parametrize(
    ("state", "expected_lock"),
    [
        (
            RiskState(
                date=date(2022, 8, 10),
                daily_stop_losses=2,
                daily_start_equity_cny=1000,
                current_equity_cny=1000,
                peak_equity_cny=1000,
            ),
            "daily_stop_count_reached",
        ),
        (
            RiskState(
                date=date(2022, 8, 10),
                daily_realized_loss_cny=20,
                daily_start_equity_cny=1000,
                current_equity_cny=980,
                peak_equity_cny=1000,
                current_drawdown=0.02,
            ),
            "daily_loss_limit_reached",
        ),
        (
            RiskState(
                date=date(2022, 8, 10),
                daily_start_equity_cny=1000,
                current_equity_cny=900,
                peak_equity_cny=1000,
                current_drawdown=0.10,
            ),
            "maximum_drawdown_protection_active",
        ),
    ],
)
def test_analysis_fails_closed_for_persisted_risk_locks(market_frames, state, expected_lock):
    requested = market_frames["1d"].index[220] + pd.Timedelta(days=1)
    report = analyze_frames_at_time(
        "BTC/USDT",
        market_frames,
        AppConfig(),
        evaluated_at=requested.to_pydatetime(),
        risk_state=state,
    )
    assert report.signal == SignalLabel.NO_TRADE
    assert expected_lock in report.risk_locks
    assert report.suggested_position_size == "not_available"


def test_analysis_position_uses_persisted_current_equity(
    market_frames, trading_rules, monkeypatch
):
    config = AppConfig()
    requested = market_frames["1d"].index[220] + pd.Timedelta(days=1)
    baseline = evaluate_setup_at_time(
        prepare_market_frames(market_frames, config),
        config,
        requested_at=requested.to_pydatetime(),
    )
    current_price = float(baseline.frames["4h"]["close"].iloc[-1])
    entry_zone = PriceZone(
        lower_price=current_price * 0.98,
        upper_price=current_price,
        center_price=current_price * 0.99,
        level_type="support",
        timeframe="4h",
        touch_count=2,
        last_touch_time=baseline.frames["4h"].index[-1].to_pydatetime(),
        strength_score=70,
        evidence=["test"],
    )
    candidate = replace(
        baseline.decision,
        label=SignalLabel.BUY_CANDIDATE,
        blockers=[],
        entry_zone=entry_zone,
        stop_loss=current_price * 0.95,
        take_profit_1=current_price * 1.10,
        take_profit_2=current_price * 1.15,
        reward_risk=3.0,
    )
    monkeypatch.setattr(
        analysis_module,
        "evaluate_setup_at_time",
        lambda *args, **kwargs: replace(baseline, decision=candidate),
    )
    state = RiskState(
        date=requested.date(),
        daily_start_equity_cny=500,
        current_equity_cny=500,
        peak_equity_cny=500,
    )

    report = analyze_frames_at_time(
        "BTC/USDT",
        market_frames,
        config,
        evaluated_at=requested.to_pydatetime(),
        risk_state=state,
        trading_rules=trading_rules,
    )

    assert report.account_equity_cny == 500
    assert report.maximum_loss_amount == 5
    assert report.suggested_position_size != "not_available"
    assert report.suggested_position_size.position_notional_cny == pytest.approx(100, abs=0.1)
