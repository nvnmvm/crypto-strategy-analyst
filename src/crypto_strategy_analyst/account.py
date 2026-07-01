"""Versioned, idempotent account commands with a recoverable file transaction."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from .errors import RiskStateError
from .risk import RiskState

SCHEMA_VERSION = 3
LOGGER = logging.getLogger(__name__)


class PendingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1, max_length=200)
    symbol: Literal["BTC/USDT", "ETH/USDT"]
    created_at: datetime
    expires_at: datetime
    entry_lower: float = Field(gt=0)
    entry_upper: float = Field(gt=0)
    planned_entry: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    take_profit_1: float = Field(gt=0)
    take_profit_2: float | None = Field(default=None, gt=0)
    initial_risk_quote: float = Field(gt=0)
    status: Literal["pending", "validated"] = "pending"
    strategy_id: str = "trend_pullback"
    strategy_horizon: Literal["short_term", "medium_term", "long_term"] = "medium_term"
    risk_multiplier: float = Field(default=1.0, gt=0, le=1)
    tranche_number: Literal[1, 2] = 1

    @model_validator(mode="after")
    def validate_prices(self) -> PendingPlan:
        if not self.entry_lower <= self.planned_entry <= self.entry_upper:
            raise ValueError("planned_entry must be inside the entry zone")
        if not self.stop_price < self.planned_entry < self.take_profit_1:
            raise ValueError("plan prices must satisfy stop < entry < TP1")
        if self.take_profit_2 is not None and self.take_profit_2 <= self.take_profit_1:
            raise ValueError("TP2 must be above TP1")
        if self.expires_at <= self.created_at:
            raise ValueError("pending plan must expire after creation")
        return self


class SpotPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_id: str = Field(min_length=1, max_length=200)
    symbol: Literal["BTC/USDT", "ETH/USDT"]
    opened_at: datetime
    entry_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    mark_price: float = Field(gt=0)
    initial_trade_risk: float = Field(ge=0)
    remaining_open_risk: float = Field(ge=0)
    deployed_notional: float = Field(gt=0)
    realized_pnl: float = 0.0
    entry_count: int = Field(default=1, ge=1, le=2)
    strategy_id: str = "trend_pullback"
    strategy_horizon: Literal["short_term", "medium_term", "long_term"] = "medium_term"

    @model_validator(mode="after")
    def validate_stop(self) -> SpotPosition:
        if self.stop_price >= self.entry_price:
            raise ValueError("long-only protective stop must be below entry")
        return self


class PortfolioState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_currency: Literal["USDT"] = "USDT"
    cash: float = Field(default=0.0, ge=0)
    reserved_cash: float = Field(default=0.0, ge=0)
    positions: dict[str, SpotPosition] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cash(self) -> PortfolioState:
        if self.reserved_cash > self.cash:
            raise ValueError("reserved_cash cannot exceed cash")
        if set(self.positions) - {"BTC/USDT", "ETH/USDT"}:
            raise ValueError("portfolio contains an unsupported symbol")
        if any(key != position.symbol for key, position in self.positions.items()):
            raise ValueError("position map key must equal the position symbol")
        return self

    @property
    def available_cash(self) -> float:
        return max(0.0, self.cash - self.reserved_cash)

    @property
    def total_deployed(self) -> float:
        return sum(position.quantity * position.mark_price for position in self.positions.values())


class AccountRiskState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    daily_stop_losses: int = Field(default=0, ge=0)
    realized_daily_loss: float = Field(default=0.0, ge=0)
    daily_start_equity: float = Field(default=0.0, ge=0)
    current_equity: float = Field(default=0.0, ge=0)
    peak_equity: float = Field(default=0.0, ge=0)
    current_drawdown: float = Field(default=0.0, ge=0, le=1)
    aggregate_open_risk: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_drawdown(self) -> AccountRiskState:
        expected = 1 - self.current_equity / self.peak_equity if self.peak_equity else 0.0
        if self.current_equity > self.peak_equity + 1e-9:
            raise ValueError("current equity cannot exceed peak equity")
        if abs(expected - self.current_drawdown) > 1e-9:
            raise ValueError("current_drawdown is inconsistent with equity")
        return self


class AccountState(BaseModel):
    """Materialized state; account-events.jsonl is the append-only fact record."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = SCHEMA_VERSION
    state_version: int = Field(default=3, ge=3)
    risk: AccountRiskState
    portfolio: PortfolioState
    pending_plans: list[PendingPlan] = Field(default_factory=list)
    processed_commands: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_invariants(self) -> AccountState:
        if len(self.processed_commands) != len(set(self.processed_commands)):
            raise ValueError("processed command IDs must be unique")
        plan_ids = [plan.plan_id for plan in self.pending_plans]
        if len(plan_ids) != len(set(plan_ids)):
            raise ValueError("pending plan IDs must be unique")
        aggregate = sum(
            position.remaining_open_risk for position in self.portfolio.positions.values()
        )
        if abs(aggregate - self.risk.aggregate_open_risk) > 1e-8:
            raise ValueError("aggregate_open_risk is inconsistent with positions")
        return self

    def as_legacy_risk_state(self, *, cny_per_usdt: float) -> RiskState:
        return RiskState(
            date=self.risk.date,
            daily_stop_losses=self.risk.daily_stop_losses,
            daily_realized_loss_cny=round(self.risk.realized_daily_loss * cny_per_usdt, 12),
            daily_start_equity_cny=round(self.risk.daily_start_equity * cny_per_usdt, 12),
            current_equity_cny=round(self.risk.current_equity * cny_per_usdt, 12),
            peak_equity_cny=round(self.risk.peak_equity * cny_per_usdt, 12),
            current_drawdown=self.risk.current_drawdown,
        )


class CommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=200)
    timestamp: datetime
    expected_state_version: int = Field(ge=3)


class InitializeAccount(CommandBase):
    command_type: Literal["InitializeAccount"] = "InitializeAccount"
    initial_cash: float = Field(gt=0)
    reserved_cash: float = Field(default=0.0, ge=0)


class CreatePendingPlan(CommandBase):
    command_type: Literal["CreatePendingPlan"] = "CreatePendingPlan"
    plan: PendingPlan


class ValidatePendingPlan(CommandBase):
    command_type: Literal["ValidatePendingPlan"] = "ValidatePendingPlan"
    plan_id: str


class CancelPendingPlan(CommandBase):
    command_type: Literal["CancelPendingPlan"] = "CancelPendingPlan"
    plan_id: str
    reason: str = Field(min_length=1, max_length=200)


class OpenSpotPosition(CommandBase):
    command_type: Literal["OpenSpotPosition"] = "OpenSpotPosition"
    plan_id: str
    position_id: str
    symbol: Literal["BTC/USDT", "ETH/USDT"]
    entry_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    fee: float = Field(default=0.0, ge=0)
    minimum_notional: float = Field(default=0.0, ge=0)
    aggregate_open_risk_limit: float = Field(default=0.02, gt=0, le=0.03)
    max_symbol_deployed_fraction: float = Field(default=0.60, gt=0, le=1)
    max_total_deployed_fraction: float = Field(default=1.0, gt=0, le=1)


class UpdateMarkPrice(CommandBase):
    command_type: Literal["UpdateMarkPrice"] = "UpdateMarkPrice"
    symbol: Literal["BTC/USDT", "ETH/USDT"]
    mark_price: float = Field(gt=0)


class AddSpotPosition(CommandBase):
    command_type: Literal["AddSpotPosition"] = "AddSpotPosition"
    symbol: Literal["BTC/USDT", "ETH/USDT"]
    entry_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    fee: float = Field(default=0.0, ge=0)
    independent_structure_confirmation: bool
    aggregate_open_risk_limit: float = Field(default=0.02, gt=0, le=0.03)
    max_symbol_deployed_fraction: float = Field(default=0.60, gt=0, le=1)
    max_total_deployed_fraction: float = Field(default=1.0, gt=0, le=1)


class RecordPartialExit(CommandBase):
    command_type: Literal["RecordPartialExit"] = "RecordPartialExit"
    symbol: Literal["BTC/USDT", "ETH/USDT"]
    quantity: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    fee: float = Field(default=0.0, ge=0)
    stopped_out: bool = False


