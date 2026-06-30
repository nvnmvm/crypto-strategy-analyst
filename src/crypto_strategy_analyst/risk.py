"""Persistent risk locks and position sizing."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from datetime import date as CalendarDate
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import RiskConfig
from .errors import RiskStateError
from .models import PositionSuggestion


class RiskState(BaseModel):
    """Risk controls that survive process restarts."""

    model_config = ConfigDict(extra="forbid")

    date: CalendarDate = Field(default_factory=lambda: datetime.now(UTC).date())
    daily_stop_losses: int = Field(default=0, ge=0)
    daily_realized_loss_cny: float = Field(default=0.0, ge=0)
    peak_equity_cny: float = Field(default=0.0, ge=0)
    current_drawdown: float = Field(default=0.0, ge=0, le=1)

    def rolled_to(self, current_date: CalendarDate) -> RiskState:
        """Reset daily fields only; preserve peak equity and drawdown."""

        if current_date <= self.date:
            return self.model_copy(deep=True)
        return self.model_copy(
            update={
                "date": current_date,
                "daily_stop_losses": 0,
                "daily_realized_loss_cny": 0.0,
            },
            deep=True,
        )

    def with_equity(self, equity_cny: float) -> RiskState:
        if equity_cny < 0:
            raise ValueError("equity_cny cannot be negative")
        peak = max(self.peak_equity_cny, equity_cny)
        drawdown = 1 - equity_cny / peak if peak > 0 else 0.0
        return self.model_copy(
            update={"peak_equity_cny": peak, "current_drawdown": min(1.0, drawdown)},
            deep=True,
        )

    def with_realized_result(self, pnl_cny: float, *, stopped_out: bool) -> RiskState:
        loss = max(0.0, -pnl_cny)
        return self.model_copy(
            update={
                "daily_stop_losses": self.daily_stop_losses + int(stopped_out and loss > 0),
                "daily_realized_loss_cny": self.daily_realized_loss_cny + loss,
            },
            deep=True,
        )


class RiskStateStore:
    """JSON risk-state store using same-directory atomic replacement."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def load(self, *, current_date: CalendarDate, initial_equity_cny: float) -> RiskState:
        if not self.path.exists():
            return RiskState(date=current_date, peak_equity_cny=initial_equity_cny)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            state = RiskState.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise RiskStateError(f"risk state is corrupt: {self.path}") from exc
        return state.rolled_to(current_date)

    def save(self, state: RiskState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = handle.name
                json.dump(state.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        except OSError as exc:
            if temporary_path:
                Path(temporary_path).unlink(missing_ok=True)
            raise RiskStateError(f"failed to atomically save risk state: {self.path}") from exc


def risk_blockers(config: RiskConfig, state: RiskState) -> list[str]:
    blockers: list[str] = []
    if state.daily_stop_losses >= config.daily_stop_count:
        blockers.append("daily_stop_count_reached")
    loss_fraction = state.daily_realized_loss_cny / config.account_equity_cny
    if loss_fraction >= config.daily_max_loss:
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
