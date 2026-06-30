"""Strict time-forward, long-only spot backtest engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from .config import AppConfig
from .indicators import add_indicators
from .models import BacktestMetrics, BacktestResult, TradeRecord, Trend


@dataclass(slots=True)
class _Position:
    entry_time: pd.Timestamp
    entry_index: int
    entry_price: float
    original_quantity: float
    remaining_quantity: float
    stop_price: float
    target_1: float
    target_2: float
    target_1_done: bool
    target_2_done: bool
    entry_cost: float
    exit_proceeds: float
    fees: float
    slippage: float
    regime: Trend


def _trend_from_row(row: pd.Series) -> Trend:
    score = 0
    if row["ema20"] > row["ema50"] > row["ema200"]:
        score += 2
    elif row["ema20"] < row["ema50"] < row["ema200"]:
        score -= 2
    score += 1 if row["close"] > row["ema200"] else -1
    score += 1 if row["macd_histogram"] > 0 else -1
    return Trend.BULLISH if score >= 3 else Trend.BEARISH if score <= -3 else Trend.SIDEWAYS


def _daily_trends(frame: pd.DataFrame, enable_adx: bool) -> pd.Series:
    rules = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    daily = frame[list(rules)].resample("1D", label="left", closed="left").agg(rules).dropna()
    if len(daily) < 200:
        return pd.Series(index=frame.index, data=Trend.SIDEWAYS.value, dtype="object")
    daily_indicators = add_indicators(daily, enable_adx=enable_adx)
    trend_values = daily_indicators.apply(_trend_from_row, axis=1).astype(str)
    available = pd.DataFrame(
        {
            "available_at": trend_values.index + pd.Timedelta(days=1),
            "daily_trend": trend_values.values,
        }
    ).sort_values("available_at")
    bars = pd.DataFrame({"timestamp": frame.index}).sort_values("timestamp")
    joined = pd.merge_asof(
        bars,
        available,
        left_on="timestamp",
        right_on="available_at",
        direction="backward",
    )
    values = joined["daily_trend"].fillna(Trend.SIDEWAYS.value).to_numpy()
    return pd.Series(values, index=frame.index, dtype="object")


def _entry_setup(
    frame: pd.DataFrame, index: int, daily_trend: Trend, config: AppConfig
) -> dict[str, float] | None:
    row, previous = frame.iloc[index], frame.iloc[index - 1]
    if daily_trend == Trend.BEARISH or _trend_from_row(row) == Trend.BEARISH:
        return None
    support = float(frame["low"].iloc[max(0, index - 30) : index].min())
    resistance = float(frame["high"].iloc[max(0, index - 80) : index].max())
    atr, close = float(row["atr14"]), float(row["close"])
    near_support = close - support <= atr * 1.5
    confirmations = sum(
        (
            bool(row["rsi14"] > previous["rsi14"] and row["rsi14"] <= 55),
            bool(row["macd_histogram"] > previous["macd_histogram"]),
            bool(
                row["volume_ratio"] >= config.strategy.volume_ratio_threshold
                and row["close"] > previous["close"]
            ),
            bool(previous["close"] <= previous["ema20"] and row["close"] > row["ema20"]),
            bool(row["close"] > row["open"] and row["close"] > previous["close"]),
        )
    )
    stop = min(support - atr * 0.25, close - atr)
    if not near_support or confirmations < config.strategy.min_confirmations or stop <= 0:
        return None
    one_r = close - stop
    if one_r <= 0 or (resistance - close) / one_r < config.risk.min_reward_risk:
        return None
    return {"stop": stop, "one_r": one_r}


def _streak(values: list[bool], target: bool) -> int:
    best = current = 0
    for value in values:
        if value is target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _finite(value: float) -> float:
    return round(float(value), 8) if np.isfinite(value) else 0.0


def _metrics(
    equity: pd.Series,
    trades: list[TradeRecord],
    initial: float,
    fees: float,
    slippage: float,
    buy_hold: float,
) -> BacktestMetrics:
    final = float(equity.iloc[-1])
    total_return = final / initial - 1
    days = max((equity.index[-1] - equity.index[0]).total_seconds() / 86_400, 1)
    annualized = (1 + total_return) ** (365.25 / days) - 1 if total_return > -1 else -1.0
    drawdown = equity / equity.cummax() - 1
    bar_returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    bars_per_year = 365.25 * 6
    std = float(bar_returns.std(ddof=1))
    downside = float(bar_returns[bar_returns < 0].std(ddof=1))
    sharpe = float(bar_returns.mean()) / std * np.sqrt(bars_per_year) if std > 0 else 0.0
    sortino = float(bar_returns.mean()) / downside * np.sqrt(bars_per_year) if downside > 0 else 0.0
    wins = [trade.pnl for trade in trades if trade.pnl > 0]
    losses = [-trade.pnl for trade in trades if trade.pnl < 0]
    payoff = (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else 0.0
    profit_factor = sum(wins) / sum(losses) if losses else (999.0 if wins else 0.0)
    outcomes = [trade.pnl > 0 for trade in trades]
    return BacktestMetrics(
        total_return=_finite(total_return),
        annualized_return=_finite(annualized),
        max_drawdown=_finite(abs(float(drawdown.min()))),
        win_rate=_finite(len(wins) / len(trades) if trades else 0.0),
        payoff_ratio=_finite(payoff),
        profit_factor=_finite(profit_factor),
        sharpe_ratio=_finite(sharpe),
        sortino_ratio=_finite(sortino),
        trade_count=len(trades),
        average_holding_hours=_finite(
            np.mean([trade.holding_hours for trade in trades]) if trades else 0.0
        ),
        max_consecutive_wins=_streak(outcomes, True),
        max_consecutive_losses=_streak(outcomes, False),
        total_fees=_finite(fees),
        slippage_cost=_finite(slippage),
        buy_and_hold_return=_finite(buy_hold),
    )


def _split_results(equity: pd.Series, config: AppConfig) -> dict[str, dict[str, object]]:
    length = len(equity)
    train_end = max(1, int(length * config.backtest.train_ratio))
    validation_end = max(
        train_end + 1,
        int(length * (config.backtest.train_ratio + config.backtest.validation_ratio)),
    )
    slices = {
        "train": equity.iloc[:train_end],
        "validation": equity.iloc[train_end:validation_end],
        "test": equity.iloc[validation_end:],
    }
    result: dict[str, dict[str, object]] = {}
    for name, values in slices.items():
        if len(values) < 2:
            result[name] = {"start": "not_available", "end": "not_available", "return": 0.0}
        else:
            result[name] = {
                "start": values.index[0].isoformat(),
                "end": values.index[-1].isoformat(),
                "return": _finite(float(values.iloc[-1] / values.iloc[0] - 1)),
            }
    return result


def run_backtest(frame: pd.DataFrame, symbol: str, config: AppConfig) -> BacktestResult:
    """Run one deterministic, next-bar execution backtest on completed 4h bars."""

    enriched = add_indicators(frame.copy(), enable_adx=config.strategy.enable_adx).dropna(
        subset=["ema200", "atr14", "rsi14"]
    )
    if len(enriched) <= config.backtest.warmup_bars + 2:
        raise ValueError("backtest requires more bars than warmup_bars")
    daily_trends = (
        _daily_trends(frame, config.strategy.enable_adx)
        .reindex(enriched.index)
        .fillna(Trend.SIDEWAYS.value)
    )
    rate = config.risk.cny_per_usdt
    initial_quote = config.risk.account_equity_cny / rate
    cash = initial_quote
    peak_equity = initial_quote
    position: _Position | None = None
    pending: dict[str, float | Trend] | None = None
    trades: list[TradeRecord] = []
    equity_values: list[float] = []
    equity_times: list[pd.Timestamp] = []
    total_fees = total_slippage = 0.0
    current_day = None
    daily_stops = 0
    day_start_equity = initial_quote
    day_realized_loss = 0.0

    for index in range(config.backtest.warmup_bars, len(enriched)):
        timestamp, row = pd.Timestamp(enriched.index[index]), enriched.iloc[index]
        if current_day != timestamp.date():
            current_day = timestamp.date()
            daily_stops = 0
            day_realized_loss = 0.0
            day_start_equity = cash + (
                position.remaining_quantity * float(row["open"]) if position else 0.0
            )

        if pending is not None and position is None:
            raw_open = float(row["open"])
            entry_price = raw_open * (1 + config.backtest.slippage_rate)
            stop = float(pending["stop"])
            if stop < entry_price:
                equity_before = cash
                risk_quote = equity_before * config.risk.risk_per_trade
                quantity_by_risk = risk_quote / (entry_price - stop)
                quantity_by_cash = cash / (entry_price * (1 + config.backtest.fee_rate))
                quantity = min(
                    quantity_by_risk, quantity_by_cash * config.risk.max_position_fraction
                )
                if quantity > 0:
                    notional = quantity * entry_price
                    fee = notional * config.backtest.fee_rate
                    slip = quantity * (entry_price - raw_open)
                    cash -= notional + fee
                    total_fees += fee
                    total_slippage += slip
                    one_r = entry_price - stop
                    position = _Position(
                        entry_time=timestamp,
                        entry_index=index,
                        entry_price=entry_price,
                        original_quantity=quantity,
                        remaining_quantity=quantity,
                        stop_price=stop,
                        target_1=entry_price + config.risk.min_reward_risk * one_r,
                        target_2=entry_price + (config.risk.min_reward_risk + 1) * one_r,
                        target_1_done=False,
                        target_2_done=False,
                        entry_cost=notional + fee,
                        exit_proceeds=0.0,
                        fees=fee,
                        slippage=slip,
                        regime=Trend(str(pending["regime"])),
                    )
            pending = None

        closed_reason: str | None = None
        if position is not None:
            low, high, open_price = float(row["low"]), float(row["high"]), float(row["open"])
            if low <= position.stop_price:
                raw_exit = min(open_price, position.stop_price)
                exit_price = raw_exit * (1 - config.backtest.slippage_rate)
                quantity = position.remaining_quantity
                proceeds = quantity * exit_price
                fee = proceeds * config.backtest.fee_rate
                slip = quantity * (raw_exit - exit_price)
                cash += proceeds - fee
                position.exit_proceeds += proceeds - fee
                position.fees += fee
                position.slippage += slip
                total_fees += fee
                total_slippage += slip
                position.remaining_quantity = 0.0
                closed_reason = (
                    "stop_loss" if index > position.entry_index else "entry_bar_protective_stop"
                )
            elif index > position.entry_index:
                if not position.target_1_done and high >= position.target_1:
                    quantity = min(position.original_quantity * 0.30, position.remaining_quantity)
                    exit_price = position.target_1 * (1 - config.backtest.slippage_rate)
                    proceeds = quantity * exit_price
                    fee = proceeds * config.backtest.fee_rate
                    slip = quantity * (position.target_1 - exit_price)
                    cash += proceeds - fee
                    position.exit_proceeds += proceeds - fee
                    position.fees += fee
                    position.slippage += slip
                    total_fees += fee
                    total_slippage += slip
                    position.remaining_quantity -= quantity
                    position.target_1_done = True
                if (
                    position.target_1_done
                    and not position.target_2_done
                    and high >= position.target_2
                ):
                    quantity = min(position.original_quantity * 0.30, position.remaining_quantity)
                    exit_price = position.target_2 * (1 - config.backtest.slippage_rate)
                    proceeds = quantity * exit_price
                    fee = proceeds * config.backtest.fee_rate
                    slip = quantity * (position.target_2 - exit_price)
                    cash += proceeds - fee
                    position.exit_proceeds += proceeds - fee
                    position.fees += fee
                    position.slippage += slip
                    total_fees += fee
                    total_slippage += slip
                    position.remaining_quantity -= quantity
                    position.target_2_done = True
                if position.target_1_done:
                    if config.risk.trailing_stop_method == "atr":
                        trailing = float(
                            row["close"] - row["atr14"] * config.risk.trailing_atr_multiple
                        )
                    else:
                        trailing = float(enriched["low"].iloc[max(0, index - 10) : index].min())
                    position.stop_price = max(position.stop_price, trailing)

            if position is not None and position.remaining_quantity <= 1e-12:
                pnl_quote = position.exit_proceeds - position.entry_cost
                if closed_reason and "stop" in closed_reason and pnl_quote < 0:
                    daily_stops += 1
                    day_realized_loss += -pnl_quote
                gross_exit_quantity = position.original_quantity
                average_exit = (position.exit_proceeds + position.fees) / gross_exit_quantity
                trades.append(
                    TradeRecord(
                        symbol=symbol,
                        entry_time=position.entry_time.to_pydatetime(),
                        exit_time=timestamp.to_pydatetime(),
                        entry_price=position.entry_price,
                        exit_price=average_exit,
                        quantity=position.original_quantity,
                        pnl=pnl_quote * rate,
                        return_pct=pnl_quote / position.entry_cost,
                        fees=position.fees * rate,
                        slippage_cost=position.slippage * rate,
                        holding_hours=(timestamp - position.entry_time).total_seconds() / 3600,
                        exit_reason=closed_reason or "completed_exit",
                        market_regime=position.regime,
                    )
                )
                position = None

        mark = float(row["close"])
        equity = cash + (position.remaining_quantity * mark if position else 0.0)
        peak_equity = max(peak_equity, equity)
        drawdown = 1 - equity / peak_equity if peak_equity > 0 else 1.0
        equity_times.append(timestamp)
        equity_values.append(equity * rate)

        if position is None and pending is None and index < len(enriched) - 1:
            daily_loss_fraction = (
                day_realized_loss / day_start_equity if day_start_equity > 0 else 1.0
            )
            locked = (
                daily_stops >= config.risk.daily_stop_count
                or daily_loss_fraction >= config.risk.daily_max_loss
                or drawdown >= config.risk.max_drawdown
            )
            daily_trend = Trend(str(daily_trends.iloc[index]))
            setup = None if locked else _entry_setup(enriched, index, daily_trend, config)
            if setup:
                pending = {"stop": setup["stop"], "regime": daily_trend}

    if position is not None:
        timestamp, row = pd.Timestamp(enriched.index[-1]), enriched.iloc[-1]
        raw_exit = float(row["close"])
        exit_price = raw_exit * (1 - config.backtest.slippage_rate)
        proceeds = position.remaining_quantity * exit_price
        fee = proceeds * config.backtest.fee_rate
        slip = position.remaining_quantity * (raw_exit - exit_price)
        cash += proceeds - fee
        position.exit_proceeds += proceeds - fee
        position.fees += fee
        position.slippage += slip
        total_fees += fee
        total_slippage += slip
        pnl_quote = position.exit_proceeds - position.entry_cost
        trades.append(
            TradeRecord(
                symbol=symbol,
                entry_time=position.entry_time.to_pydatetime(),
                exit_time=timestamp.to_pydatetime(),
                entry_price=position.entry_price,
                exit_price=(position.exit_proceeds + position.fees) / position.original_quantity,
                quantity=position.original_quantity,
                pnl=pnl_quote * rate,
                return_pct=pnl_quote / position.entry_cost,
                fees=position.fees * rate,
                slippage_cost=position.slippage * rate,
                holding_hours=(timestamp - position.entry_time).total_seconds() / 3600,
                exit_reason="end_of_test",
                market_regime=position.regime,
            )
        )
        equity_values[-1] = cash * rate

    equity_series = pd.Series(equity_values, index=pd.DatetimeIndex(equity_times), dtype=float)
    initial_cny = config.risk.account_equity_cny
    buy_hold = float(
        enriched["close"].iloc[-1] / enriched["close"].iloc[config.backtest.warmup_bars] - 1
    )
    metrics = _metrics(
        equity_series,
        trades,
        initial_cny,
        total_fees * rate,
        total_slippage * rate,
        buy_hold,
    )
    yearly = (
        equity_series.resample("YE")
        .last()
        .pct_change()
        .fillna(equity_series.resample("YE").last().iloc[0] / initial_cny - 1)
    )
    phase_results = {
        trend.value: _finite(
            sum(trade.pnl for trade in trades if trade.market_regime == trend) / initial_cny
        )
        for trend in Trend
    }
    return BacktestResult(
        generated_at=datetime.now(UTC),
        symbol=symbol,
        interval=config.backtest.interval,
        start_time=equity_series.index[0].to_pydatetime(),
        end_time=equity_series.index[-1].to_pydatetime(),
        initial_capital_cny=initial_cny,
        final_equity_cny=float(equity_series.iloc[-1]),
        config={
            "fee_rate": config.backtest.fee_rate,
            "slippage_rate": config.backtest.slippage_rate,
            "risk_per_trade": config.risk.risk_per_trade,
            "random_seed": config.strategy.random_seed,
            "parameter_optimization": False,
        },
        metrics=metrics,
        walk_forward_splits=_split_results(equity_series, config),
        yearly_results={str(index.year): _finite(value) for index, value in yearly.items()},
        market_phase_results=phase_results,
        trades=trades,
        warnings=[
            "固定 BTC/ETH 样本不能代表全市场，仍存在样本选择限制。",
            "日线仅使用完整自然日，并在次日才可用于 4 小时决策。",
            "同一根 K 线同时触发止损和目标时按止损优先；入场 K 线不执行止盈。",
            "没有自动参数优化；时间切分只用于报告。",
        ],
    )
