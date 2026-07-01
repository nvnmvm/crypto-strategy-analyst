"""Public schema v2.0 shared by live analysis, backtests and adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignalStatus(StrEnum):
    NO_TRADE = "no_trade"
    WATCH = "watch"
    NEAR_KEY_LEVEL = "near_key_level"
    CANDIDATE = "candidate"
    ENTRY_VALIDATED = "entry_validated"
    ENTRY_CANCELLED = "entry_cancelled"
    POSITION_MANAGEMENT = "position_management"
    EXIT_SIGNAL = "exit_signal"
    RISK_ALERT = "risk_alert"


class Availability(StrEnum):
    AVAILABLE = "available"
    STALE = "stale"
    NOT_AVAILABLE = "not_available"
    FAILED = "failed"


class Horizon(StrEnum):
    SHORT = "short"
    SWING = "swing"
    LONG = "long"


class DataPoint(StrictModel):
    status: Availability
    source: str
    observed_at: datetime | None = None
    freshness_seconds: float | None = Field(default=None, ge=0)
    value: Any = None
    detail: str | None = None


class Candle(StrictModel):
    open_time: datetime
    close_time: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def valid_range(self) -> Candle:
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is below candle range")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is above candle range")
        if self.close_time <= self.open_time:
            raise ValueError("close_time must follow open_time")
        return self


class MarketSnapshot(StrictModel):
    symbol: str
    as_of: datetime
    price: float = Field(gt=0)
    candles: dict[str, list[Candle]]
    trading_rules: DataPoint
    timestamp: DataPoint
    volume: DataPoint
    auxiliary: dict[str, DataPoint] = Field(default_factory=dict)

    def completed(self, timeframe: str) -> list[Candle]:
        """Return only bars closed by as_of; this is the no-lookahead boundary."""
        return [bar for bar in self.candles.get(timeframe, []) if bar.close_time <= self.as_of]


class ComponentScores(StrictModel):
    technical: float = Field(ge=0, le=100)
    derivatives: float = Field(ge=0, le=100)
    onchain: float = Field(ge=0, le=100)
    macro: float = Field(ge=0, le=100)
    relative_strength: float = Field(ge=0, le=100)
    asset_specific: float = Field(ge=0, le=100)


class PriceLevel(StrictModel):
    kind: Literal["support", "resistance"]
    price: float = Field(gt=0)
    timeframe: str
    strength: float = Field(ge=0, le=100)
    touches: int = Field(ge=1)


class HorizonPlan(StrictModel):
    horizon: Horizon
    status: SignalStatus
    direction: Literal["long", "flat"] = "flat"
    strategy: str
    timeframes: list[str]
    entry: float | None = Field(default=None, gt=0)
    stop: float | None = Field(default=None, gt=0)
    take_profit_1: float | None = Field(default=None, gt=0)
    take_profit_2: float | None = Field(default=None, gt=0)
    reward_risk_1: float | None = Field(default=None, ge=0)
    reward_risk_2: float | None = Field(default=None, ge=0)
    position_fraction: float = Field(default=0, ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    invalidation: list[str] = Field(default_factory=list)


class AnalysisEvent(StrictModel):
    event_id: str
    event_type: SignalStatus
    symbol: str
    horizon: Horizon
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class AnalysisReport(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    profile: str
    market: dict[str, Any]
    data_availability: dict[str, DataPoint]
    scores: ComponentScores
    confidence: float = Field(ge=0, le=100)
    key_levels: list[PriceLevel]
    relative_strength: dict[str, float | str]
    plans: dict[Horizon, HorizonPlan]
    events: list[AnalysisEvent]
    chart_data: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    warnings: list[str]
    limitations: list[str]
    hard_filters: list[str] = Field(default_factory=list)


class OrderDraft(StrictModel):
    draft_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT"]
    quantity: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    reference_price: float = Field(gt=0)
    notional: float = Field(gt=0)
    client_order_id: str
    created_at: datetime
    expires_at: datetime
    confirmation_digest: str


class OrderResult(StrictModel):
    order_id: str
    client_order_id: str
    symbol: str
    status: str
    executed_quantity: float = Field(ge=0)
    average_price: float | None = Field(default=None, gt=0)
    raw_status: dict[str, Any] = Field(default_factory=dict)


class PaperAccount(StrictModel):
    schema_version: Literal[1] = 1
    quote_currency: str = "USDT"
    cash: float = Field(default=600, ge=0)
    peak_equity: float = Field(default=600, ge=0)
    positions: dict[str, float] = Field(default_factory=dict)
    realized_pnl: float = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
