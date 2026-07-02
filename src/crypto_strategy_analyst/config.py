"""Strict layered analysis configuration."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_INSTALLED_ROOT = Path(__file__).resolve().parents[1]
ROOT = _SOURCE_ROOT if (_SOURCE_ROOT / "config").is_dir() else _INSTALLED_ROOT


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndicatorConfig(Section):
    ema_fast: int = Field(default=20, ge=2)
    ema_medium: int = Field(default=50, ge=5)
    ema_slow: int = Field(default=200, ge=20)
    atr_period: int = Field(default=14, ge=2)
    rsi_period: int = Field(default=14, ge=2)
    volume_period: int = Field(default=20, ge=2)


class LevelConfig(Section):
    swing_window: int = Field(default=3, ge=2, le=10)
    merge_atr: float = Field(default=0.45, gt=0, le=2)
    zone_atr: float = Field(default=0.18, gt=0, le=1)
    touch_cooldown_bars: int = Field(default=6, ge=1)
    reaction_atr: float = Field(default=0.5, gt=0)
    break_atr: float = Field(default=0.3, gt=0)
    near_percent: float = Field(default=0.012, gt=0, le=0.1)
    near_atr: float = Field(default=0.8, gt=0, le=5)


class StrategyConfig(Section):
    support_rebound: bool = True
    breakout_retest: bool = True
    trend_pullback: bool = True
    range_reversal: bool = True
    bear_reversal: bool = True
    bear_accumulation: bool = False
    minimum_confidence: float = Field(default=52, ge=0, le=100)
    candidate_confidence: float = Field(default=65, ge=0, le=100)
    volume_ratio: float = Field(default=1.15, ge=0.5)
    breakout_atr: float = Field(default=0.3, gt=0)
    pullback_minimum: float = Field(default=0.03, gt=0, le=0.5)
    bear_drawdown: float = Field(default=0.22, gt=0, le=0.8)
    entry_deviation_atr: float = Field(default=0.25, gt=0, le=1)
    stop_buffer_atr: float = Field(default=0.25, gt=0, le=2)
    validity_bars: int = Field(default=2, ge=1, le=10)


class HorizonConfig(Section):
    short_minimum_r: float = Field(default=1.5, ge=1)
    swing_minimum_r: float = Field(default=1.8, ge=1)
    long_minimum_r: float = Field(default=2.0, ge=1)
    short_risk: float = Field(default=0.005, ge=0, le=0.03)
    swing_risk: float = Field(default=0.008, ge=0, le=0.03)
    long_risk: float = Field(default=0.006, ge=0, le=0.03)


class DataConfig(Section):
    exchange: str = "binance"
    timeframes: list[str] = Field(default_factory=lambda: ["1w", "1d", "4h", "1h"])
    history_limit: int = Field(default=500, ge=100, le=1500)
    stale_after_seconds: int = Field(default=900, gt=0)
    request_timeout_seconds: float = Field(default=15, gt=0, le=60)


class ResearchConfig(Section):
    train_end: date = date(2021, 12, 31)
    validation_end: date = date(2023, 12, 31)
    historical_replay_end: date = date(2026, 7, 1)
    fee_rate: float = Field(default=0.001, ge=0, le=0.02)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.02)
    starting_equity: float = Field(default=600, gt=0)
    minimum_trades: int = Field(default=30, ge=1)
    time_exit_bars: int = Field(default=30, ge=1)
    rolling_days: int = Field(default=365, ge=30)
    move_stop_to_breakeven_after_tp1: bool = True


class OutputConfig(Section):
    output_dir: str = "outputs"


class AppConfig(Section):
    config_version: int = 3
    profile: str = "auto"
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    levels: LevelConfig = Field(default_factory=LevelConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    horizons: HorizonConfig = Field(default_factory=HorizonConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        merged[key] = (
            deep_merge(merged[key], value)
            if isinstance(value, dict) and isinstance(merged.get(key), dict)
            else value
        )
    return merged


def _yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"configuration root must be a mapping: {path}")
    return value


def load_config(
    user_path: str | Path | None = None,
    profile: str = "generic",
    cli_overrides: dict[str, Any] | None = None,
) -> AppConfig:
    data = deep_merge(AppConfig().model_dump(), _yaml(ROOT / "config" / "default.yaml"))
    data = deep_merge(data, _yaml(ROOT / "config" / "profiles" / f"{profile}.yaml"))
    if user_path:
        data = deep_merge(data, _yaml(Path(user_path).expanduser()))
    return AppConfig.model_validate(deep_merge(data, cli_overrides or {}))
