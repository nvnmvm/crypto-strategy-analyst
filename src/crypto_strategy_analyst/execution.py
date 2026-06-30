"""Shared validation for turning a candidate plan into a next-open entry."""

from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .signal import SignalDecision


@dataclass(frozen=True, slots=True)
class PendingEntryValidation:
    """Result of revalidating a candidate at the next 4h open."""

    is_valid: bool
    reasons: list[str]
    reward_risk_at_open: float | None


def validate_pending_entry_at_open(
    signal: SignalDecision,
    next_open_price: float,
    atr: float,
    config: AppConfig,
    *,
    age_bars: int = 1,
) -> PendingEntryValidation:
    """Revalidate immutable stop/targets against the actual next 4h open."""

    if age_bars > config.strategy.pending_signal_valid_bars:
        return PendingEntryValidation(False, ["signal_expired"], None)
    required = (
        signal.entry_zone,
        signal.stop_loss,
        signal.take_profit_1,
        signal.take_profit_2,
        signal.planned_entry_price,
    )
    if any(value is None for value in required):
        return PendingEntryValidation(False, ["signal_incomplete"], None)
    entry_zone = signal.entry_zone
    stop = float(signal.stop_loss)
    target_1 = float(signal.take_profit_1)
    target_2 = float(signal.take_profit_2)
    planned_entry = float(signal.planned_entry_price)
    reasons: list[str] = []
    if next_open_price <= stop:
        reasons.append("open_below_stop")
    if next_open_price >= target_1:
        reasons.append("open_above_target_1")
    if target_2 <= target_1:
        reasons.append("invalid_target_order")
    if next_open_price > entry_zone.upper_price:
        reasons.append("open_above_entry_tolerance")
    elif next_open_price < entry_zone.lower_price:
        reasons.append("open_below_entry_zone")
    if abs(next_open_price - planned_entry) > atr * config.strategy.max_entry_gap_atr:
        gap_reason = (
            "open_above_entry_tolerance"
            if next_open_price > planned_entry
            else "open_below_entry_zone"
        )
        reasons.append(gap_reason)
    risk = next_open_price - stop
    reward_risk = (target_1 - next_open_price) / risk if risk > 0 else None
    if reward_risk is None or reward_risk < config.risk.min_reward_risk:
        reasons.append("reward_risk_invalid_after_gap")
    unique_reasons = list(dict.fromkeys(reasons))
    return PendingEntryValidation(
        is_valid=not unique_reasons,
        reasons=unique_reasons,
        reward_risk_at_open=reward_risk,
    )
