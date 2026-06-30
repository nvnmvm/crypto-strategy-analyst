"""Typed models shared across analysis, risk, and reporting."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Trend(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"


class SignalLabel(StrEnum):
    STRONG_BUY_CANDIDATE = "strong_buy_candidate"
    BUY_CANDIDATE = "buy_candidate"
    WATCH = "watch"
    NO_TRADE = "no_trade"


class QualityGrade(StrEnum):
    VALID = "valid"
    DEGRADED = "degraded"
    INVALID = "invalid"


class DataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade: QualityGrade
    bars: int = Field(ge=0)
    expected_interval: str
    duplicate_count: int = Field(ge=0)
    gap_count: int = Field(ge=0)
    missing_intervals: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class PriceZone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lower_price: float = Field(gt=0)
    upper_price: float = Field(gt=0)
    center_price: float = Field(gt=0)
    level_type: Literal["support", "resistance"]
    timeframe: str
    touch_count: int = Field(ge=1)
    reaction_count: int = Field(default=0, ge=0)
    break_count: int = Field(default=0, ge=0)
    last_touch_time: datetime
    strength_score: float = Field(ge=0, le=100)
    evidence: list[str]

    @field_validator("upper_price")
    @classmethod
    def validate_upper(cls, value: float, info: Any) -> float:
        lower = info.data.get("lower_price")
        if lower is not None and value < lower:
            raise ValueError("upper_price must be >= lower_price")
        return value


class IndicatorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    close: float
    ema20: float
    ema50: float
    ema200: float
    rsi14: float
    macd: float
    macd_signal: float
    macd_histogram: float
    atr14: float
    adx14: float | Literal["not_available"]
    volume_ratio: float


class ScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    higher_timeframe_trend: float = Field(ge=0, le=20)
    support_resistance: float = Field(ge=0, le=25)
    candlestick_confirmation: float = Field(ge=0, le=15)
    volume_confirmation: float = Field(ge=0, le=15)
    indicator_confirmation: float = Field(ge=0, le=15)
    reward_risk_space: float = Field(ge=0, le=10)
    sentiment_adjustment: float = Field(default=0, ge=-5, le=5)

    @property
    def total(self) -> float:
        values = self.model_dump().values()
        return round(max(0.0, min(100.0, sum(float(v) for v in values))), 2)


class PositionSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: float = Field(ge=0)
    position_notional_cny: float = Field(ge=0)
    risk_amount_cny: float = Field(ge=0)
    position_fraction: float = Field(ge=0, le=1)
    quote_to_account_rate: float = Field(gt=0)


class AnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    generated_at: datetime
    symbol: str
    market: Literal["binance_spot"] = "binance_spot"
    data_source: str
    analysis_timeframes: list[str]
    current_price: float = Field(gt=0)
    data_quality: dict[str, DataQuality]
    daily_trend: Trend
    four_hour_trend: Trend
    one_hour_confirmation: str
    support_zones: list[PriceZone]
    resistance_zones: list[PriceZone]
    indicators: dict[str, IndicatorSnapshot]
    signal: SignalLabel
    signal_score: float = Field(ge=0, le=100)
    score_breakdown: ScoreBreakdown
    entry_zone: PriceZone | Literal["not_available"]
    stop_loss: float | Literal["not_available"]
    take_profit_1: float | Literal["not_available"]
    take_profit_2: float | Literal["not_available"]
    trailing_stop_method: str
    risk_reward_ratio: float | Literal["not_available"]
    suggested_position_size: PositionSuggestion | Literal["not_available"]
    maximum_loss_amount: float | Literal["not_available"]
    reasons: list[str]
    invalidation_conditions: list[str]
    missing_data: dict[str, Literal["not_available"]]
    warnings: list[str]
    disclaimer: str = "策略研究结果，不是收益保证，也不是投资建议。"


class TradeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    return_pct: float
    fees: float
    slippage_cost: float
    holding_hours: float
    exit_reason: str
    market_regime: Trend


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_return: float
    annualized_return: float
    max_drawdown: float
    win_rate: float
    payoff_ratio: float
    profit_factor: float
    sharpe_ratio: float
    sortino_ratio: float
    trade_count: int
    average_holding_hours: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    total_fees: float
    slippage_cost: float
    buy_and_hold_return: float


class BacktestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    generated_at: datetime
    symbol: str
    interval: str
    start_time: datetime
    end_time: datetime
    initial_capital_cny: float
    final_equity_cny: float
    config: dict[str, Any]
    metrics: BacktestMetrics
    time_splits: dict[str, dict[str, Any]]
    yearly_results: dict[str, float]
    market_phase_results: dict[str, float]
    trades: list[TradeRecord]
    warnings: list[str]
    disclaimer: str = "历史回测不代表未来收益；结果仅用于策略研究。"
