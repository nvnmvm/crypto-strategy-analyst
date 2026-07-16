"""Immutable next-bar validation of a previously emitted plan."""

from __future__ import annotations

from .events import make_event
from .models import AnalysisReport, EntryValidation, Horizon, MarketSnapshot, SignalStatus
from .profiles.registry import get_profile

PRIMARY = {Horizon.SHORT: "4h", Horizon.SWING: "1d", Horizon.LONG: "1w"}


def validate_entry(
    report: AnalysisReport, snapshot: MarketSnapshot, horizon: Horizon
) -> EntryValidation:
    plan = report.horizons[horizon]
    reasons: list[str] = []
    if (
        plan.status != SignalStatus.CANDIDATE
        or not plan.entry_range
        or not plan.stop_loss
        or not plan.take_profits
    ):
        reasons.append("original_plan_not_candidate")
    later = [
        bar
        for bar in snapshot.candles.get(PRIMARY[horizon], [])
        if bar.open_time >= report.evaluation_time
    ]
    next_bar = later[0] if later else None
    if next_bar is None:
        reasons.append("next_bar_not_available")
    if plan.valid_until and next_bar and next_bar.open_time > plan.valid_until:
        reasons.append("plan_expired")
    open_price = next_bar.open if next_bar else None
    if (
        open_price
        and plan.entry_range
        and not plan.entry_range.lower <= open_price <= plan.entry_range.upper
    ):
        reasons.append(
            "open_above_entry_range"
            if open_price > plan.entry_range.upper
            else "open_below_entry_range"
        )
    if open_price and plan.stop_loss and open_price <= plan.stop_loss:
        reasons.append("open_below_stop")
    if open_price and plan.take_profits and open_price >= plan.take_profits[0].price:
        reasons.append("open_above_target")
    reward_risk = None
    if open_price and plan.stop_loss and plan.take_profits and open_price > plan.stop_loss:
        reward_risk = max(
            0, (plan.take_profits[0].price - open_price) / (open_price - plan.stop_loss)
        )
        if plan.minimum_reward_risk and reward_risk < plan.minimum_reward_risk:
            reasons.append("reward_risk_below_minimum")
    profile = get_profile(report.profile, report.symbol)
    if profile.apply_hard_filters(snapshot, horizon):
        reasons.append("hard_market_risk")
    status = SignalStatus.ENTRY_CANCELLED if reasons else SignalStatus.ENTRY_VALIDATED
    event = make_event(
        status.value,
        report.symbol,
        report.profile,
        horizon,
        next_bar.open_time if next_bar else snapshot.as_of,
        f"{report.report_id}:{horizon.value}:{status.value}",
        {"report_id": report.report_id, "reasons": reasons},
        "warning" if reasons else "info",
    )
    return EntryValidation(
        report_id=report.report_id,
        horizon=horizon,
        status=status,
        validation_time=next_bar.open_time if next_bar else snapshot.as_of,
        actual_open_price=open_price,
        original_entry_range=plan.entry_range,
        stop_loss=plan.stop_loss,
        take_profits=plan.take_profits,
        reward_risk_at_open=reward_risk,
        reasons=reasons,
        event=event,
    )
