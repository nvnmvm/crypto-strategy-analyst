"""Conservative multi-timeframe replay using the public strategy engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import AppConfig
from .engine import evaluate_setup_at_time
from .models import Availability, DataPoint, Horizon, MarketSnapshot, SignalStatus


@dataclass
class BacktestResult:
    symbol: str
    start_equity: float
    end_equity: float
    total_return: float
    max_drawdown: float
    trades: int
    time_splits: dict[str, dict[str, float | int]]

    def as_dict(self) -> dict[str, object]:
        return self.__dict__


def snapshot_at(snapshot: MarketSnapshot, at: datetime) -> MarketSnapshot:
    """Construct a replay view containing only data closed by `at`."""
    candles = {
        frame: [bar for bar in bars if bar.close_time <= at]
        for frame, bars in snapshot.candles.items()
    }
    decision_bars = candles.get("4h", [])
    price = decision_bars[-1].close if decision_bars else snapshot.price
    volume_bars = candles.get("1h", []) or decision_bars
    volume = DataPoint(
        status=Availability.AVAILABLE if volume_bars else Availability.NOT_AVAILABLE,
        source="historical_candle",
        observed_at=at,
        freshness_seconds=0,
        value=volume_bars[-1].volume if volume_bars else None,
    )
    timestamp = DataPoint(
        status=Availability.AVAILABLE,
        source="replay_clock",
        observed_at=at,
        freshness_seconds=0,
        value=at.isoformat(),
    )
    auxiliary = {
        name: (
            point
            if point.observed_at is None or point.observed_at <= at
            else point.model_copy(
                update={
                    "status": Availability.NOT_AVAILABLE,
                    "value": None,
                    "detail": "not yet observed at replay time",
                }
            )
        )
        for name, point in snapshot.auxiliary.items()
    }
    rules = snapshot.trading_rules.model_copy(update={"observed_at": at})
    return snapshot.model_copy(
        update={
            "as_of": at,
            "price": price,
            "candles": candles,
            "volume": volume,
            "timestamp": timestamp,
            "trading_rules": rules,
            "auxiliary": auxiliary,
        }
    )


def replay_signal(snapshot: MarketSnapshot, at: datetime, config: AppConfig, profile: str = "auto"):
    return evaluate_setup_at_time(snapshot_at(snapshot, at), config, profile)


def run_backtest(
    snapshot: MarketSnapshot,
    config: AppConfig,
    profile: str = "auto",
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0005,
) -> BacktestResult:
    timeline = [bar.close_time for bar in snapshot.candles.get("4h", [])]
    equity = config.risk.account_equity
    peak = equity
    max_drawdown = 0.0
    trades = 0
    position: tuple[float, float, float, float] | None = None
    returns: list[float] = []
    for at in timeline:
        view = snapshot_at(snapshot, at)
        report = evaluate_setup_at_time(view, config, profile)
        plan = report.plans[Horizon.SWING]
        price = view.price
        if position:
            entry, stop, target, quantity = position
            if price <= stop or price >= target or plan.status == SignalStatus.EXIT_SIGNAL:
                exit_price = price * (1 - slippage_rate)
                pnl = (exit_price - entry) * quantity - (exit_price + entry) * quantity * fee_rate
                equity += pnl
                returns.append(pnl)
                trades += 1
                position = None
                peak = max(peak, equity)
                max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0)
        elif (
            plan.status == SignalStatus.CANDIDATE
            and plan.entry
            and plan.stop
            and plan.take_profit_1
        ):
            entry = plan.entry * (1 + slippage_rate)
            notional = min(equity * plan.position_fraction, config.risk.maximum_order_notional)
            position = (entry, plan.stop, plan.take_profit_1, notional / entry)
    sections: dict[str, dict[str, float | int]] = {}
    cut1 = int(len(returns) * 0.6)
    cut2 = int(len(returns) * 0.8)
    for name, values in {
        "train": returns[:cut1],
        "validation": returns[cut1:cut2],
        "test": returns[cut2:],
    }.items():
        sections[name] = {"trades": len(values), "realized_pnl": round(sum(values), 8)}
    return BacktestResult(
        symbol=snapshot.symbol,
        start_equity=config.risk.account_equity,
        end_equity=round(equity, 8),
        total_return=round(equity / config.risk.account_equity - 1, 8),
        max_drawdown=round(max_drawdown, 8),
        trades=trades,
        time_splits=sections,
    )