class CloseSpotPosition(CommandBase):
    command_type: Literal["CloseSpotPosition"] = "CloseSpotPosition"
    symbol: Literal["BTC/USDT", "ETH/USDT"]
    exit_price: float = Field(gt=0)
    fee: float = Field(default=0.0, ge=0)
    stopped_out: bool = False


class ResetDailyRisk(CommandBase):
    command_type: Literal["ResetDailyRisk"] = "ResetDailyRisk"
    new_date: date


class UpdateExternalEquity(CommandBase):
    command_type: Literal["UpdateExternalEquity"] = "UpdateExternalEquity"
    current_equity: float = Field(ge=0)


class RecordExternalResult(CommandBase):
    command_type: Literal["RecordExternalResult"] = "RecordExternalResult"
    pnl: float
    stopped_out: bool = False


AccountCommand = Annotated[
    InitializeAccount
    | CreatePendingPlan
    | ValidatePendingPlan
    | CancelPendingPlan
    | OpenSpotPosition
    | UpdateMarkPrice
    | AddSpotPosition
    | RecordPartialExit
    | CloseSpotPosition
    | ResetDailyRisk
    | UpdateExternalEquity
    | RecordExternalResult,
    Field(discriminator="command_type"),
]
COMMAND_ADAPTER = TypeAdapter(AccountCommand)


class AccountEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    command_id: str
    timestamp: datetime
    event_type: str
    state_version: int
    state_hash: str
    data: dict[str, Any] = Field(default_factory=dict)


