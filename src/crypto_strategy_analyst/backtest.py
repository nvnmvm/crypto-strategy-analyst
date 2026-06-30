"""Strict three-timeframe replay using the shared strategy evaluator."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

import numpy as np
import pandas as pd

from .config import AppConfig
from .errors import PositionConstraintError
from .execution import validate_pending_entry_at_open
from .models import (
    BacktestMetrics,
    BacktestResult,
    CostScenarioMetrics,
    SignalLabel,
    SymbolTradingRules,
    TradeRecord,
    Trend,
)
from .risk import RiskState, calculate_position
from .signal import SignalDecision
from .strategy import SetupEvaluation, evaluate_setup_at_time, prepare_market_frames


@dataclass(slots=True)
class _PendingEntry:
    signal: SignalDecision
    atr: float
    created_index: int
    regime: Trend


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
    initial_risk_cny: float


def _utc_timestamp(value: str | datetime | None) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def evaluate_backtest_at_time(
    frames: Mapping[str, pd.DataFrame],
    config: AppConfig,
    *,
    evaluated_at: datetime,
    risk_state: RiskState | None = None,
) -> SetupEvaluation:
    """Evaluate open-time-indexed replay frames at the shared completed 4h close."""

    prepared = prepare_market_frames(frames, config)
    return evaluate_setup_at_time(
        prepared,
        config,
        requested_at=evaluated_at,
        risk_state=risk_state,
        data_is_complete=True,
    )


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
    exposure_percent: float,
    average_capital_utilization: float,
    generated_signal_count: int,
    cancelled_signal_count: int,
    no_trade_count: int,
) -> BacktestMetrics:
    final = float(equity.iloc[-1])
    total_return = final / initial - 1
    days = max((equity.index[-1] - equity.index[0]).total_seconds() / 86_400, 1)
    annualized = (1 + total_return) ** (365.25 / days) - 1 if total_return > -1 else -1.0
    drawdown = equity / equity.cummax() - 1
    bar_returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    bars_per_year = 365.25 * 6
    standard_deviation = float(bar_returns.std(ddof=1))
    downside = float(bar_returns[bar_returns < 0].std(ddof=1))
    sharpe = (
        float(bar_returns.mean()) / standard_deviation * np.sqrt(bars_per_year)
        if standard_deviation > 0
        else 0.0
    )
    sortino = float(bar_returns.mean()) / downside * np.sqrt(bars_per_year) if downside > 0 else 0.0
    wins = [trade.pnl for trade in trades if trade.pnl > 0]
    losses = [-trade.pnl for trade in trades if trade.pnl < 0]
    payoff = (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else 0.0
    profit_factor = sum(wins) / sum(losses) if losses else (999.0 if wins else 0.0)
    outcomes = [trade.pnl > 0 for trade in trades]
    realized_r = [trade.realized_r_multiple for trade in trades]
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
        expectancy=_finite(float(np.mean([trade.pnl for trade in trades])) if trades else 0.0),
        exposure_percent=_finite(exposure_percent),
        average_capital_utilization=_finite(average_capital_utilization),
        generated_signal_count=generated_signal_count,
        executed_trade_count=len(trades),
        cancelled_signal_count=cancelled_signal_count,
        no_trade_count=no_trade_count,
        average_initial_risk_cny=_finite(
            float(np.mean([trade.initial_risk_cny for trade in trades])) if trades else 0.0
        ),
        average_realized_r_multiple=_finite(float(np.mean(realized_r)) if realized_r else 0.0),
        median_realized_r_multiple=_finite(float(np.median(realized_r)) if realized_r else 0.0),
    )


def _time_split_results(equity: pd.Series, config: AppConfig) -> dict[str, dict[str, object]]:
    """Report fixed chronological splits; this is not walk-forward optimization."""

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


def _record_closed_trade(
    *,
    position: _Position,
    symbol: str,
    timestamp: pd.Timestamp,
    exit_reason: str,
    rate: float,
) -> TradeRecord:
    pnl_quote = position.exit_proceeds - position.entry_cost
    return TradeRecord(
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
        exit_reason=exit_reason,
        market_regime=position.regime,
        initial_risk_cny=position.initial_risk_cny,
        realized_r_multiple=(
            pnl_quote * rate / position.initial_risk_cny if position.initial_risk_cny > 0 else 0.0
        ),
    )


def _frames_hash(frames: Mapping[str, pd.DataFrame]) -> str:
    digest = hashlib.sha256()
    for timeframe in ("1d", "4h", "1h"):
        digest.update(timeframe.encode())
        digest.update(
            frames[timeframe].to_csv(index=True, float_format="%.12g").encode("utf-8")
        )
    return digest.hexdigest()


def _strategy_config_hash(config: AppConfig) -> str:
    payload = {
        "config_version": config.config_version,
        "market": config.market.model_dump(mode="json"),
        "risk": config.risk.model_dump(mode="json"),
        "strategy": config.strategy.model_dump(mode="json"),
        "backtest": config.backtest.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _package_version() -> str:
    try:
        return version("crypto-strategy-analyst")
    except PackageNotFoundError:  # pragma: no cover
        return "0.1.2"


def run_backtest(
    frames: Mapping[str, pd.DataFrame],
    symbol: str,
    config: AppConfig,
    *,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    decision_observer: Callable[[datetime, SetupEvaluation], None] | None = None,
    trading_rules: SymbolTradingRules | None = None,
    dataset_hash: str | None = None,
    include_cost_sensitivity: bool = False,
) -> BacktestResult:
    """Replay closed 1d/4h/1h inputs and execute each decision next 4h open.

    DataFrame indices are candle open times. ``close_time`` is open plus four
    hours; only then is the shared evaluator called, and a pending entry cannot
    execute until the following frame's open.
    """

    prepared = prepare_market_frames(frames, config)
    four_hour = prepared["4h"]
    earliest = max(
        prepared["1d"].index[209] + pd.Timedelta(days=1),
        prepared["4h"].index[209] + pd.Timedelta(hours=4),
        prepared["1h"].index[209] + pd.Timedelta(hours=1),
    )
    start_time = max(filter(None, [earliest, _utc_timestamp(start)]))
    end_time = _utc_timestamp(end) or four_hour.index[-1] + pd.Timedelta(hours=4)
    bar_close_times = four_hour.index + pd.Timedelta(hours=4)
    replay_positions = np.flatnonzero(
        (bar_close_times >= start_time) & (bar_close_times <= end_time)
    )
    if len(replay_positions) < 3:
        raise ValueError("backtest range must contain at least three replay bars after warmup")

    rate = config.risk.cny_per_usdt
    initial_quote = config.risk.account_equity_cny / rate
    cash = initial_quote
    position: _Position | None = None
    pending: _PendingEntry | None = None
    trades: list[TradeRecord] = []
    equity_values: list[float] = []
    equity_times: list[pd.Timestamp] = []
    total_fees = total_slippage = 0.0
    generated_signal_count = executed_entry_count = cancelled_entry_count = no_trade_count = 0
    cancelled_reasons: Counter[str] = Counter()
    exposure_flags: list[float] = []
    capital_utilization: list[float] = []
    risk_state = RiskState(
        date=start_time.date(),
        daily_start_equity_cny=config.risk.account_equity_cny,
        current_equity_cny=config.risk.account_equity_cny,
        peak_equity_cny=config.risk.account_equity_cny,
    )

    for replay_index, index in enumerate(replay_positions):
        timestamp = pd.Timestamp(four_hour.index[index])
        close_time = timestamp + pd.Timedelta(hours=4)
        row = four_hour.iloc[index]
        risk_state = risk_state.rolled_to(close_time.date())

        if pending is not None and position is None:
            raw_open = float(row["open"])
            entry_price = raw_open * (1 + config.backtest.slippage_rate)
            validation = validate_pending_entry_at_open(
                pending.signal,
                entry_price,
                pending.atr,
                config,
                age_bars=index - pending.created_index,
            )
            if validation.is_valid:
                suggestion = None
                try:
                    suggestion = calculate_position(
                        entry_price=entry_price,
                        stop_price=float(pending.signal.stop_loss),
                        config=config.risk,
                        account_equity_cny=cash * rate,
                        trading_rules=trading_rules,
                    )
                except (PositionConstraintError, ValueError) as exc:
                    cancelled_reasons[str(exc)] += 1
                    cancelled_entry_count += 1
                if suggestion is not None:
                    quantity = suggestion.quantity
                    normalized_entry = suggestion.entry_price
                    notional = quantity * normalized_entry
                    fee = notional * config.backtest.fee_rate
                    slip = quantity * (normalized_entry - raw_open)
                    if notional + fee > cash:
                        cancelled_reasons["insufficient_cash_after_fees"] += 1
                        cancelled_entry_count += 1
                    else:
                        cash -= notional + fee
                        total_fees += fee
                        total_slippage += slip
                        position = _Position(
                            entry_time=timestamp,
                            entry_index=index,
                            entry_price=normalized_entry,
                            original_quantity=quantity,
                            remaining_quantity=quantity,
                            stop_price=suggestion.stop_price,
                            target_1=float(pending.signal.take_profit_1),
                            target_2=float(pending.signal.take_profit_2),
                            target_1_done=False,
                            target_2_done=False,
                            entry_cost=notional + fee,
                            exit_proceeds=0.0,
                            fees=fee,
                            slippage=slip,
                            regime=pending.regime,
                            initial_risk_cny=suggestion.risk_amount_cny,
                        )
                        executed_entry_count += 1
            else:
                cancelled_entry_count += 1
                cancelled_reasons.update(validation.reasons)
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
                    "entry_bar_protective_stop" if index == position.entry_index else "stop_loss"
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
                        trailing = float(four_hour["low"].iloc[max(0, index - 10) : index].min())
                    position.stop_price = max(position.stop_price, trailing)

            if position is not None and position.remaining_quantity <= 1e-12:
                trade = _record_closed_trade(
                    position=position,
                    symbol=symbol,
                    timestamp=timestamp,
                    exit_reason=closed_reason or "completed_exit",
                    rate=rate,
                )
                trades.append(trade)
                risk_state = risk_state.with_realized_result(
                    trade.pnl,
                    stopped_out=bool(closed_reason and "stop" in closed_reason),
                )
                position = None

        mark = float(row["close"])
        equity_quote = cash + (position.remaining_quantity * mark if position else 0.0)
        equity_cny = equity_quote * rate
        risk_state = risk_state.with_equity(equity_cny)
        equity_times.append(close_time)
        equity_values.append(equity_cny)
        exposure_flags.append(1.0 if position else 0.0)
        capital_utilization.append(
            (position.remaining_quantity * mark / equity_quote)
            if position is not None and equity_quote > 0
            else 0.0
        )

        if position is None and pending is None and replay_index < len(replay_positions) - 1:
            evaluation = evaluate_setup_at_time(
                prepared,
                config,
                requested_at=close_time.to_pydatetime(),
                risk_state=risk_state,
                data_is_complete=True,
            )
            if decision_observer:
                decision_observer(close_time.to_pydatetime(), evaluation)
            decision = evaluation.decision
            if (
                decision.label in {SignalLabel.BUY_CANDIDATE, SignalLabel.STRONG_BUY_CANDIDATE}
                and decision.stop_loss is not None
                and decision.take_profit_1 is not None
                and decision.take_profit_2 is not None
            ):
                generated_signal_count += 1
                pending = _PendingEntry(
                    signal=decision,
                    atr=float(evaluation.frames["4h"]["atr14"].iloc[-1]),
                    created_index=index,
                    regime=evaluation.trends["1d"],
                )
            else:
                no_trade_count += 1

    if position is not None:
        timestamp = pd.Timestamp(four_hour.index[replay_positions[-1]])
        row = four_hour.iloc[replay_positions[-1]]
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
        trades.append(
            _record_closed_trade(
                position=position,
                symbol=symbol,
                timestamp=timestamp,
                exit_reason="end_of_test",
                rate=rate,
            )
        )
        equity_values[-1] = cash * rate

    equity_series = pd.Series(equity_values, index=pd.DatetimeIndex(equity_times), dtype=float)
    initial_cny = config.risk.account_equity_cny
    first_bar = four_hour.iloc[replay_positions[0]]
    last_bar = four_hour.iloc[replay_positions[-1]]
    buy_hold = float(last_bar["close"] / first_bar["open"] - 1)
    metrics = _metrics(
        equity_series,
        trades,
        initial_cny,
        total_fees * rate,
        total_slippage * rate,
        buy_hold,
        float(np.mean(exposure_flags) * 100 if exposure_flags else 0.0),
        float(np.mean(capital_utilization) if capital_utilization else 0.0),
        generated_signal_count,
        cancelled_entry_count,
        no_trade_count,
    )
    yearly_values = equity_series.resample("YE").last()
    yearly = yearly_values.pct_change().fillna(yearly_values.iloc[0] / initial_cny - 1)
    phase_results = {
        trend.value: _finite(
            sum(trade.pnl for trade in trades if trade.market_regime == trend) / initial_cny
        )
        for trend in Trend
    }
    insufficient_warning = (
        f"交易样本仅 {len(trades)} 笔，少于 {config.backtest.minimum_sample_trades} 笔；"
        "胜率、Sharpe、Sortino 等统计不宜用于证明策略有效。"
        if len(trades) < config.backtest.minimum_sample_trades
        else None
    )
    result = BacktestResult(
        generated_at=datetime.now(UTC),
        package_version=_package_version(),
        strategy_config_hash=_strategy_config_hash(config),
        dataset_hash=dataset_hash or _frames_hash(frames),
        random_seed=config.strategy.random_seed,
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
            "strategy_evaluator": "evaluate_setup_at_time",
            "timeframes": ["1d", "4h", "1h"],
        },
        metrics=metrics,
        time_splits=_time_split_results(equity_series, config),
        yearly_results={str(index.year): _finite(value) for index, value in yearly.items()},
        market_phase_results=phase_results,
        generated_signal_count=generated_signal_count,
        executed_entry_count=executed_entry_count,
        cancelled_entry_count=cancelled_entry_count,
        cancelled_entry_reasons=dict(sorted(cancelled_reasons.items())),
        cost_sensitivity={},
        insufficient_sample_warning=insufficient_warning,
        trades=trades,
        warnings=[
            "固定 BTC/ETH 样本不能代表全市场，仍存在样本选择限制。",
            "每次评估只纳入该时刻已经收盘的日线、4 小时线和 1 小时线。",
            "同一根 K 线同时触发止损和目标时按止损优先；入场 K 线不执行止盈。",
            "60%/20%/20% 仅为固定时间切分，不是 walk-forward，且没有自动参数优化。",
            *([insufficient_warning] if insufficient_warning else []),
        ],
    )
    if not include_cost_sensitivity:
        return result
    scenarios = {
        "base": (1.0, 1.0),
        "fee_x2": (2.0, 1.0),
        "slippage_x2": (1.0, 2.0),
        "fee_and_slippage_x2": (2.0, 2.0),
    }
    sensitivity: dict[str, CostScenarioMetrics] = {}
    for name, (fee_multiplier, slippage_multiplier) in scenarios.items():
        scenario_result = result
        if name != "base":
            scenario_backtest = config.backtest.model_copy(
                update={
                    "fee_rate": config.backtest.fee_rate * fee_multiplier,
                    "slippage_rate": config.backtest.slippage_rate * slippage_multiplier,
                }
            )
            scenario_config = config.model_copy(update={"backtest": scenario_backtest})
            scenario_result = run_backtest(
                frames,
                symbol,
                scenario_config,
                start=start,
                end=end,
                trading_rules=trading_rules,
                dataset_hash=result.dataset_hash,
                include_cost_sensitivity=False,
            )
        sensitivity[name] = CostScenarioMetrics(
            total_return=scenario_result.metrics.total_return,
            max_drawdown=scenario_result.metrics.max_drawdown,
            profit_factor=scenario_result.metrics.profit_factor,
            trade_count=scenario_result.metrics.trade_count,
        )
    return result.model_copy(update={"cost_sensitivity": sensitivity})
