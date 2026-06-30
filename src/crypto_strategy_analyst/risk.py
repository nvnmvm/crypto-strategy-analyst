"""Hard risk locks and position sizing."""

from __future__ import annotations

from dataclasses import dataclass

from .config import RiskConfig
from .models import PositionSuggestion


@dataclass(frozen=True, slots=True)
class RiskState:
    daily_stop_losses: int = 0
    daily_loss_fraction: float = 0.0
    current_drawdown: float = 0.0


def risk_blockers(config: RiskConfig, state: RiskState) -> list[str]:
    blockers: list[str] = []
    if state.daily_stop_losses >= config.daily_stop_count:
        blockers.append("daily_stop_count_reached")
    if state.daily_loss_fraction >= config.daily_max_loss:
        blockers.append("daily_loss_limit_reached")
    if state.current_drawdown >= config.max_drawdown:
        blockers.append("maximum_drawdown_protection_active")
    return blockers


def calculate_position(
    *,
    entry_price: float,
    stop_price: float,
    config: RiskConfig,
) -> PositionSuggestion:
    """Size a long spot position from maximum loss, distinct from capital deployed."""

    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        raise ValueError("long position requires 0 < stop_price < entry_price")
    risk_amount = config.account_equity_cny * config.risk_per_trade
    stop_fraction = (entry_price - stop_price) / entry_price
    unconstrained_notional = risk_amount / stop_fraction
    maximum_notional = config.account_equity_cny * config.max_position_fraction
    notional = min(unconstrained_notional, maximum_notional)
    entry_price_cny = entry_price * config.cny_per_usdt
    quantity = notional / entry_price_cny
    actual_risk = notional * stop_fraction
    return PositionSuggestion(
        quantity=round(quantity, 10),
        position_notional_cny=round(notional, 2),
        risk_amount_cny=round(actual_risk, 2),
        position_fraction=round(notional / config.account_equity_cny, 6),
        quote_to_account_rate=config.cny_per_usdt,
    )
