"""Layered configuration: code < default < profile < user < CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_INSTALLED_ROOT = Path(__file__).resolve().parents[1]
ROOT = _SOURCE_ROOT if (_SOURCE_ROOT / "config").is_dir() else _INSTALLED_ROOT


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategyConfig(Section):
    support_rebound: bool = True
    breakout_retest: bool = True
    trend_pullback: bool = True
    range_reversal: bool = True
    bear_reversal: bool = False
    bear_accumulation: bool = False
    minimum_confidence: float = Field(default=58, ge=0, le=100)
    entry_confidence: float = Field(default=68, ge=0, le=100)
    minimum_reward_risk: float = Field(default=2, ge=1)
    touch_cooldown_bars: int = Field(default=6, ge=1)
    level_tolerance_atr: float = Field(default=0.35, gt=0)


class RiskConfig(Section):
    account_equity: float = Field(default=600, gt=0)
    risk_per_trade: float = Field(default=0.01, gt=0, le=0.03)
    maximum_position_fraction: float = Field(default=0.30, gt=0, le=1)
    maximum_order_notional: float = Field(default=200, gt=0)
    maximum_daily_loss: float = Field(default=0.03, gt=0, le=0.1)
    maximum_drawdown: float = Field(default=0.15, gt=0, le=0.5)


class TradingConfig(Section):
    trading_enabled: bool = False
    futures_enabled: bool = False
    require_human_confirmation: bool = True
    testnet: bool = True
    symbol_whitelist: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    api_key_env: str = "BINANCE_API_KEY"
    api_secret_env: str = "BINANCE_API_SECRET"
    maximum_price_deviation: float = Field(default=0.01, gt=0, le=0.1)
    confirmation_ttl_seconds: int = Field(default=120, ge=10, le=600)
    request_timeout_seconds: float = Field(default=10, gt=0, le=60)
    emergency_stop: bool = False

    @model_validator(mode="after")
    def enforce_safe_defaults(self) -> TradingConfig:
        if self.futures_enabled:
            raise ValueError("futures are not supported in v0.2.0")
        if self.trading_enabled and not self.require_human_confirmation:
            raise ValueError("real trading requires human confirmation")
        return self


class DataConfig(Section):
    exchange: str = "binance"
    timeframes: list[str] = Field(default_factory=lambda: ["1w", "1d", "4h", "1h"])
    history_limit: int = Field(default=500, ge=100, le=1500)
    stale_after_seconds: int = Field(default=600, gt=0)


class StorageConfig(Section):
    state_dir: str = "state"
    output_dir: str = "outputs"
    paper_account_file: str = "state/paper-account.json"
    paper_trades_file: str = "state/paper-trades.jsonl"
    journal_file: str = "state/manual-journal.jsonl"


class AppConfig(Section):
    config_version: int = 2
    profile: str = "auto"
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
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
    data = AppConfig().model_dump()
    data = deep_merge(data, _yaml(ROOT / "config" / "default.yaml"))
    data = deep_merge(data, _yaml(ROOT / "config" / "profiles" / f"{profile}.yaml"))
    if user_path:
        data = deep_merge(data, _yaml(Path(user_path).expanduser()))
    data = deep_merge(data, cli_overrides or {})
    return AppConfig.model_validate(data)
