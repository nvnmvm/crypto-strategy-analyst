from __future__ import annotations

import pytest
from pydantic import ValidationError

from crypto_strategy_analyst.config import RiskConfig
from crypto_strategy_analyst.errors import PositionConstraintError
from crypto_strategy_analyst.risk import calculate_position


def test_position_distinguishes_notional_and_maximum_loss():
    config = RiskConfig(account_equity_cny=1000, risk_per_trade=0.01, cny_per_usdt=7.2)
    result = calculate_position(entry_price=100, stop_price=95, config=config)
    assert result.position_notional_cny == 200
    assert result.risk_amount_cny == 10
    assert result.position_notional_cny > result.risk_amount_cny


def test_position_is_capped_by_available_equity():
    config = RiskConfig(account_equity_cny=1000, risk_per_trade=0.01, max_position_fraction=0.5)
    result = calculate_position(entry_price=100, stop_price=99.5, config=config)
    assert result.position_notional_cny == 500
    assert result.risk_amount_cny == 2.5


def test_position_can_use_persisted_current_equity_instead_of_config_default():
    config = RiskConfig(account_equity_cny=1000, risk_per_trade=0.01)
    result = calculate_position(
        entry_price=100,
        stop_price=95,
        config=config,
        account_equity_cny=500,
    )
    assert result.position_notional_cny == 100
    assert result.risk_amount_cny == 5


def test_risk_above_three_percent_is_rejected():
    with pytest.raises(ValidationError):
        RiskConfig(risk_per_trade=0.031)


def test_long_stop_must_be_below_entry():
    with pytest.raises(ValueError):
        calculate_position(entry_price=100, stop_price=101, config=RiskConfig())


def test_exchange_step_rounds_down_without_exceeding_risk(trading_rules):
    rules = trading_rules.model_copy(update={"quantity_step_size": 0.01})
    result = calculate_position(
        entry_price=100,
        stop_price=95,
        config=RiskConfig(account_equity_cny=1000, risk_per_trade=0.01),
        trading_rules=rules,
    )
    assert result.quantity == 0.27
    assert result.risk_amount_cny <= 10


def test_exchange_minimum_notional_fails_closed(trading_rules):
    rules = trading_rules.model_copy(update={"minimum_notional": 30})
    with pytest.raises(PositionConstraintError, match="notional_below_exchange_minimum"):
        calculate_position(
            entry_price=100,
            stop_price=95,
            config=RiskConfig(account_equity_cny=1000, risk_per_trade=0.01),
            trading_rules=rules,
        )


def test_position_respects_cash_deployment_and_aggregate_risk(trading_rules):
    config = RiskConfig(
        account_equity_cny=1000,
        risk_per_trade=0.01,
        aggregate_open_risk_limit=0.02,
        max_symbol_deployed_fraction=0.6,
        max_total_deployed_fraction=0.8,
    )
    result = calculate_position(
        entry_price=100,
        stop_price=95,
        config=config,
        trading_rules=trading_rules,
        available_cash_cny=50,
        current_total_deployed_cny=700,
        aggregate_open_risk_cny=15,
    )
    assert result.position_notional_cny <= 50
    assert result.risk_amount_cny <= 5

    with pytest.raises(PositionConstraintError, match="aggregate_open_risk_limit_reached"):
        calculate_position(
            entry_price=100,
            stop_price=95,
            config=config,
            trading_rules=trading_rules,
            aggregate_open_risk_cny=20,
        )
