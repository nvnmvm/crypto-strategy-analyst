"""Version 3 public models for analysis, replay and OpenClaw events."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Availability(StrEnum):
    AVAILABLE = "available"
    STALE = "stale"
    NOT_AVAILABLE = "not_available"
    FAILED = "failed"


class Horizon(StrEnum):
    SHORT = "short"
    SWING = "swing"
    LONG = "long"


class MarketRegime(StrEnum):
    STRONG_BULL = "strong_bull"
    BULLISH = "bullish"
    BULL_PULLBACK = "bull_pullback"
    RANGE = "range"
    BEARISH = "bearish"
    CAPITULATION = "capitulation"
    RECOVERY = "recovery"


class SignalStatus(StrEnum):
    NO_TRADE = "no_trade"
    WATCH = "watch"
    NEAR_KEY_LEVEL = "near_key_level"
    CANDIDATE = "candidate"
    ENTRY_VALIDATED = "entry_validated"
    ENTRY_CANCELLED = "entry_cancelled"


class Candle(StrictModel):
    open_time: datetime
    close_time: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> Candle:
        if self.close_time <= self.open_time:
            raise ValueError("close_time must follow open_time")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC range")
        return self


class DataPoint(StrictModel):
    status: Availability
    source: str
    observed_at: datetime | None = None
    freshness_seconds: float | None = Field(default=None, ge=0)
    value: Any = None
    detail: str = ""

    def usable_at(self, at: datetime) -> bool:
        return self.status == Availability.AVAILABLE and (
            self.observed_at is None or self.observed_at <= at
        )


class MarketSnapshot(StrictModel):
    symbol: str
    exchange: str = "binance"
    as_of: datetime
    price: float = Field(gt=0)
    candles: dict[str, list[Candle]]
    trading_rules: DataPoint
    auxiliary: dict[str, DataPoint] = Field(default_factory=dict)

    def completed(self, timeframe: str) -> list[Candle]:
        return [bar for bar in self.candles.get(timeframe, []) if bar.close_time <= self.as_of]


class IndicatorSet(StrictModel):
    close: float
    ema20: float
    ema50: float
    ema200: float
    sma_fast: float
    sma_medium: float
    sma_slow: float
    ema20_slope: float
    rsi: float = Field(ge=0, le=100)
    macd_line: float
    macd_signal: float
    macd_histogram: float
    macd_histogram_change: float
    atr: float = Field(gt=0)
    atr_percent: float = Field(ge=0)
    volume_ratio: float = Field(ge=0)
    trend_strength: float = Field(ge=0, le=100)


class KeyLevel(StrictModel):
    type: Literal["support", "resistance"]
    lower: float = Field(gt=0)
    upper: float = Field(gt=0)
    midpoint: float = Field(gt=0)
    timeframe: str
    strength: float = Field(ge=0, le=100)
    touches: int = Field(ge=1)
    last_reaction_at: datetime
    sources: list[str]
    distance_percent: float
    distance_atr: float


class ScoreCard(StrictModel):
    technical: float = Field(ge=0, le=100)
    derivatives: float | None = Field(default=None, ge=0, le=100)
    onchain: float | None = Field(default=None, ge=0, le=100)
    macro: float | None = Field(default=None, ge=0, le=100)
    relative_strength: float | None = Field(default=None, ge=0, le=100)
    asset_specific: float | None = Field(default=None, ge=0, le=100)
    data_completeness: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)


class PriceRange(StrictModel):
    lower: float = Field(gt=0)
    upper: float = Field(gt=0)


class TakeProfit(StrictModel):
    price: float = Field(gt=0)
    fraction: float = Field(gt=0, le=1)
    source: str


class RiskSuggestion(StrictModel):
    level: Literal["none", "low", "reduced", "normal"]
    risk_fraction: float = Field(ge=0, le=0.03)
    rationale: list[str] = Field(default_factory=list)


class StrategyMatch(StrictModel):
    strategy: str
    matched: bool
    structure_confirmations: list[str]
    secondary_confirmations: list[str]
    failed_conditions: list[str]
    entry_range: PriceRange | None = None
    stop_loss: float | None = Field(default=None, gt=0)
    take_profits: list[TakeProfit] = Field(default_factory=list)
    reward_risk: float | None = Field(default=None, ge=0)
    invalidation_conditions: list[str] = Field(default_factory=list)


class HorizonPlan(StrictModel):
    horizon: Horizon
    status: SignalStatus
    market_regime: MarketRegime
    strategy: str | None = None
    key_levels: list[KeyLevel] = Field(default_factory=list)
    entry_range: PriceRange | None = None
    planned_entry: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profits: list[TakeProfit] = Field(default_factory=list)
    reward_risk: float | None = Field(default=None, ge=0)
    minimum_reward_risk: float | None = Field(default=None, ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    structure_confirmations: list[str] = Field(default_factory=list)
    secondary_confirmations: list[str] = Field(default_factory=list)
    failed_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=100)
    risk_suggestion: RiskSuggestion
    strategy_results: list[StrategyMatch] = Field(default_factory=list)


class OpenClawEvent(StrictModel):
    event_id: str
    event_type: Literal[
        "analysis_completed",
        "near_key_level",
        "candidate_created",
        "entry_validated",
        "entry_cancelled",
        "risk_alert",
        "data_failure",
        "profile_warning",
    ]
    severity: Literal["info", "warning", "critical"]
    symbol: str
    profile: str
    horizon: Horizon | None = None
    occurred_at: datetime
    deduplication_key: str
    expires_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AnalysisReport(StrictModel):
    schema_version: Literal["3.0"] = "3.0"
    report_id: str
    symbol: str
    profile: str
    profile_confidence: Literal["dedicated", "limited"] = "dedicated"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evaluation_time: datetime
    market: dict[str, Any]
    data_availability: dict[str, DataPoint]
    scores: ScoreCard
    confidence: float = Field(ge=0, le=100)
    key_levels: dict[Literal["supports", "resistances"], list[KeyLevel]]
    relative_strength: dict[str, Any]
    horizons: dict[Horizon, HorizonPlan]
    events: list[OpenClawEvent]
    warnings: list[str]
    limitations: list[str]
    hard_filters: list[str] = Field(default_factory=list)


class EntryValidation(StrictModel):
    report_id: str
    horizon: Horizon
    status: SignalStatus
    validation_time: datetime
    actual_open_price: float | None = Field(default=None, gt=0)
    original_entry_range: PriceRange | None = None
    stop_loss: float | None = Field(default=None, gt=0)
    take_profits: list[TakeProfit] = Field(default_factory=list)
    reward_risk_at_open: float | None = Field(default=None, ge=0)
    reasons: list[str]
    event: OpenClawEvent | None = None


class BacktestTrade(StrictModel):
    symbol: str
    profile: str
    horizon: Horizon
    strategy: str
    regime: MarketRegime
    planned_at: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    return_fraction: float
    r_multiple: float
    confidence: float = Field(ge=0, le=100)
    fees: float
    holding_hours: float
    mfe: float
    mae: float
    exit_reason: str


class BacktestResult(StrictModel):
    symbol: str
    generated_at: datetime
    metrics: dict[str, Any]
    benchmarks: dict[str, Any]
    time_splits: dict[str, Any]
    rolling_windows: list[dict[str, Any]]
    trades: list[BacktestTrade]
    candidate_funnel: dict[str, int]
    blockers: dict[str, int]
    cancellations: dict[str, int]
    assumptions: dict[str, Any]
