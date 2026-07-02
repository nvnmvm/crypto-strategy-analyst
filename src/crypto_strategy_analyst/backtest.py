"""Strict next-bar-open OHLC replay using the public analysis engine."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

import numpy as np

from .config import AppConfig
from .engine import evaluate_setup_at_time
from .models import (
    Availability,
    BacktestResult,
    BacktestTrade,
    Horizon,
    MarketSnapshot,
    SignalStatus,
)
from .validation import PRIMARY, validate_entry


def snapshot_at(snapshot: MarketSnapshot, at: datetime) -> MarketSnapshot:
    candles = {
        frame: [bar for bar in bars if bar.close_time <= at]
        for frame, bars in snapshot.candles.items()
    }
    decision = candles.get("4h", []) or candles.get("1d", [])
    auxiliary = {
        name: point
        if point.observed_at is None or point.observed_at <= at
        else point.model_copy(
            update={
                "status": Availability.NOT_AVAILABLE,
                "value": None,
                "detail": "future_at_replay_time",
            }
        )
        for name, point in snapshot.auxiliary.items()
    }
    rules = snapshot.trading_rules.model_copy(update={"observed_at": at})
    return snapshot.model_copy(
        update={
            "as_of": at,
            "price": decision[-1].close if decision else snapshot.price,
            "candles": candles,
            "auxiliary": auxiliary,
            "trading_rules": rules,
        }
    )


def replay_signal(snapshot: MarketSnapshot, at: datetime, config: AppConfig, profile: str = "auto"):
    return evaluate_setup_at_time(snapshot_at(snapshot, at), config, profile)


def _validation_snapshot(snapshot: MarketSnapshot, at: datetime) -> MarketSnapshot:
    values = snapshot_at(snapshot, at)
    return values.model_copy(update={"as_of": at, "candles": snapshot.candles})


def _simulate_trade(
    bars,
    start_index: int,
    plan,
    symbol: str,
    equity: float,
    config: AppConfig,
    profile_name: str = "unknown",
) -> BacktestTrade:
    entry_bar = bars[start_index]
    entry = entry_bar.open * (1 + config.research.slippage_rate)
    stop = plan.stop_loss
    initial_risk = entry - stop
    risk_budget = equity * plan.risk_suggestion.risk_fraction
    quantity = min(risk_budget / max(initial_risk, 1e-12), equity / entry)
    remaining = quantity
    realized = -entry * quantity * config.research.fee_rate
    fees = entry * quantity * config.research.fee_rate
    weighted_exit = 0.0
    exited = 0.0
    current_stop = stop
    reason = "end_of_data"
    exit_time = bars[-1].close_time
    mfe = 0.0
    mae = 0.0
    targets = list(plan.take_profits)
    for offset, bar in enumerate(bars[start_index : start_index + config.research.time_exit_bars]):
        mfe = max(mfe, (bar.high - entry) / initial_risk)
        mae = min(mae, (bar.low - entry) / initial_risk)
        if bar.low <= current_stop and any(bar.high >= target.price for target in targets):
            exit_price = current_stop * (1 - config.research.slippage_rate)
            realized += (exit_price - entry) * remaining
            fee = exit_price * remaining * config.research.fee_rate
            realized -= fee
            fees += fee
            weighted_exit += exit_price * remaining
            exited += remaining
            remaining = 0
            reason = "stop_first_same_bar"
        elif bar.low <= current_stop:
            exit_price = current_stop * (1 - config.research.slippage_rate)
            realized += (exit_price - entry) * remaining
            fee = exit_price * remaining * config.research.fee_rate
            realized -= fee
            fees += fee
            weighted_exit += exit_price * remaining
            exited += remaining
            remaining = 0
            reason = "stop_loss"
        else:
            for index, target in enumerate(targets):
                if remaining and bar.high >= target.price:
                    fraction_quantity = min(remaining, quantity * target.fraction)
                    exit_price = target.price * (1 - config.research.slippage_rate)
                    realized += (exit_price - entry) * fraction_quantity
                    fee = exit_price * fraction_quantity * config.research.fee_rate
                    realized -= fee
                    fees += fee
                    weighted_exit += exit_price * fraction_quantity
                    exited += fraction_quantity
                    remaining -= fraction_quantity
                    if index == 0 and config.research.move_stop_to_breakeven_after_tp1:
                        current_stop = max(current_stop, entry)
                    reason = f"take_profit_{index + 1}"
        exit_time = bar.close_time
        if remaining <= 1e-12:
            break
        if offset + 1 >= config.research.time_exit_bars:
            reason = "time_exit"
            exit_price = bar.close * (1 - config.research.slippage_rate)
            realized += (exit_price - entry) * remaining
            fee = exit_price * remaining * config.research.fee_rate
            realized -= fee
            fees += fee
            weighted_exit += exit_price * remaining
            exited += remaining
            remaining = 0
    if remaining:
        exit_price = bars[-1].close * (1 - config.research.slippage_rate)
        realized += (exit_price - entry) * remaining
        fee = exit_price * remaining * config.research.fee_rate
        realized -= fee
        fees += fee
        weighted_exit += exit_price * remaining
        exited += remaining
    average_exit = weighted_exit / max(exited, 1e-12)
    return BacktestTrade(
        symbol=symbol,
        profile=profile_name,
        horizon=plan.horizon,
        strategy=plan.strategy,
        regime=plan.market_regime,
        planned_at=plan.valid_from,
        entry_time=entry_bar.open_time,
        exit_time=exit_time,
        entry_price=entry,
        exit_price=average_exit,
        quantity=quantity,
        pnl=realized,
        return_fraction=realized / equity,
        r_multiple=realized / max(risk_budget, 1e-12),
        confidence=plan.confidence,
        fees=fees,
        holding_hours=(exit_time - entry_bar.open_time).total_seconds() / 3600,
        mfe=mfe,
        mae=mae,
        exit_reason=reason,
    )


def _metrics(trades: list[BacktestTrade], start: float, minimum: int) -> dict[str, object]:
    pnls = np.array([trade.pnl for trade in trades], dtype=float)
    returns = np.array([trade.return_fraction for trade in trades], dtype=float)
    equity = start + np.cumsum(pnls)
    peaks = np.maximum.accumulate(np.insert(equity, 0, start))[1:] if len(equity) else np.array([])
    drawdowns = (peaks - equity) / peaks if len(equity) else np.array([])
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    downside = returns[returns < 0]
    sharpe = (
        float(np.mean(returns) / np.std(returns) * np.sqrt(252))
        if len(returns) > 1 and np.std(returns)
        else 0
    )
    sortino = (
        float(np.mean(returns) / np.std(downside) * np.sqrt(252))
        if len(downside) > 1 and np.std(downside)
        else 0
    )
    total_return = float(pnls.sum() / start) if start else 0
    years = (
        max(1 / 365, (trades[-1].exit_time - trades[0].entry_time).days / 365.25) if trades else 1
    )
    annualized = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1
    max_drawdown = float(drawdowns.max()) if len(drawdowns) else 0
    gross_profit = float(wins.sum()) if len(wins) else 0
    gross_loss = abs(float(losses.sum())) if len(losses) else 0
    return {
        "total_return": total_return,
        "annualized_return": annualized,
        "max_drawdown": max_drawdown,
        "trade_count": len(trades),
        "win_rate": float(len(wins) / len(trades)) if trades else 0,
        "average_win": float(wins.mean()) if len(wins) else 0,
        "average_loss": float(losses.mean()) if len(losses) else 0,
        "payoff_ratio": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else 0,
        "expectancy_r": float(np.mean([trade.r_multiple for trade in trades])) if trades else 0,
        "profit_factor": gross_profit / gross_loss
        if gross_loss
        else (float("inf") if gross_profit else 0),
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": annualized / max_drawdown if max_drawdown else 0,
        "fee_fraction": sum(trade.fees for trade in trades) / start,
        "average_holding_hours": float(np.mean([trade.holding_hours for trade in trades]))
        if trades
        else 0,
        "average_mfe_r": float(np.mean([trade.mfe for trade in trades])) if trades else 0,
        "average_mae_r": float(np.mean([trade.mae for trade in trades])) if trades else 0,
        "maximum_single_trade_contribution": max((trade.pnl for trade in trades), default=0)
        / max(abs(pnls.sum()), start),
        "strategy_concentration": _concentration([trade.strategy for trade in trades]),
        "symbol_concentration": _concentration([trade.symbol for trade in trades]),
        "sample_size_status": "sufficient"
        if len(trades) >= minimum
        else "sample_size_insufficient",
    }


def _concentration(values: list[str]) -> float:
    counts = Counter(values)
    total = sum(counts.values())
    return sum((count / total) ** 2 for count in counts.values()) if total else 0


def _time_splits(trades: list[BacktestTrade], config: AppConfig) -> dict[str, object]:
    train = config.research.train_end
    validation = config.research.validation_end
    replay_end = config.research.historical_replay_end
    buckets = {"train": [], "validation": [], "historical_replay": [], "post_freeze_forward": []}
    for trade in trades:
        date = trade.entry_time.date()
        key = (
            "train"
            if date <= train
            else "validation"
            if date <= validation
            else "historical_replay"
            if date <= replay_end
            else "post_freeze_forward"
        )
        buckets[key].append(trade)
    return {
        name: {"trade_count": len(items), "pnl": sum(item.pnl for item in items)}
        for name, items in buckets.items()
    }


def _benchmarks(snapshot: MarketSnapshot, start: float) -> dict[str, float]:
    bars = snapshot.candles.get("1d", [])
    if len(bars) < 2:
        return {"buy_and_hold_return": 0, "fixed_amount_dca_return": 0, "cash_return": 0}
    buy_hold = bars[-1].close / bars[0].open - 1
    monthly = [bar for index, bar in enumerate(bars) if index % 30 == 0]
    allocation = start / max(1, len(monthly))
    quantity = sum(allocation / bar.open for bar in monthly)
    dca = quantity * bars[-1].close / start - 1
    return {"buy_and_hold_return": buy_hold, "fixed_amount_dca_return": dca, "cash_return": 0}


def run_backtest(
    snapshot: MarketSnapshot,
    config: AppConfig,
    profile: str = "auto",
    horizons: list[Horizon] | None = None,
) -> BacktestResult:
    selected = horizons or list(Horizon)
    equity = config.research.starting_equity
    trades: list[BacktestTrade] = []
    funnel = Counter({"evaluations": 0, "candidates": 0, "validated": 0, "cancelled": 0})
    blockers: Counter[str] = Counter()
    cancellations: Counter[str] = Counter()
    for horizon in selected:
        bars = snapshot.candles.get(PRIMARY[horizon], [])
        for index in range(1, len(bars) - 1):
            at = bars[index].close_time
            report = replay_signal(snapshot, at, config, profile)
            plan = report.horizons[horizon]
            funnel["evaluations"] += 1
            if plan.status != SignalStatus.CANDIDATE:
                blockers.update(plan.failed_conditions)
                continue
            funnel["candidates"] += 1
            next_bar = bars[index + 1]
            validation_snapshot = _validation_snapshot(snapshot, next_bar.open_time)
            validation = validate_entry(report, validation_snapshot, horizon)
            if validation.status == SignalStatus.ENTRY_CANCELLED:
                funnel["cancelled"] += 1
                cancellations.update(validation.reasons)
                continue
            funnel["validated"] += 1
            trade = _simulate_trade(
                bars, index + 1, plan, snapshot.symbol, equity, config, report.profile
            )
            trades.append(trade)
            equity += trade.pnl
    trades.sort(key=lambda trade: trade.entry_time)
    rolling = []
    if trades:
        start = trades[0].entry_time
        end = trades[-1].exit_time
        while start <= end:
            window_end = start + timedelta(days=config.research.rolling_days)
            items = [trade for trade in trades if start <= trade.entry_time < window_end]
            rolling.append(
                {
                    "start": start.isoformat(),
                    "end": window_end.isoformat(),
                    "trade_count": len(items),
                    "pnl": sum(item.pnl for item in items),
                }
            )
            start = window_end
    return BacktestResult(
        symbol=snapshot.symbol,
        generated_at=datetime.now(UTC),
        metrics=_metrics(trades, config.research.starting_equity, config.research.minimum_trades),
        benchmarks=_benchmarks(snapshot, config.research.starting_equity),
        time_splits=_time_splits(trades, config),
        rolling_windows=rolling,
        trades=trades,
        candidate_funnel=dict(funnel),
        blockers=dict(blockers),
        cancellations=dict(cancellations),
        assumptions={
            "execution": "next_primary_bar_open",
            "intrabar_order": "stop_first",
            "fee_rate": config.research.fee_rate,
            "slippage_rate": config.research.slippage_rate,
            "historical_replay_not_unseen_test": True,
        },
    )