def _state_hash(state: AccountState) -> str:
    payload = json.dumps(
        state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def empty_account_state(timestamp: datetime) -> AccountState:
    return AccountState(
        risk=AccountRiskState(date=timestamp.date()),
        portfolio=PortfolioState(),
    )


def _revalue(state: AccountState, *, realized_loss_delta: float = 0.0) -> AccountState:
    portfolio = state.portfolio
    equity = portfolio.cash + sum(
        position.quantity * position.mark_price for position in portfolio.positions.values()
    )
    peak = max(state.risk.peak_equity, equity)
    risk = state.risk.model_copy(
        update={
            "current_equity": equity,
            "peak_equity": peak,
            "current_drawdown": round(1 - equity / peak, 12) if peak else 0.0,
            "realized_daily_loss": state.risk.realized_daily_loss + realized_loss_delta,
            "aggregate_open_risk": sum(
                position.remaining_open_risk for position in portfolio.positions.values()
            ),
        }
    )
    return state.model_copy(update={"risk": risk})


def _finish(
    before: AccountState,
    command: CommandBase,
    updated: AccountState,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> tuple[AccountState, list[AccountEvent]]:
    new_version = before.state_version + 1
    processed = [*before.processed_commands, command.command_id]
    finished = updated.model_copy(
        update={"state_version": new_version, "processed_commands": processed}
    )
    event = AccountEvent(
        event_id=str(uuid.uuid4()),
        command_id=command.command_id,
        timestamp=command.timestamp,
        event_type=event_type,
        state_version=new_version,
        state_hash=_state_hash(finished),
        data=data or {},
    )
    return AccountState.model_validate(finished.model_dump()), [event]


def apply_command(
    current_state: AccountState, command: AccountCommand
) -> tuple[AccountState, list[AccountEvent]]:
    """Validate and apply one command; duplicate IDs are successful no-ops."""

    if command.command_id in current_state.processed_commands:
        return current_state.model_copy(deep=True), []
    if command.expected_state_version != current_state.state_version:
        raise RiskStateError(
            f"state version conflict: expected {command.expected_state_version}, "
            f"actual {current_state.state_version}"
        )

    if isinstance(command, InitializeAccount):
        if current_state.risk.current_equity or current_state.portfolio.cash:
            raise RiskStateError("account is already initialized")
        if command.reserved_cash > command.initial_cash:
            raise RiskStateError("reserved cash cannot exceed initial cash")
        portfolio = PortfolioState(cash=command.initial_cash, reserved_cash=command.reserved_cash)
        risk = AccountRiskState(
            date=command.timestamp.date(),
            daily_start_equity=command.initial_cash,
            current_equity=command.initial_cash,
            peak_equity=command.initial_cash,
        )
        return _finish(
            current_state,
            command,
            current_state.model_copy(update={"portfolio": portfolio, "risk": risk}),
            "AccountInitialized",
            {"initial_cash": command.initial_cash},
        )

    if current_state.risk.current_equity <= 0 and not isinstance(command, UpdateExternalEquity):
        raise RiskStateError("account must be initialized before applying commands")

    if isinstance(command, CreatePendingPlan):
        if command.plan.plan_id in {plan.plan_id for plan in current_state.pending_plans}:
            raise RiskStateError(f"pending plan already exists: {command.plan.plan_id}")
        if command.plan.symbol in current_state.portfolio.positions:
            raise RiskStateError("only one long spot position per symbol is allowed")
        return _finish(
            current_state,
            command,
            current_state.model_copy(
                update={"pending_plans": [*current_state.pending_plans, command.plan]}
            ),
            "PendingPlanCreated",
            {"plan_id": command.plan.plan_id, "symbol": command.plan.symbol},
        )

    if isinstance(command, ValidatePendingPlan):
        plans = []
        found = False
        for plan in current_state.pending_plans:
            if plan.plan_id == command.plan_id:
                if command.timestamp > plan.expires_at:
                    raise RiskStateError("pending plan has expired")
                found = True
                plans.append(plan.model_copy(update={"status": "validated"}))
            else:
                plans.append(plan)
        if not found:
            raise RiskStateError(f"pending plan not found: {command.plan_id}")
        return _finish(
            current_state,
            command,
            current_state.model_copy(update={"pending_plans": plans}),
            "PendingPlanValidated",
            {"plan_id": command.plan_id},
        )

    if isinstance(command, CancelPendingPlan):
        plans = [plan for plan in current_state.pending_plans if plan.plan_id != command.plan_id]
        if len(plans) == len(current_state.pending_plans):
            raise RiskStateError(f"pending plan not found: {command.plan_id}")
        return _finish(
            current_state,
            command,
            current_state.model_copy(update={"pending_plans": plans}),
            "PendingPlanCancelled",
            {"plan_id": command.plan_id, "reason": command.reason},
        )

    if isinstance(command, OpenSpotPosition):
        plan = next(
            (plan for plan in current_state.pending_plans if plan.plan_id == command.plan_id), None
        )
        if plan is None or plan.status != "validated":
            raise RiskStateError("a validated pending plan is required")
        if command.symbol != plan.symbol or command.symbol in current_state.portfolio.positions:
            raise RiskStateError("invalid or duplicate spot position symbol")
        if not plan.entry_lower <= command.entry_price <= plan.entry_upper:
            raise RiskStateError("entry price is outside the validated entry zone")
        if abs(command.stop_price - plan.stop_price) > 1e-9:
            raise RiskStateError("open command cannot move the validated protective stop")
        if command.stop_price >= command.entry_price:
            raise RiskStateError("long-only stop must be below entry")
        notional = command.entry_price * command.quantity
        if notional < command.minimum_notional:
            raise RiskStateError("position is below minimum notional")
        cash_required = notional + command.fee
        if cash_required > current_state.portfolio.available_cash + 1e-9:
            raise RiskStateError("position exceeds available cash")
        initial_risk = command.quantity * (command.entry_price - command.stop_price)
        if initial_risk > plan.initial_risk_quote + 1e-9:
            raise RiskStateError("position exceeds pending plan risk budget")
        aggregate = current_state.risk.aggregate_open_risk + initial_risk
        equity = current_state.risk.current_equity
        if aggregate > equity * command.aggregate_open_risk_limit + 1e-9:
            raise RiskStateError("aggregate open risk limit exceeded")
        if notional > equity * command.max_symbol_deployed_fraction + 1e-9:
            raise RiskStateError("per-symbol deployed capital limit exceeded")
        if current_state.portfolio.total_deployed + notional > (
            equity * command.max_total_deployed_fraction + 1e-9
        ):
            raise RiskStateError("total deployed capital limit exceeded")
        position = SpotPosition(
            position_id=command.position_id,
            symbol=command.symbol,
            opened_at=command.timestamp,
            entry_price=command.entry_price,
            quantity=command.quantity,
            stop_price=command.stop_price,
            mark_price=command.entry_price,
            initial_trade_risk=initial_risk,
            remaining_open_risk=initial_risk,
            deployed_notional=notional,
            strategy_id=plan.strategy_id,
            strategy_horizon=plan.strategy_horizon,
        )
        portfolio = current_state.portfolio.model_copy(
            update={
                "cash": current_state.portfolio.cash - cash_required,
                "positions": {**current_state.portfolio.positions, command.symbol: position},
            }
        )
        updated = _revalue(
            current_state.model_copy(
                update={
                    "portfolio": portfolio,
                    "pending_plans": [
                        item
                        for item in current_state.pending_plans
                        if item.plan_id != command.plan_id
                    ],
                }
            )
        )
        return _finish(
            current_state,
            command,
            updated,
            "SpotPositionOpened",
            {"symbol": command.symbol, "quantity": command.quantity, "initial_risk": initial_risk},
        )

    if isinstance(command, UpdateMarkPrice):
        position = current_state.portfolio.positions.get(command.symbol)
        if position is None:
            raise RiskStateError(f"open position not found: {command.symbol}")
        positions = dict(current_state.portfolio.positions)
        positions[command.symbol] = position.model_copy(update={"mark_price": command.mark_price})
        updated = _revalue(
            current_state.model_copy(
                update={
                    "portfolio": current_state.portfolio.model_copy(update={"positions": positions})
                }
            )
        )
        return _finish(
            current_state,
            command,
            updated,
            "MarkPriceUpdated",
            {"symbol": command.symbol, "mark_price": command.mark_price},
        )

    if isinstance(command, AddSpotPosition):
        position = current_state.portfolio.positions.get(command.symbol)
        if position is None:
            raise RiskStateError("second entry requires an existing position")
        if position.entry_count >= 2:
            raise RiskStateError("a position may contain at most two entries")
        if not command.independent_structure_confirmation:
            raise RiskStateError("second entry requires independent structure confirmation")
        if command.stop_price != position.stop_price or command.entry_price <= command.stop_price:
            raise RiskStateError("second entry cannot move or violate the first protective stop")
        if command.entry_price < position.entry_price:
            raise RiskStateError("second entry cannot average down below the first entry")
        notional = command.entry_price * command.quantity
        cash_required = notional + command.fee
        if cash_required > current_state.portfolio.available_cash + 1e-9:
            raise RiskStateError("second entry exceeds available cash")
        added_risk = command.quantity * (command.entry_price - command.stop_price)
        aggregate = current_state.risk.aggregate_open_risk + added_risk
        equity = current_state.risk.current_equity
        if aggregate > equity * command.aggregate_open_risk_limit + 1e-9:
            raise RiskStateError("aggregate open risk limit exceeded")
        if position.deployed_notional + notional > (
            equity * command.max_symbol_deployed_fraction + 1e-9
        ):
            raise RiskStateError("symbol deployed capital limit exceeded")
        if current_state.portfolio.total_deployed + notional > (
            equity * command.max_total_deployed_fraction + 1e-9
        ):
            raise RiskStateError("total deployed capital limit exceeded")
        total_quantity = position.quantity + command.quantity
        average_entry = (
            position.entry_price * position.quantity + command.entry_price * command.quantity
        ) / total_quantity
        positions = dict(current_state.portfolio.positions)
        positions[command.symbol] = position.model_copy(
            update={
                "entry_price": average_entry,
                "quantity": total_quantity,
                "mark_price": command.entry_price,
                "initial_trade_risk": position.initial_trade_risk + added_risk,
                "remaining_open_risk": position.remaining_open_risk + added_risk,
                "deployed_notional": position.deployed_notional + notional,
                "entry_count": 2,
            }
        )
        portfolio = current_state.portfolio.model_copy(
            update={
                "cash": current_state.portfolio.cash - cash_required,
                "positions": positions,
            }
        )
        updated = _revalue(current_state.model_copy(update={"portfolio": portfolio}))
        return _finish(
            current_state,
            command,
            updated,
            "SpotPositionAdded",
            {"symbol": command.symbol, "quantity": command.quantity, "entry_count": 2},
        )

    if isinstance(command, (RecordPartialExit, CloseSpotPosition)):
        position = current_state.portfolio.positions.get(command.symbol)
        if position is None:
            raise RiskStateError(f"open position not found: {command.symbol}")
        quantity = position.quantity if isinstance(command, CloseSpotPosition) else command.quantity
        if quantity > position.quantity + 1e-12:
            raise RiskStateError("exit quantity exceeds open quantity")
        if isinstance(command, RecordPartialExit) and quantity >= position.quantity - 1e-12:
            raise RiskStateError("partial exit must leave a positive quantity")
        proceeds = quantity * command.exit_price - command.fee
        pnl = quantity * (command.exit_price - position.entry_price) - command.fee
        remaining = position.quantity - quantity
        positions = dict(current_state.portfolio.positions)
        if remaining <= 1e-12:
            del positions[command.symbol]
        else:
            positions[command.symbol] = position.model_copy(
                update={
                    "quantity": remaining,
                    "mark_price": command.exit_price,
                    "remaining_open_risk": remaining
                    * max(0.0, position.entry_price - position.stop_price),
                    "realized_pnl": position.realized_pnl + pnl,
                }
            )
        portfolio = current_state.portfolio.model_copy(
            update={"cash": current_state.portfolio.cash + proceeds, "positions": positions}
        )
        risk = current_state.risk.model_copy(
            update={
                "daily_stop_losses": current_state.risk.daily_stop_losses
                + int(command.stopped_out and pnl < 0)
            }
        )
        updated = _revalue(
            current_state.model_copy(update={"portfolio": portfolio, "risk": risk}),
            realized_loss_delta=max(0.0, -pnl),
        )
        event_type = (
            "SpotPositionClosed"
            if isinstance(command, CloseSpotPosition)
            else "PartialExitRecorded"
        )
        return _finish(
            current_state,
            command,
            updated,
            event_type,
            {"symbol": command.symbol, "quantity": quantity, "realized_pnl": pnl},
        )

    if isinstance(command, ResetDailyRisk):
        if command.new_date < current_state.risk.date:
            raise RiskStateError("daily risk date cannot move backward")
        risk = current_state.risk.model_copy(
            update={
                "date": command.new_date,
                "daily_stop_losses": 0,
                "realized_daily_loss": 0.0,
                "daily_start_equity": current_state.risk.current_equity,
            }
        )
        return _finish(
            current_state,
            command,
            current_state.model_copy(update={"risk": risk}),
            "DailyRiskReset",
            {"new_date": command.new_date.isoformat()},
        )

    if isinstance(command, UpdateExternalEquity):
        peak = max(current_state.risk.peak_equity, command.current_equity)
        risk = current_state.risk.model_copy(
            update={
                "current_equity": command.current_equity,
                "peak_equity": peak,
                "current_drawdown": round(1 - command.current_equity / peak, 12) if peak else 0.0,
            }
        )
        return _finish(
            current_state,
            command,
            current_state.model_copy(update={"risk": risk}),
            "ExternalEquityUpdated",
            {"current_equity": command.current_equity},
        )

    if isinstance(command, RecordExternalResult):
        if not math.isfinite(command.pnl):
            raise RiskStateError("pnl must be finite")
        equity = current_state.risk.current_equity + command.pnl
        if equity < 0:
            raise RiskStateError("result cannot make equity negative")
        peak = max(current_state.risk.peak_equity, equity)
        loss = max(0.0, -command.pnl)
        risk = current_state.risk.model_copy(
            update={
                "current_equity": equity,
                "peak_equity": peak,
                "current_drawdown": round(1 - equity / peak, 12) if peak else 0.0,
                "realized_daily_loss": current_state.risk.realized_daily_loss + loss,
                "daily_stop_losses": current_state.risk.daily_stop_losses
                + int(command.stopped_out and loss > 0),
            }
        )
        return _finish(
            current_state,
            command,
            current_state.model_copy(update={"risk": risk}),
            "ExternalResultRecorded",
            {"pnl": command.pnl, "stopped_out": command.stopped_out},
        )

    raise RiskStateError(f"unsupported command: {type(command).__name__}")


class AccountStateStore:
    """JSON materialized state + JSONL facts, committed through a local WAL."""

    def __init__(
        self,
        path: str | Path,
        *,
        events_path: str | Path | None = None,
        lock_timeout_seconds: float = 5.0,
        cny_per_usdt: float = 1.0,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.events_path = (
            Path(events_path).expanduser().resolve()
            if events_path
            else self.path.with_name("account-events.jsonl")
        )
        self.audit_path = self.events_path
        self.wal_path = self.path.with_name(f".{self.path.name}.wal")
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")
        self.lock_timeout_seconds = lock_timeout_seconds
        if cny_per_usdt <= 0:
            raise ValueError("cny_per_usdt must be positive")
        self.cny_per_usdt = cny_per_usdt

    @contextmanager
    def _lock(self) -> Iterator[None]:
        if fcntl is None:
            raise RiskStateError("account-state locking requires POSIX")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise RiskStateError("timed out acquiring account-state lock") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = handle.name
                json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except (OSError, TypeError, ValueError) as exc:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
            raise RiskStateError(f"failed to atomically write {path}") from exc

    def _append_events(self, events: list[AccountEvent]) -> None:
        if not events:
            return
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        existing = (
            {
                json.loads(line)["event_id"]
                for line in self.events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
            if self.events_path.exists()
            else set()
        )
        try:
            with self.events_path.open("a", encoding="utf-8") as handle:
                for event in events:
                    if event.event_id not in existing:
                        handle.write(
                            json.dumps(event.model_dump(mode="json"), allow_nan=False) + "\n"
                        )
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            raise RiskStateError("account event log is corrupt or not writable") from exc

    def _recover(self) -> None:
        if not self.wal_path.exists():
            return
        try:
            payload = json.loads(self.wal_path.read_text(encoding="utf-8"))
            state = AccountState.model_validate(payload["state"])
            events = [AccountEvent.model_validate(event) for event in payload["events"]]
        except (OSError, KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise RiskStateError("account WAL is corrupt; refusing automatic recovery") from exc
        self._append_events(events)
        self._write_atomic(self.path, state.model_dump(mode="json"))
        self.wal_path.unlink()

    def _load(self) -> AccountState:
        self._recover()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("state_version") == 2 and "schema_version" not in payload:
                return self._migrate_legacy_risk(payload)
            return AccountState.model_validate(payload)
        except FileNotFoundError:
            raise RiskStateError(
                f"account state does not exist: {self.path}; run 'risk initialize' first"
            ) from None
        except (OSError, json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise RiskStateError(f"account state is corrupt: {self.path}") from exc

    def _migrate_legacy_risk(self, payload: dict[str, Any]) -> AccountState:
        """Migrate the v2 risk-only file once, preserving a byte-for-byte backup."""

        try:
            legacy = RiskState.model_validate(payload)
        except ValidationError as exc:
            raise RiskStateError("legacy risk state is corrupt; migration aborted") from exc
        backup = self.path.with_name(f"{self.path.name}.v2.{uuid.uuid4().hex}.bak")
        try:
            shutil.copy2(self.path, backup)
        except OSError as exc:
            raise RiskStateError("failed to back up legacy risk state") from exc
        timestamp = datetime.combine(legacy.date, datetime.min.time(), tzinfo=UTC)
        state = empty_account_state(timestamp)
        initial_cash = legacy.current_equity_cny / self.cny_per_usdt
        initialized, _ = apply_command(
            state,
            InitializeAccount(
                command_id=f"migration-{uuid.uuid4()}",
                timestamp=timestamp,
                expected_state_version=state.state_version,
                initial_cash=max(initial_cash, 1e-12),
            ),
        )
        peak = legacy.peak_equity_cny / self.cny_per_usdt
        risk = AccountRiskState(
            date=legacy.date,
            daily_stop_losses=legacy.daily_stop_losses,
            realized_daily_loss=legacy.daily_realized_loss_cny / self.cny_per_usdt,
            daily_start_equity=legacy.daily_start_equity_cny / self.cny_per_usdt,
            current_equity=initial_cash,
            peak_equity=peak,
            current_drawdown=legacy.current_drawdown,
        )
        migrated = initialized.model_copy(
            update={
                "risk": risk,
                "processed_commands": [
                    *initialized.processed_commands,
                    *legacy.processed_trade_ids,
                ],
            }
        )
        migrated = AccountState.model_validate(migrated.model_dump())
        event = AccountEvent(
            event_id=str(uuid.uuid4()),
            command_id=initialized.processed_commands[-1],
            timestamp=timestamp,
            event_type="LegacyRiskStateMigrated",
            state_version=migrated.state_version,
            state_hash=_state_hash(migrated),
            data={"backup_file": backup.name, "source_schema_version": 2},
        )
        self._append_events([event])
        self._write_atomic(self.path, migrated.model_dump(mode="json"))
        return migrated

    def execute(self, command: AccountCommand) -> tuple[AccountState, list[AccountEvent]]:
        with self._lock():
            current = self._load()
            updated, events = apply_command(current, command)
            if not events:
                return updated, []
            wal = {
                "state": updated.model_dump(mode="json"),
                "events": [e.model_dump(mode="json") for e in events],
            }
            self._write_atomic(self.wal_path, wal)
            self._append_events(events)
            self._write_atomic(self.path, updated.model_dump(mode="json"))
            self.wal_path.unlink()
            LOGGER.info(
                "account command committed",
                extra={
                    "event_data": {
                        "event_name": "account_command",
                        "operation": command.command_type,
                        "result": "success",
                        "state_version": updated.state_version,
                        "command_id": command.command_id,
                    }
                },
            )
            return updated, events

    def initialize(
        self,
        *,
        timestamp: datetime,
        initial_cash: float,
        reserved_cash: float = 0.0,
        force: bool = False,
    ) -> AccountState:
        with self._lock():
            if self.path.exists() and not force:
                raise RiskStateError(f"account state already exists: {self.path}")
            if self.path.exists() and force:
                backup = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.bak")
                shutil.copy2(self.path, backup)
            state = empty_account_state(timestamp)
            command = InitializeAccount(
                command_id=str(uuid.uuid4()),
                timestamp=timestamp,
                expected_state_version=state.state_version,
                initial_cash=initial_cash,
                reserved_cash=reserved_cash,
            )
            initialized, events = apply_command(state, command)
            self._write_atomic(
                self.wal_path,
                {
                    "state": initialized.model_dump(mode="json"),
                    "events": [e.model_dump(mode="json") for e in events],
                },
            )
            self._append_events(events)
            self._write_atomic(self.path, initialized.model_dump(mode="json"))
            self.wal_path.unlink()
            return initialized

    def load(self) -> AccountState:
        with self._lock():
            return self._load()

    def load_or_initialize(
        self, *, timestamp: datetime, initial_cash: float
    ) -> tuple[AccountState, bool]:
        if self.path.exists():
            return self.load(), False
        return self.initialize(timestamp=timestamp, initial_cash=initial_cash), True

    def history(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("history limit must be between 1 and 1000")
        with self._lock():
            if not self.events_path.exists():
                return []
            try:
                return [
                    json.loads(line)
                    for line in self.events_path.read_text(encoding="utf-8").splitlines()[-limit:]
                ]
            except (OSError, json.JSONDecodeError) as exc:
                raise RiskStateError("account event log is corrupt") from exc

    def verify_consistency(self) -> bool:
        """Verify that the last durable fact identifies the materialized state."""

        with self._lock():
            state = self._load()
            if not self.events_path.exists():
                raise RiskStateError("account event log is missing")
            try:
                lines = [
                    line
                    for line in self.events_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                last = AccountEvent.model_validate_json(lines[-1])
            except (OSError, IndexError, ValidationError) as exc:
                raise RiskStateError("account event log is corrupt") from exc
            if last.state_version != state.state_version or last.state_hash != _state_hash(state):
                raise RiskStateError("account event log and materialized state do not reconcile")
            return True
