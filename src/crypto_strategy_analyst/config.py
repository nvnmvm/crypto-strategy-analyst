"""Configuration loading with hard risk bounds."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import ConfigurationError


class MarketConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange: Literal["binance"] = "binance"
    market_type: Literal["spot"] = "spot"
    symbols: list[str] = ["BTC/USDT", "ETH/USDT"]
    timeframes: list[str] = ["1d", "4h", "1h"]
    history_limit: int = Field(default=500, ge=250, le=1000)
    request_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    request_read_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    request_max_total_seconds: float = Field(default=45.0, gt=0, le=120)
    max_retries: int = Field(default=3, ge=1, le=5)
    retry_backoff_base_seconds: float = Field(default=0.5, ge=0, le=10)
    circuit_failure_threshold: int = Field(default=3, ge=1, le=10)
    circuit_cooldown_seconds: float = Field(default=60.0, gt=0, le=600)
    freshness_retry_count: int = Field(default=3, ge=0, le=10)
    freshness_retry_delay_seconds: float = Field(default=20.0, ge=0, le=120)
    freshness_grace_seconds: float = Field(default=90.0, ge=0, le=600)


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_currency: Literal["CNY", "USDT"] = "CNY"
    account_equity_cny: float = Field(default=1000.0, gt=0)
    cny_per_usdt: float = Field(default=7.2, gt=0)
    risk_per_trade: float = Field(default=0.01, gt=0, le=0.03)
    max_risk_per_trade: float = Field(default=0.03, gt=0, le=0.03)
    daily_stop_count: int = Field(default=2, ge=1)
    daily_max_loss: float = Field(default=0.02, gt=0, le=0.1)
    max_drawdown: float = Field(default=0.10, gt=0, le=0.5)
    max_position_fraction: float = Field(default=1.0, gt=0, le=1)
    aggregate_open_risk_limit: float = Field(default=0.02, gt=0, le=0.03)
    max_symbol_deployed_fraction: float = Field(default=0.60, gt=0, le=1)
    max_total_deployed_fraction: float = Field(default=1.0, gt=0, le=1)
    reserved_cash_fraction: float = Field(default=0.0, ge=0, lt=1)
    min_reward_risk: float = Field(default=2.0, ge=2.0)
    trailing_stop_method: Literal["atr", "previous_swing_low"] = "atr"
    trailing_atr_multiple: float = Field(default=2.0, ge=0.5, le=5)

    @model_validator(mode="after")
    def enforce_risk_ceiling(self) -> RiskConfig:
        if self.risk_per_trade > self.max_risk_per_trade:
            raise ValueError("risk_per_trade cannot exceed max_risk_per_trade")
        if self.account_currency == "USDT" and self.cny_per_usdt != 1.0:
            raise ValueError("USDT account research requires cny_per_usdt=1.0")
        return self


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_variant: Literal[
        "baseline_v0_1_2",
        "relaxed_trend",
        "relaxed_trend_plus_breakout",
        "relaxed_trend_plus_bear_reversal",
    ] = "baseline_v0_1_2"
    strong_buy_score: float = Field(default=75.0, ge=60, le=90)
    buy_score: float = Field(default=60.0, ge=50, le=80)
    watch_score: float = Field(default=45.0, ge=30, le=60)
    b_tier_min_reward_risk: float = Field(default=1.6, ge=1.5, le=2.0)
    execution_reward_risk_cushion: float = Field(default=0.2, ge=0.05, le=0.5)
    b_tier_risk_multiplier: float = Field(default=0.5, gt=0, le=0.5)
    sideways_risk_multiplier: float = Field(default=0.5, gt=0, le=1)
    bear_first_risk_multiplier: float = Field(default=0.25, ge=0.25, le=0.5)
    bear_drawdown_threshold: float = Field(default=0.25, ge=0.20, le=0.50)
    bear_max_deployed_fraction: float = Field(default=0.20, ge=0.15, le=0.25)
    maximum_bear_entries: Literal[2] = 2
    short_term_max_holding_days: int = Field(default=14, ge=2, le=30)
    medium_term_max_holding_days: int = Field(default=90, ge=14, le=180)
    long_term_max_holding_days: int = Field(default=180, ge=60, le=365)
    swing_left: int = Field(default=3, ge=1, le=10)
    swing_right: int = Field(default=3, ge=1, le=10)
    level_merge_percent: float = Field(default=0.006, gt=0, le=0.03)
    support_proximity_atr: float = Field(default=1.0, gt=0, le=3)
    entry_zone_depth_atr: float = Field(default=0.25, ge=0, le=1)
    entry_zone_chase_atr: float = Field(default=0.15, ge=0, le=1)
    stop_buffer_atr: float = Field(default=0.50, gt=0, le=2)
    volume_ratio_threshold: float = Field(default=1.2, ge=1)
    min_confirmations: int = Field(default=2, ge=2, le=7)
    touch_cooldown_bars: int = Field(default=6, ge=1, le=50)
    reaction_atr_multiple: float = Field(default=0.75, gt=0, le=5)
    break_atr_multiple: float = Field(default=0.25, gt=0, le=2)
    target_resistance_buffer_atr: float = Field(default=0.15, ge=0, le=1)
    min_second_target_r_multiple: float = Field(default=2.5, ge=2.1, le=4)
    max_entry_gap_atr: float = Field(default=0.5, gt=0, le=3)
    pending_signal_valid_bars: int = Field(default=1, ge=1, le=6)
    enable_adx: bool = True
    random_seed: int = 42


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval: Literal["4h"] = "4h"
    fee_rate: float = Field(default=0.001, ge=0, le=0.02)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.02)
    split_mode: Literal["calendar", "ratio"] = "calendar"
    train_end_date: str = "2021-12-31"
    validation_end_date: str = "2023-12-31"
    train_ratio: float = Field(default=0.6, gt=0)
    validation_ratio: float = Field(default=0.2, gt=0)
    test_ratio: float = Field(default=0.2, gt=0)
    minimum_sample_trades: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def validate_split(self) -> BacktestConfig:
        total = self.train_ratio + self.validation_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-9:
            raise ValueError("time split ratios must sum to 1")
        train_end = pd.Timestamp(self.train_end_date)
        validation_end = pd.Timestamp(self.validation_end_date)
        if train_end >= validation_end:
            raise ValueError("train_end_date must precede validation_end_date")
        return self


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: str = "outputs"
    log_dir: str = "logs"
    risk_state_file: str = "state/risk-state.json"
    risk_events_file: str = "state/risk-events.jsonl"
    account_state_file: str = "state/account-state.json"
    account_events_file: str = "state/account-events.jsonl"


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_version: Literal[1] = 1
    market: MarketConfig = MarketConfig()
    risk: RiskConfig = RiskConfig()
    strategy: StrategyConfig = StrategyConfig()
    backtest: BacktestConfig = BacktestConfig()
    output: OutputConfig = OutputConfig()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load defaults and optionally merge a YAML override."""

    defaults = AppConfig().model_dump()
    if path is None:
        return AppConfig.model_validate(defaults)
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigurationError(f"configuration file not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ConfigurationError("configuration root must be a mapping")
        return AppConfig.model_validate(_deep_merge(defaults, raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise ConfigurationError(f"invalid configuration: {exc}") from exc
