"""Configuration loading with hard risk bounds."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

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
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    max_retries: int = Field(default=3, ge=1, le=5)


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_equity_cny: float = Field(default=1000.0, gt=0)
    cny_per_usdt: float = Field(default=7.2, gt=0)
    risk_per_trade: float = Field(default=0.01, gt=0, le=0.03)
    max_risk_per_trade: float = Field(default=0.03, gt=0, le=0.03)
    daily_stop_count: int = Field(default=2, ge=1)
    daily_max_loss: float = Field(default=0.02, gt=0, le=0.1)
    max_drawdown: float = Field(default=0.10, gt=0, le=0.5)
    max_position_fraction: float = Field(default=1.0, gt=0, le=1)
    min_reward_risk: float = Field(default=2.0, ge=2.0)
    trailing_stop_method: Literal["atr", "previous_swing_low"] = "atr"
    trailing_atr_multiple: float = Field(default=2.0, ge=0.5, le=5)

    @model_validator(mode="after")
    def enforce_risk_ceiling(self) -> RiskConfig:
        if self.risk_per_trade > self.max_risk_per_trade:
            raise ValueError("risk_per_trade cannot exceed max_risk_per_trade")
        return self


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    swing_left: int = Field(default=3, ge=1, le=10)
    swing_right: int = Field(default=3, ge=1, le=10)
    level_merge_percent: float = Field(default=0.006, gt=0, le=0.03)
    support_proximity_atr: float = Field(default=1.0, gt=0, le=3)
    volume_ratio_threshold: float = Field(default=1.2, ge=1)
    min_confirmations: int = Field(default=2, ge=2, le=7)
    enable_adx: bool = True
    random_seed: int = 42


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval: Literal["4h"] = "4h"
    fee_rate: float = Field(default=0.001, ge=0, le=0.02)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.02)
    warmup_bars: int = Field(default=220, ge=210)
    train_ratio: float = Field(default=0.6, gt=0)
    validation_ratio: float = Field(default=0.2, gt=0)
    test_ratio: float = Field(default=0.2, gt=0)

    @model_validator(mode="after")
    def validate_split(self) -> BacktestConfig:
        total = self.train_ratio + self.validation_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-9:
            raise ValueError("walk-forward ratios must sum to 1")
        return self


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: str = "outputs"
    log_dir: str = "logs"


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
