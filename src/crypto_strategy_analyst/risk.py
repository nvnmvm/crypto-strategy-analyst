"""Persistent, process-safe risk state and position sizing."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from datetime import date as CalendarDate
from pathlib import Path

try:  # POSIX file locks are available on supported Linux and macOS runtimes.
    import fcntl
except ImportError:  # pragma: no cover - Windows is not a supported runtime
    fcntl = None  # type: ignore[assignment]

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .config import RiskConfig
from .errors import RiskStateError
from .models import PositionSuggestion


class RiskState(BaseModel):
    """Risk controls and account equity that survive process restarts."""

    model_config = ConfigDict(extra="forbid")

    date: CalendarDate = Field(default_factory=lambda: datetime.now(UTC).date())
    daily_stop_losses: int = Field(default=0, ge=0)
    daily_realized_loss_cny: float = Field(default=0.0, ge=0)
    daily_start_equity_cny: float = Field(default=0.0, ge=0)
    current_equity_cny: float = Field(default=0.0, ge=0)
    peak_equity_cny: float = Field(default=0.0, ge=0)
    current_drawdown: float = Field(default=0.0, ge=0, le=1)

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
        """Reset daily counters on a later UTC date; preserve equity history."""

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
        """Set current equity and recompute the all-time peak and drawdown."""

        if not math.isfinite(equity_cny) or equity_cny < 0:
            raise ValueError("equity_cny cannot be negative")
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

    def with_realized_result(self, pnl_cny: float, *, stopped_out: bool) -> RiskState:
        """Record PnL using the fixed rule ``new equity = old equity + pnl``."""

        if not math.isfinite(pnl_cny):
            raise ValueError("pnl_cny must be finite")
        new_equity = self.current_equity_cny + pnl_cny
        if new_equity < 0:
            raise ValueError("trade result cannot make current equity negative")
        loss = max(0.0, -pnl_cny)
        updated = self.model_copy(
            update={
                "daily_stop_losses": self.daily_stop_losses + int(stopped_out and loss > 0),
                "daily_realized_loss_cny": self.daily_realized_loss_cny + loss,
            },
            deep=True,
        )
        return updated.with_equity(new_equity)


class RiskStateStore:
    """Atomic JSON store with a timeout-bounded POSIX process lock.

    Lock scope for mutations covers read, date rollover, modification, fsync,
    and atomic replacement. The adjacent ``.lock`` file is intentionally kept
    so concurrent processes always contend on the same inode.
    """

    def __init__(self, path: str | Path, *, lock_timeout_seconds: float = 5.0) -> None:
        if lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be positive")
        self.path = Path(path).expanduser().resolve()
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

    def _load_unlocked(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
        require_exists: bool = False,
    ) -> RiskState:
        if not self.path.exists():
            if require_exists:
                raise RiskStateError(
                    f"risk state does not exist: {self.path}; run 'risk initialize' first"
                )
            return self._new_state(current_date, initial_equity_cny)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("risk state root must be an object")
            if "current_equity_cny" not in payload:
                peak = float(payload.get("peak_equity_cny", initial_equity_cny))
                drawdown = float(payload.get("current_drawdown", 0.0))
                payload["current_equity_cny"] = max(0.0, peak * (1 - drawdown))
            if "daily_start_equity_cny" not in payload:
                payload["daily_start_equity_cny"] = payload["current_equity_cny"]
            state = RiskState.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise RiskStateError(f"risk state is corrupt: {self.path}") from exc
        return state.rolled_to(current_date)

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

    def load(self, *, current_date: CalendarDate, initial_equity_cny: float) -> RiskState:
        """Read a state safely; missing files return an unsaved initialized state."""

        with self._lock():
            return self._load_unlocked(
                current_date=current_date,
                initial_equity_cny=initial_equity_cny,
            )

    def load_or_initialize(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
    ) -> tuple[RiskState, bool]:
        """Load and persist rollover, or atomically create a missing state."""

        with self._lock():
            created = not self.path.exists()
            state = self._load_unlocked(
                current_date=current_date,
                initial_equity_cny=initial_equity_cny,
            )
            self._save_unlocked(state)
            return state, created

    def load_existing(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
    ) -> RiskState:
        """Load an existing state and atomically persist any date rollover."""

        with self._lock():
            state = self._load_unlocked(
                current_date=current_date,
                initial_equity_cny=initial_equity_cny,
                require_exists=True,
            )
            self._save_unlocked(state)
            return state

    def save(self, state: RiskState) -> None:
        """Atomically replace the state while holding the process lock."""

        with self._lock():
            self._save_unlocked(state)

    def initialize(
        self,
        *,
        current_date: CalendarDate,
        equity_cny: float,
        force: bool = False,
    ) -> RiskState:
        """Create the first state, refusing overwrite unless ``force`` is set."""

        if not math.isfinite(equity_cny) or equity_cny < 0:
            raise ValueError("equity_cny cannot be negative")
        with self._lock():
            if self.path.exists() and not force:
                raise RiskStateError(
                    f"risk state already exists: {self.path}; pass --force to overwrite"
                )
            state = self._new_state(current_date, equity_cny)
            self._save_unlocked(state)
            return state

    def update(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
        updater: Callable[[RiskState], RiskState],
    ) -> RiskState:
        """Apply one read-modify-save transaction without a lost-update window."""

        with self._lock():
            state = self._load_unlocked(
                current_date=current_date,
                initial_equity_cny=initial_equity_cny,
                require_exists=True,
            )
            updated = RiskState.model_validate(updater(state).model_dump())
            self._save_unlocked(updated)
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
            updater=lambda state: state.with_equity(equity_cny),
        )

    def record_trade(
        self,
        *,
        current_date: CalendarDate,
        initial_equity_cny: float,
        pnl_cny: float,
        stopped_out: bool,
    ) -> RiskState:
        return self.update(
            current_date=current_date,
            initial_equity_cny=initial_equity_cny,
            updater=lambda state: state.with_realized_result(
                pnl_cny,
                stopped_out=stopped_out,
            ),
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
            updater=lambda state: state.reset_daily(current_date),
        )


def risk_blockers(config: RiskConfig, state: RiskState) -> list[str]:
    """Return deterministic lock reasons for the current persisted risk state."""

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
    """Build the stable JSON status payload used by the risk CLI."""

    locks = risk_blockers(config, state)
    return {
        "date": state.date.isoformat(),
        "current_equity_cny": state.current_equity_cny,
        "peak_equity_cny": state.peak_equity_cny,
        "current_drawdown": state.current_drawdown,
        "daily_stop_losses": state.daily_stop_losses,
        "daily_realized_loss_cny": state.daily_realized_loss_cny,
        "daily_start_equity_cny": state.daily_start_equity_cny,
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
) -> PositionSuggestion:
    """Size a long spot position from current equity and maximum accepted loss."""

    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        raise ValueError("long position requires 0 < stop_price < entry_price")
    equity_cny = config.account_equity_cny if account_equity_cny is None else account_equity_cny
    if equity_cny <= 0:
        raise ValueError("account_equity_cny must be positive for position sizing")
    risk_amount = equity_cny * config.risk_per_trade
    stop_fraction = (entry_price - stop_price) / entry_price
    unconstrained_notional = risk_amount / stop_fraction
    maximum_notional = equity_cny * config.max_position_fraction
    notional = min(unconstrained_notional, maximum_notional)
    entry_price_cny = entry_price * config.cny_per_usdt
    quantity = notional / entry_price_cny
    actual_risk = notional * stop_fraction
    return PositionSuggestion(
        quantity=round(quantity, 10),
        position_notional_cny=round(notional, 2),
        risk_amount_cny=round(actual_risk, 2),
        position_fraction=round(notional / equity_cny, 6),
        quote_to_account_rate=config.cny_per_usdt,
    )
