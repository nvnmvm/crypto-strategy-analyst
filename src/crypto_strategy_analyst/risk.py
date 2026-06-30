"""Persistent, audited, process-safe risk state and position sizing."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from datetime import date as CalendarDate
from pathlib import Path
from typing import Any, Literal

try:  # POSIX file locks are available on supported Linux and macOS runtimes.
    import fcntl
except ImportError:  # pragma: no cover - Windows is not a supported runtime
    fcntl = None  # type: ignore[assignment]

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .config import RiskConfig
from .errors import PositionConstraintError, RiskStateError
from .models import PositionSuggestion, SymbolTradingRules
from .trading_rules import floor_to_increment


class RiskState(BaseModel):
    """Versioned risk controls and account equity persisted across restarts."""

    model_config = ConfigDict(extra="forbid")

    state_version: Literal[2] = 2
    date: CalendarDate = Field(default_factory=lambda: datetime.now(UTC).date())
    daily_stop_losses: int = Field(default=0, ge=0)
    daily_realized_loss_cny: float = Field(default=0.0, ge=0)
    daily_start_equity_cny: float = Field(default=0.0, ge=0)
    current_equity_cny: float = Field(default=0.0, ge=0)
    peak_equity_cny: float = Field(default=0.0, ge=0)
    current_drawdown: float = Field(default=0.0, ge=0, le=1)
    processed_trade_ids: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("processed_trade_ids")
    @classmethod
    def validate_trade_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("processed trade IDs must contain 1 to 200 characters")
        if len(values) != len(set(values)):
            raise ValueError("processed trade IDs must be unique")
        return values

    @model_validator(mode="after")
    def validate_equity_history(self) -> RiskState:
        if self.current_equity_cny > self.peak_equity_cny:
            raise ValueError("current_equity_cny cannot exceed peak_equity_cny")
        expected_drawdown = (
            1 - self.current_equity_cny / self.peak_equity_cny
            if self.peak_equity_cny > 0
            else 0.0
        )
        if abs(self.current_drawdown - expected_drawdown) > 1e-9:
            raise ValueError("current_drawdown is inconsistent with current and peak equity")
        return self

    def rolled_to(self, current_date: CalendarDate) -> RiskState:
        """Reset daily counters on a later UTC date; preserve equity and IDs."""

        if current_date <= self.date:
            return self.model_copy(deep=True)
        return self.model_copy(
            update={
                "date": current_date,
                "daily_stop_losses": 0,
                "daily_realized_loss_cny": 0.0,
                "daily_start_equity_cny": self.current_equity_cny,
            },
            deep=True,
        )

    def reset_daily(self, current_date: CalendarDate) -> RiskState:
        """Manually clear only daily counters for correction or testing."""

        return self.model_copy(
            update={
                "date": current_date,
                "daily_stop_losses": 0,
                "daily_realized_loss_cny": 0.0,
                "daily_start_equity_cny": self.current_equity_cny,
            },
            deep=True,
        )

    def with_equity(self, equity_cny: float) -> RiskState:
        """Set current equity and recompute all-time peak and drawdown."""

        if not math.isfinite(equity_cny) or equity_cny < 0:
            raise ValueError("equity_cny must be finite and non-negative")
        peak = max(self.peak_equity_cny, equity_cny)
        drawdown = 1 - equity_cny / peak if peak > 0 else 0.0
        return self.model_copy(
            update={
                "current_equity_cny": equity_cny,
                "peak_equity_cny": peak,
                "current_drawdown": round(min(1.0, drawdown), 12),
            },
            deep=True,
        )

    def with_realized_result(
        self,
        pnl_cny: float,
        *,
        stopped_out: bool,
        trade_id: str | None = None,
    ) -> RiskState:
        """Record PnL once using ``new equity = old equity + pnl``."""

        if not math.isfinite(pnl_cny):
            raise ValueError("pnl_cny must be finite")
        normalized_trade_id = trade_id.strip() if trade_id is not None else None
        if normalized_trade_id is not None:
            if not normalized_trade_id or len(normalized_trade_id) > 200:
                raise ValueError("trade_id must contain 1 to 200 characters")
            if normalized_trade_id in self.processed_trade_ids:
                raise RiskStateError(f"trade_id already processed: {normalized_trade_id}")
        new_equity = self.current_equity_cny + pnl_cny
        if new_equity < 0:
            raise ValueError("trade result cannot make current equity negative")
        loss = max(0.0, -pnl_cny)
        processed = self.processed_trade_ids
        if normalized_trade_id is not None:
            processed = [*processed, normalized_trade_id][-1000:]
        updated = self.model_copy(
            update={
                "daily_stop_losses": self.daily_stop_losses + int(stopped_out and loss > 0),
                "daily_realized_loss_cny": self.daily_realized_loss_cny + loss,
                "processed_trade_ids": processed,
            },
            deep=True,
        )
        return updated.with_equity(new_equity)


class RiskStateStore:
    """Atomic JSON state plus append-only audit log under one POSIX lock."""

    def __init__(
        self,
        path: str | Path,
        *,
        audit_path: str | Path | None = None,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        if lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be positive")
        self.path = Path(path).expanduser().resolve()
        self.audit_path = (
            Path(audit_path).expanduser().resolve()
            if audit_path is not None
            else self.path.with_name("risk-events.jsonl")
        )
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.lock_timeout_seconds = lock_timeout_seconds

    @contextmanager
    def _lock(self) -> Iterator[None]:
        if fcntl is None:
            raise RiskStateError("risk-state locking requires a POSIX runtime")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise RiskStateError(
                            f"timed out acquiring risk-state lock: {self.lock_path}"
                        ) from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _new_state(current_date: CalendarDate, equity_cny: float) -> RiskState:
        return RiskState(
            date=current_date,
            daily_start_equity_cny=equity_cny,
            current_equity_cny=equity_cny,
            peak_equity_cny=equity_cny,
        )

    @staticmethod
    def _event(
        operation: str,
        before: RiskState | None,
        after: RiskState,
        **details: Any,
    ) -> dict[str, Any]:
        return {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "operation": operation,
            "before_equity_cny": before.current_equity_cny if before else None,
            "after_equity_cny": after.current_equity_cny,
            "daily_stop_losses_after": after.daily_stop_losses,
            **details,
        }

    def _append_audit_unlocked(self, event: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, TypeError, ValueError) as exc:
            raise RiskStateError(f"failed to append risk audit log: {self.audit_path}") from exc

    def _backup_migration_unlocked(self) -> Path:
        backup = self.path.with_name(f"{self.path.name}.v1.{uuid.uuid4().hex}.bak")
        try:
            shutil.copy2(self.path, backup)
            with backup.open("rb") as handle:
                os.fsync(handle.fileno())
            return backup
        except OSError as exc:
            backup.unlink(missing_ok=True)
            raise RiskStateError(f"failed to back up legacy risk state: {self.path}") from exc

    def _load_unlocked(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
        require_exists: bool = False,
    ) -> tuple[RiskState, list[dict[str, Any]]]:
        if not self.path.exists():
            if require_exists:
                raise RiskStateError(
                    f"risk state does not exist: {self.path}; run 'risk initialize' first"
                )
            return self._new_state(current_date, initial_equity_cny), []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("risk state root must be an object")
            migration_required = payload.get("state_version") != 2
            backup: Path | None = None
            if migration_required:
                backup = self._backup_migration_unlocked()
                payload["state_version"] = 2
                payload.setdefault("processed_trade_ids", [])
            if "current_equity_cny" not in payload:
                peak = float(payload.get("peak_equity_cny", initial_equity_cny))
                drawdown = float(payload.get("current_drawdown", 0.0))
                payload["current_equity_cny"] = max(0.0, peak * (1 - drawdown))
            payload.setdefault("daily_start_equity_cny", payload["current_equity_cny"])
            payload.setdefault("processed_trade_ids", [])
            state = RiskState.model_validate(payload)
        except RiskStateError:
            raise
        except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise RiskStateError(f"risk state is corrupt or migration failed: {self.path}") from exc
        events: list[dict[str, Any]] = []
        if migration_required:
            events.append(
                self._event(
                    "migrate_state_v2",
                    state,
                    state,
                    backup_path=str(backup),
                )
            )
        rolled = state.rolled_to(current_date)
        if rolled.date != state.date:
            events.append(
                self._event(
                    "date_rollover",
                    state,
                    rolled,
                    previous_date=state.date.isoformat(),
                    new_date=rolled.date.isoformat(),
                )
            )
        return rolled, events

    def _save_unlocked(self, state: RiskState) -> None:
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
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            if temporary_path:
                Path(temporary_path).unlink(missing_ok=True)
            raise RiskStateError(f"failed to atomically save risk state: {self.path}") from exc

    def _persist_unlocked(self, state: RiskState, events: list[dict[str, Any]]) -> None:
        self._save_unlocked(state)
        for event in events:
            self._append_audit_unlocked(event)

    def load(self, *, current_date: CalendarDate, initial_equity_cny: float) -> RiskState:
        """Read, migrate, and persist a rollover while holding the state lock."""

        with self._lock():
            state, events = self._load_unlocked(
                current_date=current_date,
                initial_equity_cny=initial_equity_cny,
            )
            if events:
                self._persist_unlocked(state, events)
            return state

    def load_or_initialize(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
    ) -> tuple[RiskState, bool]:
        with self._lock():
            created = not self.path.exists()
            state, events = self._load_unlocked(
                current_date=current_date,
                initial_equity_cny=initial_equity_cny,
            )
            if created:
                events.append(self._event("initialize", None, state))
            self._persist_unlocked(state, events)
            return state, created

    def load_existing(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
    ) -> RiskState:
        with self._lock():
            state, events = self._load_unlocked(
                current_date=current_date,
                initial_equity_cny=initial_equity_cny,
                require_exists=True,
            )
            if events:
                self._persist_unlocked(state, events)
            return state

    def save(self, state: RiskState) -> None:
        with self._lock():
            self._save_unlocked(state)

    def initialize(
        self,
        *,
        current_date: CalendarDate,
        equity_cny: float,
        force: bool = False,
    ) -> RiskState:
        if not math.isfinite(equity_cny) or equity_cny < 0:
            raise ValueError("equity_cny must be finite and non-negative")
        with self._lock():
            existed = self.path.exists()
            if existed and not force:
                raise RiskStateError(
                    f"risk state already exists: {self.path}; pass --force to overwrite"
                )
            state = self._new_state(current_date, equity_cny)
            operation = "force_initialize" if existed else "initialize"
            self._persist_unlocked(state, [self._event(operation, None, state)])
            return state

    def update(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
        operation: str,
        updater: Callable[[RiskState], RiskState],
        details: dict[str, Any] | None = None,
    ) -> RiskState:
        with self._lock():
            state, lifecycle_events = self._load_unlocked(
                current_date=current_date,
                initial_equity_cny=initial_equity_cny,
                require_exists=True,
            )
            updated = RiskState.model_validate(updater(state).model_dump())
            event = self._event(operation, state, updated, **(details or {}))
            self._persist_unlocked(updated, [*lifecycle_events, event])
            return updated

    def update_equity(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
        equity_cny: float,
    ) -> RiskState:
        return self.update(
            current_date=current_date,
            initial_equity_cny=initial_equity_cny,
            operation="update_equity",
            updater=lambda state: state.with_equity(equity_cny),
            details={"equity_cny": equity_cny},
        )

    def record_trade(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
        trade_id: str,
        pnl_cny: float,
        stopped_out: bool,
    ) -> RiskState:
        return self.update(
            current_date=current_date,
            initial_equity_cny=initial_equity_cny,
            operation="record_trade",
            updater=lambda state: state.with_realized_result(
                pnl_cny,
                stopped_out=stopped_out,
                trade_id=trade_id,
            ),
            details={"trade_id": trade_id, "pnl_cny": pnl_cny, "stopped_out": stopped_out},
        )

    def reset_daily(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
    ) -> RiskState:
        return self.update(
            current_date=current_date,
            initial_equity_cny=initial_equity_cny,
            operation="reset_daily",
            updater=lambda state: state.reset_daily(current_date),
        )

    def history(self, *, limit: int) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("history limit must be between 1 and 1000")
        with self._lock():
            if not self.audit_path.exists():
                return []
            try:
                lines = self.audit_path.read_text(encoding="utf-8").splitlines()
                return [json.loads(line) for line in lines[-limit:]]
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                raise RiskStateError(f"risk audit log is corrupt: {self.audit_path}") from exc


def risk_blockers(config: RiskConfig, state: RiskState) -> list[str]:
    blockers: list[str] = []
    if state.daily_stop_losses >= config.daily_stop_count:
        blockers.append("daily_stop_count_reached")
    daily_loss_limit_cny = state.daily_start_equity_cny * config.daily_max_loss
    if state.daily_realized_loss_cny >= daily_loss_limit_cny and (
        state.daily_realized_loss_cny > 0 or state.current_equity_cny <= 0
    ):
        blockers.append("daily_loss_limit_reached")
    if state.current_drawdown >= config.max_drawdown:
        blockers.append("maximum_drawdown_protection_active")
    if state.current_equity_cny <= 0:
        blockers.append("account_equity_depleted")
    return blockers


def risk_status(config: RiskConfig, state: RiskState) -> dict[str, object]:
    locks = risk_blockers(config, state)
    return {
        "state_version": state.state_version,
        "date": state.date.isoformat(),
        "current_equity_cny": state.current_equity_cny,
        "peak_equity_cny": state.peak_equity_cny,
        "current_drawdown": state.current_drawdown,
        "daily_stop_losses": state.daily_stop_losses,
        "daily_realized_loss_cny": state.daily_realized_loss_cny,
        "daily_start_equity_cny": state.daily_start_equity_cny,
        "processed_trade_id_count": len(state.processed_trade_ids),
        "daily_stop_limit_reached": "daily_stop_count_reached" in locks,
        "daily_loss_limit_reached": "daily_loss_limit_reached" in locks,
        "maximum_drawdown_limit_reached": "maximum_drawdown_protection_active" in locks,
        "locks": locks,
        "new_trade_allowed": not locks,
    }


def calculate_position(
    *,
    entry_price: float,
    stop_price: float,
    config: RiskConfig,
    account_equity_cny: float | None = None,
    trading_rules: SymbolTradingRules | None = None,
) -> PositionSuggestion:
    """Size a spot position, always rounding down under public exchange rules."""

    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        raise ValueError("long position requires 0 < stop_price < entry_price")
    equity_cny = config.account_equity_cny if account_equity_cny is None else account_equity_cny
    if equity_cny <= 0:
        raise ValueError("account_equity_cny must be positive for position sizing")
    rules = trading_rules
    normalized_entry = (
        floor_to_increment(entry_price, rules.price_tick_size) if rules else entry_price
    )
    normalized_stop = floor_to_increment(stop_price, rules.price_tick_size) if rules else stop_price
    if normalized_stop <= 0 or normalized_stop >= normalized_entry:
        raise PositionConstraintError("tick-size rounding invalidated the stop distance")
    risk_limit = equity_cny * config.risk_per_trade
    stop_fraction = (normalized_entry - normalized_stop) / normalized_entry
    unconstrained_notional = risk_limit / stop_fraction
    maximum_notional = equity_cny * config.max_position_fraction
    notional = min(unconstrained_notional, maximum_notional)
    raw_quantity = notional / (normalized_entry * config.cny_per_usdt)
    step_size = rules.quantity_step_size if rules else 1e-10
    quantity = floor_to_increment(raw_quantity, step_size)
    if rules:
        if quantity < rules.minimum_quantity:
            raise PositionConstraintError("quantity_below_exchange_minimum")
        if rules.maximum_quantity is not None:
            quantity = min(quantity, floor_to_increment(rules.maximum_quantity, step_size))
    quote_notional = quantity * normalized_entry
    if rules and quote_notional < rules.minimum_notional:
        raise PositionConstraintError("notional_below_exchange_minimum")
    actual_notional = quote_notional * config.cny_per_usdt
    actual_risk = quantity * (normalized_entry - normalized_stop) * config.cny_per_usdt
    if actual_risk > risk_limit + 1e-8:
        raise PositionConstraintError("rounded_position_exceeds_risk_limit")
    return PositionSuggestion(
        quantity=round(quantity, 10),
        position_notional_cny=round(actual_notional, 2),
        risk_amount_cny=round(actual_risk, 2),
        position_fraction=round(actual_notional / equity_cny, 6),
        quote_to_account_rate=config.cny_per_usdt,
        entry_price=normalized_entry,
        stop_price=normalized_stop,
        minimum_notional=rules.minimum_notional if rules else 0.0,
        quantity_step_size=step_size,
    )
