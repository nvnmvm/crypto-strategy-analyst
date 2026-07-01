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


class MarketRegime(StrEnum):
    BULL_TREND = "bull_trend"
    BULL_PULLBACK = "bull_pullback"
    SIDEWAYS_RANGE = "sideways_range"
    BEAR_TREND = "bear_trend"
    BEAR_CAPITULATION = "bear_capitulation"
    BEAR_RECOVERY = "bear_recovery"


class StrategyHorizon(StrEnum):
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class SignalLabel(StrEnum):
    STRONG_BUY_CANDIDATE = "strong_buy_candidate"
    BUY_CANDIDATE = "buy_candidate"
    WATCH = "watch"
    NO_TRADE = "no_trade"


class QualityGrade(StrEnum):
    VALID = "valid"
    DEGRADED = "degraded"
    INVALID = "invalid"


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    INVALID = "invalid"


class DataFreshnessItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FreshnessStatus
    expected_latest_close: datetime
    actual_latest_close: datetime | None
    staleness_seconds: float = Field(ge=0)
    reason: str | None = None


class SymbolTradingRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    price_tick_size: float = Field(gt=0)
    quantity_step_size: float = Field(gt=0)
    minimum_quantity: float = Field(ge=0)
    maximum_quantity: float | None = Field(default=None, gt=0)
    minimum_notional: float = Field(ge=0)
    fetched_at: datetime
    data_source: str


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
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    minimum_notional: float = Field(ge=0)
    quantity_step_size: float = Field(gt=0)


class AnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.3.0"
    generated_at: datetime
    requested_at: datetime
    evaluation_time: datetime
    evaluation_timeframe: Literal["4h"] = "4h"
    time_alignment_applied: bool
    latest_completed_candle_close: dict[str, datetime]
    data_freshness: dict[str, DataFreshnessItem]
    freshness_retry_attempts: int = Field(ge=0)
    symbol: str
    market: Literal["binance_spot"] = "binance_spot"
    data_source: str
    analysis_timeframes: list[str]
    current_price: float = Field(gt=0)
    account_currency: Literal["CNY", "USDT"] = "CNY"
    account_equity_cny: float = Field(ge=0)
    risk_locks: list[str]
    trading_rules: SymbolTradingRules | Literal["not_available"]
    trading_rules_status: Literal[
        "available", "exchange_rules_unavailable", "exchange_rules_stale_cache"
    ]
    data_quality: dict[str, DataQuality]
    daily_trend: Trend
    four_hour_trend: Trend
    one_hour_trend: Trend
    market_regime: MarketRegime
    regime_evidence: list[str]
    selected_strategy: str
    strategy_horizon: StrategyHorizon
    entry_setup: str
    candidate_tier: Literal["A", "B", "none"]
    risk_multiplier: float = Field(ge=0, le=1)
    confirmation_score: float = Field(ge=0)
    strong_confirmation_count: int = Field(ge=0)
    one_hour_confirmation: str
    support_zones: list[PriceZone]
    resistance_zones: list[PriceZone]
    indicators: dict[str, IndicatorSnapshot]
    signal: SignalLabel
    signal_score: float = Field(ge=0, le=100)
    score_breakdown: ScoreBreakdown
    support_zone: PriceZone | Literal["not_available"] = "not_available"
    allowed_entry_range: PriceZone | Literal["not_available"] = "not_available"
    planned_entry_price: float | Literal["not_available"] = "not_available"
    entry_zone: PriceZone | Literal["not_available"]
    stop_loss: float | Literal["not_available"]
    take_profit_1: float | Literal["not_available"]
    take_profit_2: float | Literal["not_available"]
    target_sources: list[str]
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
    market_regime_detail: MarketRegime | None = None
    strategy_id: str = "trend_pullback"
    strategy_horizon: StrategyHorizon = StrategyHorizon.MEDIUM_TERM
    entry_setup: str = "support_rebound"
    candidate_tier: Literal["A", "B", "none"] = "none"
    initial_risk_cny: float = Field(ge=0)
    realized_r_multiple: float


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
    expectancy: float
    exposure_percent: float = Field(ge=0, le=100)
    average_capital_utilization: float = Field(ge=0, le=1)
    generated_signal_count: int = Field(ge=0)
    executed_trade_count: int = Field(ge=0)
    cancelled_signal_count: int = Field(ge=0)
    no_trade_count: int = Field(ge=0)
    average_initial_risk_cny: float = Field(ge=0)
    average_realized_r_multiple: float
    median_realized_r_multiple: float
    annualized_volatility: float = Field(ge=0)
    longest_drawdown_recovery_days: float = Field(ge=0)
    best_trade_pnl: float
    worst_trade_pnl: float
    best_trade_profit_contribution: float
    best_year_profit_contribution: float
    return_without_best_trade: float
    return_without_best_year: float


class CostScenarioMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_return: float
    max_drawdown: float
    profit_factor: float
    trade_count: int = Field(ge=0)


class BenchmarkMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_return: float
    annualized_return: float
    max_drawdown: float
    annualized_volatility: float = Field(ge=0)
    exposure_percent: float = Field(ge=0, le=100)
    longest_drawdown_recovery_days: float = Field(ge=0)
    total_fees: float = Field(ge=0)
    transaction_count: int = Field(ge=0)


class ResearchProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_version: str
    parameter_set_id: str
    parameter_search_performed: Literal[False] = False
    number_of_parameter_sets_evaluated: int = Field(default=1, ge=1)
    selection_rule: Literal["predefined"] = "predefined"


class BacktestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.3.0"
    generated_at: datetime
    package_version: str
    strategy_config_hash: str
    dataset_hash: str
    random_seed: int
    symbol: str
    interval: str
    start_time: datetime
    end_time: datetime
    initial_capital_cny: float
    final_equity_cny: float
    account_currency: Literal["CNY", "USDT"] = "CNY"
    config: dict[str, Any]
    research_protocol: ResearchProtocol
    metrics: BacktestMetrics
    chronological_holdout_split: dict[str, dict[str, Any]]
    rolling_window_results: list[dict[str, Any]]
    yearly_results: dict[str, float]
    market_phase_results: dict[str, float]
    market_regime_results: dict[str, float]
    strategy_results: dict[str, float]
    benchmarks: dict[str, BenchmarkMetrics]
    generated_signal_count: int = Field(ge=0)
    executed_entry_count: int = Field(ge=0)
    cancelled_entry_count: int = Field(ge=0)
    cancelled_entry_reasons: dict[str, int]
    signal_label_counts: dict[str, int]
    decision_blocker_counts: dict[str, int]
    decision_blocker_counts_by_regime: dict[str, dict[str, int]]
    cost_sensitivity: dict[str, CostScenarioMetrics]
    insufficient_sample_warning: str | None
    trades: list[TradeRecord]
    warnings: list[str]
    disclaimer: str = "历史回测不代表未来收益；结果仅用于策略研究。"

    @property
    def time_splits(self) -> dict[str, dict[str, Any]]:
        """Deprecated attribute alias; serialized output uses the truthful name."""

        return self.chronological_holdout_split
