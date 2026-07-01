"""Strict three-timeframe replay using the shared strategy evaluator."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
import pandas as pd

from .config import AppConfig
from .errors import PositionConstraintError
from .execution import validate_pending_entry_at_open
from .models import (
    BacktestMetrics,
    BacktestResult,
    BenchmarkMetrics,
    CostScenarioMetrics,
    MarketRegime,
    ResearchProtocol,
    SignalLabel,
    StrategyHorizon,
    SymbolTradingRules,
    TradeRecord,
    Trend,
)
from .risk import RiskState, calculate_position
from .signal import SignalDecision
from .strategy import SetupEvaluation, evaluate_setup_at_time, prepare_market_frames
from .trading_rules import ceil_to_increment, floor_to_increment


@dataclass(slots=True)
class _PendingEntry:
    signal: SignalDecision
    atr: float
    created_index: int
    regime: Trend
    tranche_number: int = 1


@dataclass(slots=True)
class _Position:
    entry_time: pd.Timestamp
    entry_index: int
    entry_price: float
    original_quantity: float
    remaining_quantity: float
    stop_price: float
    target_1: float
    target_2: float | None
    target_1_done: bool
    target_2_done: bool
    entry_cost: float
    exit_proceeds: float
    fees: float
    slippage: float
    regime: Trend
    initial_risk_cny: float
    strategy_id: str
    risk_multiplier: float
    market_regime_detail: MarketRegime | None
    entry_setup: str
    candidate_tier: str
    strategy_horizon: StrategyHorizon
    entry_count: int = 1


def conservative_buy_fill(
    reference_price: float,
    slippage_rate: float,
    trading_rules: SymbolTradingRules | None,
) -> float:
    slipped = reference_price * (1 + slippage_rate)
    return ceil_to_increment(slipped, trading_rules.price_tick_size) if trading_rules else slipped


def conservative_sell_fill(
    reference_price: float,
    slippage_rate: float,
    trading_rules: SymbolTradingRules | None,
) -> float:
    slipped = reference_price * (1 - slippage_rate)
    return floor_to_increment(slipped, trading_rules.price_tick_size) if trading_rules else slipped


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


def _record_daily_realized_result(
    risk_state: RiskState, pnl_cny: float, *, stopped_out: bool
) -> RiskState:
    """Update daily locks without double-counting already marked-to-market equity."""

    realized_loss = max(0.0, -pnl_cny)
    return risk_state.model_copy(
        update={
            "daily_stop_losses": risk_state.daily_stop_losses
            + int(stopped_out and realized_loss > 0),
            "daily_realized_loss_cny": risk_state.daily_realized_loss_cny + realized_loss,
        }
    )


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
    best_trade = max((trade.pnl for trade in trades), default=0.0)
    worst_trade = min((trade.pnl for trade in trades), default=0.0)
    net_profit = final - initial
    yearly_equity = equity.resample("YE").last()
    yearly_profit = yearly_equity.diff().fillna(yearly_equity.iloc[0] - initial)
    best_year_profit = float(yearly_profit.max()) if len(yearly_profit) else 0.0
    below_peak = equity < equity.cummax()
    longest_bars = current_bars = 0
    for is_below in below_peak:
        current_bars = current_bars + 1 if is_below else 0
        longest_bars = max(longest_bars, current_bars)
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
        annualized_volatility=_finite(standard_deviation * np.sqrt(bars_per_year)),
        longest_drawdown_recovery_days=_finite(longest_bars / 6),
        best_trade_pnl=_finite(best_trade),
        worst_trade_pnl=_finite(worst_trade),
        best_trade_profit_contribution=_finite(best_trade / net_profit if net_profit > 0 else 0.0),
        best_year_profit_contribution=_finite(
            best_year_profit / net_profit if net_profit > 0 else 0.0
        ),
        return_without_best_trade=_finite((net_profit - best_trade) / initial),
        return_without_best_year=_finite((net_profit - best_year_profit) / initial),
    )


def _time_split_results(equity: pd.Series, config: AppConfig) -> dict[str, dict[str, object]]:
    """Report preregistered calendar splits or legacy fixed-ratio splits."""

    if config.backtest.split_mode == "calendar":
        train_end = pd.Timestamp(config.backtest.train_end_date, tz="UTC") + pd.Timedelta(days=1)
        validation_end = pd.Timestamp(config.backtest.validation_end_date, tz="UTC") + pd.Timedelta(
            days=1
        )
        slices = {
            "train": equity[equity.index < train_end],
            "validation": equity[(equity.index >= train_end) & (equity.index < validation_end)],
            "test": equity[equity.index >= validation_end],
        }
    else:
        length = len(equity)
        train_position = max(1, int(length * config.backtest.train_ratio))
        validation_position = max(
            train_position + 1,
            int(length * (config.backtest.train_ratio + config.backtest.validation_ratio)),
        )
        slices = {
            "train": equity.iloc[:train_position],
            "validation": equity.iloc[train_position:validation_position],
            "test": equity.iloc[validation_position:],
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


def _rolling_window_results(equity: pd.Series) -> list[dict[str, object]]:
    """Evaluate a frozen strategy over rolling 365-day windows stepped by 180 days."""

    windows: list[dict[str, object]] = []
    cursor = equity.index[0]
    final_time = equity.index[-1]
    while cursor + pd.Timedelta(days=365) <= final_time:
        end = cursor + pd.Timedelta(days=365)
        values = equity[(equity.index >= cursor) & (equity.index <= end)]
        if len(values) >= 2:
            drawdown = values / values.cummax() - 1
            windows.append(
                {
                    "start": values.index[0].isoformat(),
                    "end": values.index[-1].isoformat(),
                    "return": _finite(float(values.iloc[-1] / values.iloc[0] - 1)),
                    "max_drawdown": _finite(abs(float(drawdown.min()))),
                    "positive": bool(values.iloc[-1] > values.iloc[0]),
                }
            )
        cursor += pd.Timedelta(days=180)
    return windows


def _benchmark_summary(
    equity: pd.Series,
    *,
    initial: float,
    fees: float,
    transaction_count: int,
    exposure_percent: float,
) -> BenchmarkMetrics:
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    drawdown = equity / equity.cummax() - 1
    days = max((equity.index[-1] - equity.index[0]).total_seconds() / 86_400, 1)
    total_return = float(equity.iloc[-1] / initial - 1)
    annualized = (1 + total_return) ** (365.25 / days) - 1 if total_return > -1 else -1.0
    below_peak = equity < equity.cummax()
    longest = current = 0
    for value in below_peak:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return BenchmarkMetrics(
        total_return=_finite(total_return),
        annualized_return=_finite(annualized),
        max_drawdown=_finite(abs(float(drawdown.min()))),
        annualized_volatility=_finite(float(returns.std(ddof=1)) * np.sqrt(365.25 * 6)),
        exposure_percent=_finite(exposure_percent),
        longest_drawdown_recovery_days=_finite(longest / 6),
        total_fees=_finite(fees),
        transaction_count=transaction_count,
    )


def _benchmarks(
    four_hour: pd.DataFrame,
    replay_positions: np.ndarray,
    config: AppConfig,
    trading_rules: SymbolTradingRules | None,
) -> dict[str, BenchmarkMetrics]:
    """Cost-aware lump-sum and fixed-total monthly DCA reference portfolios."""

    rows = four_hour.iloc[replay_positions]
    times = pd.DatetimeIndex(rows.index + pd.Timedelta(hours=4))
    initial = config.risk.account_equity_cny / config.risk.cny_per_usdt
    first_open = float(rows["open"].iloc[0])
    buy_fill = conservative_buy_fill(first_open, config.backtest.slippage_rate, trading_rules)
    buy_quantity = initial / (buy_fill * (1 + config.backtest.fee_rate))
    buy_fee = buy_quantity * buy_fill * config.backtest.fee_rate
    lump_equity = pd.Series(buy_quantity * rows["close"].to_numpy(), index=times)
    final_sell = conservative_sell_fill(
        float(rows["close"].iloc[-1]), config.backtest.slippage_rate, trading_rules
    )
    final_fee = buy_quantity * final_sell * config.backtest.fee_rate
    lump_equity.iloc[-1] = buy_quantity * final_sell - final_fee

    month_keys = times.tz_localize(None).to_period("M")
    month_starts = np.flatnonzero(~month_keys.duplicated())
    allocation = initial / len(month_starts)
    dca_cash = initial
    dca_quantity = 0.0
    dca_fees = 0.0
    dca_values: list[float] = []
    dca_exposure: list[float] = []
    month_start_set = set(month_starts.tolist())
    for position, (_, row) in enumerate(rows.iterrows()):
        if position in month_start_set:
            fill = conservative_buy_fill(
                float(row["open"]), config.backtest.slippage_rate, trading_rules
            )
            quantity = allocation / (fill * (1 + config.backtest.fee_rate))
            fee = quantity * fill * config.backtest.fee_rate
            dca_cash -= quantity * fill + fee
            dca_quantity += quantity
            dca_fees += fee
        dca_values.append(dca_cash + dca_quantity * float(row["close"]))
        dca_exposure.append(1 - dca_cash / initial)
    dca_final_fee = dca_quantity * final_sell * config.backtest.fee_rate
    dca_values[-1] = dca_cash + dca_quantity * final_sell - dca_final_fee
    dca_equity = pd.Series(dca_values, index=times)
    return {
        "buy_and_hold": _benchmark_summary(
            lump_equity,
            initial=initial,
            fees=(buy_fee + final_fee) * config.risk.cny_per_usdt,
            transaction_count=2,
            exposure_percent=100.0,
        ),
        "fixed_total_monthly_dca": _benchmark_summary(
            dca_equity,
            initial=initial,
            fees=(dca_fees + dca_final_fee) * config.risk.cny_per_usdt,
            transaction_count=len(month_starts) + 1,
            exposure_percent=_finite(float(np.mean(dca_exposure) * 100)),
        ),
    }


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
        market_regime_detail=position.market_regime_detail,
        strategy_id=position.strategy_id,
        entry_setup=position.entry_setup,
        candidate_tier=position.candidate_tier,
        strategy_horizon=position.strategy_horizon,
        initial_risk_cny=position.initial_risk_cny,
        realized_r_multiple=(
            pnl_quote * rate / position.initial_risk_cny if position.initial_risk_cny > 0 else 0.0
        ),
    )


def _frames_hash(frames: Mapping[str, pd.DataFrame]) -> str:
    digest = hashlib.sha256()
    for timeframe in ("1d", "4h", "1h"):
        digest.update(timeframe.encode())
        digest.update(frames[timeframe].to_csv(index=True, float_format="%.12g").encode("utf-8"))
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
    source_version = Path(__file__).resolve().parents[2] / "VERSION"
    if source_version.is_file():
        return source_version.read_text(encoding="utf-8").strip()
    try:
        return version("crypto-strategy-analyst")
    except PackageNotFoundError:  # pragma: no cover
        return "0.1.3"


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
    signal_labels: Counter[str] = Counter()
    decision_blockers: Counter[str] = Counter()
    blockers_by_regime: dict[str, Counter[str]] = defaultdict(Counter)
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

        if pending is not None and (position is None or pending.tranche_number == 2):
            raw_open = float(row["open"])
            entry_price = conservative_buy_fill(
                raw_open, config.backtest.slippage_rate, trading_rules
            )
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
                    risk_multiplier = (
                        pending.signal.risk_multiplier
                        if pending.signal.risk_multiplier > 0
                        else 1.0
                    )
                    risk_config = config.risk.model_copy(
                        update={
                            "risk_per_trade": config.risk.risk_per_trade * risk_multiplier,
                            "max_position_fraction": min(
                                config.risk.max_position_fraction,
                                config.strategy.bear_max_deployed_fraction,
                            )
                            if pending.signal.strategy_id == "bear_reversal_accumulation"
                            else config.risk.max_position_fraction,
                        }
                    )
                    suggestion = calculate_position(
                        entry_price=entry_price,
                        stop_price=float(pending.signal.stop_loss),
                        config=risk_config,
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
                    elif pending.tranche_number == 2:
                        if position is None or position.strategy_id != "bear_reversal_accumulation":
                            cancelled_reasons["second_entry_requires_bear_position"] += 1
                            cancelled_entry_count += 1
                        elif position.entry_count >= config.strategy.maximum_bear_entries:
                            cancelled_reasons["maximum_bear_entries_reached"] += 1
                            cancelled_entry_count += 1
                        elif normalized_entry < position.entry_price:
                            cancelled_reasons["second_entry_would_average_down"] += 1
                            cancelled_entry_count += 1
                        else:
                            equity_quote_at_open = cash + position.remaining_quantity * raw_open
                            total_risk = position.initial_risk_cny + suggestion.risk_amount_cny
                            risk_limit = equity_quote_at_open * rate * config.risk.risk_per_trade
                            deployed_after = (
                                position.entry_price * position.original_quantity + notional
                            )
                            if deployed_after > (
                                equity_quote_at_open * config.strategy.bear_max_deployed_fraction
                                + 1e-9
                            ):
                                cancelled_reasons["second_entry_bear_deployment_exceeded"] += 1
                                cancelled_entry_count += 1
                            elif total_risk > risk_limit + 1e-9:
                                cancelled_reasons["second_entry_total_risk_exceeded"] += 1
                                cancelled_entry_count += 1
                            else:
                                cash -= notional + fee
                                total_fees += fee
                                total_slippage += slip
                                total_quantity = position.original_quantity + quantity
                                average_entry = (
                                    position.entry_price * position.original_quantity
                                    + normalized_entry * quantity
                                ) / total_quantity
                                position.entry_price = average_entry
                                position.original_quantity = total_quantity
                                position.remaining_quantity += quantity
                                position.entry_cost += notional + fee
                                position.fees += fee
                                position.slippage += slip
                                position.initial_risk_cny = total_risk
                                position.entry_count = 2
                                executed_entry_count += 1
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
                            target_2=(
                                float(pending.signal.take_profit_2)
                                if pending.signal.take_profit_2 is not None
                                else None
                            ),
                            target_1_done=False,
                            target_2_done=False,
                            entry_cost=notional + fee,
                            exit_proceeds=0.0,
                            fees=fee,
                            slippage=slip,
                            regime=pending.regime,
                            initial_risk_cny=suggestion.risk_amount_cny,
                            strategy_id=pending.signal.strategy_id,
                            risk_multiplier=risk_multiplier,
                            market_regime_detail=pending.signal.market_regime,
                            entry_setup=pending.signal.entry_setup,
                            candidate_tier=pending.signal.candidate_tier,
                            strategy_horizon=pending.signal.strategy_horizon,
                        )
                        executed_entry_count += 1
            else:
                terminal_reasons = {
                    "signal_expired",
                    "open_below_stop",
                    "open_above_target_1",
                    "invalid_target_order",
                    "signal_incomplete",
                }
                if terminal_reasons.intersection(validation.reasons) or (
                    index - pending.created_index >= config.strategy.pending_signal_valid_bars
                ):
                    cancelled_entry_count += 1
                    cancelled_reasons.update(validation.reasons)
                    pending = None
            if validation.is_valid:
                pending = None

        closed_reason: str | None = None
        if position is not None:
            low, high, open_price = float(row["low"]), float(row["high"]), float(row["open"])
            if low <= position.stop_price:
                raw_exit = min(open_price, position.stop_price)
                exit_price = conservative_sell_fill(
                    raw_exit, config.backtest.slippage_rate, trading_rules
                )
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
            elif index > position.entry_index and (
                (
                    position.strategy_horizon == StrategyHorizon.SHORT_TERM
                    and (timestamp - position.entry_time).total_seconds()
                    >= config.strategy.short_term_max_holding_days * 86_400
                    and float(row["close"]) < float(row["ema20"])
                )
                or (
                    position.strategy_horizon == StrategyHorizon.MEDIUM_TERM
                    and (timestamp - position.entry_time).total_seconds()
                    >= config.strategy.medium_term_max_holding_days * 86_400
                    and float(row["close"]) < float(row["ema50"])
                )
                or (
                    position.strategy_horizon == StrategyHorizon.LONG_TERM
                    and (timestamp - position.entry_time).total_seconds()
                    >= config.strategy.long_term_max_holding_days * 86_400
                    and float(row["close"]) < float(row["ema50"])
                )
            ):
                raw_exit = float(row["close"])
                exit_price = conservative_sell_fill(
                    raw_exit, config.backtest.slippage_rate, trading_rules
                )
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
                closed_reason = f"{position.strategy_horizon.value}_time_exit"
            elif index > position.entry_index:
                if not position.target_1_done and high >= position.target_1:
                    quantity = min(position.original_quantity * 0.30, position.remaining_quantity)
                    exit_price = conservative_sell_fill(
                        position.target_1, config.backtest.slippage_rate, trading_rules
                    )
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
                    and position.target_2 is not None
                    and high >= position.target_2
                ):
                    quantity = min(position.original_quantity * 0.30, position.remaining_quantity)
                    exit_price = conservative_sell_fill(
                        position.target_2, config.backtest.slippage_rate, trading_rules
                    )
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
                risk_state = _record_daily_realized_result(
                    risk_state,
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

        # A plan may survive one missed open, but not an intrabar stop/TP1
        # breach or a change to an incompatible market regime.
        if pending is not None and (position is None or pending.tranche_number == 2):
            invalidated: list[str] = []
            if float(row["low"]) <= float(pending.signal.stop_loss):
                invalidated.append("pending_price_crossed_stop")
            if float(row["high"]) >= float(pending.signal.take_profit_1):
                invalidated.append("pending_price_crossed_target_1")
            if (
                not invalidated
                and index - pending.created_index < config.strategy.pending_signal_valid_bars
            ):
                pending_evaluation = evaluate_setup_at_time(
                    prepared,
                    config,
                    requested_at=close_time.to_pydatetime(),
                    risk_state=risk_state,
                    data_is_complete=True,
                )
                if pending_evaluation.regime.selected_strategy != pending.signal.strategy_id:
                    invalidated.append("pending_market_regime_worsened")
            if invalidated:
                cancelled_entry_count += 1
                cancelled_reasons.update(invalidated)
                pending = None

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
            signal_labels[decision.label.value] += 1
            if (
                decision.label in {SignalLabel.BUY_CANDIDATE, SignalLabel.STRONG_BUY_CANDIDATE}
                and decision.stop_loss is not None
                and decision.take_profit_1 is not None
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
                decision_blockers.update(decision.blockers or ["score_below_candidate"])
                blockers_by_regime[evaluation.regime.regime.value].update(
                    decision.blockers or ["score_below_candidate"]
                )
        elif (
            position is not None
            and pending is None
            and position.strategy_id == "bear_reversal_accumulation"
            and position.entry_count < config.strategy.maximum_bear_entries
            and replay_index < len(replay_positions) - 1
        ):
            evaluation = evaluate_setup_at_time(
                prepared,
                config,
                requested_at=close_time.to_pydatetime(),
                risk_state=risk_state,
                data_is_complete=True,
            )
            decision = evaluation.decision
            if (
                decision.label in {SignalLabel.BUY_CANDIDATE, SignalLabel.STRONG_BUY_CANDIDATE}
                and decision.strategy_id == "bear_reversal_accumulation"
                and decision.strong_confirmation_count >= 1
                and decision.planned_entry_price is not None
                and decision.planned_entry_price >= position.entry_price
                and decision.take_profit_1 is not None
            ):
                second_signal = replace(
                    decision,
                    stop_loss=position.stop_price,
                    risk_multiplier=config.strategy.bear_first_risk_multiplier,
                )
                generated_signal_count += 1
                pending = _PendingEntry(
                    signal=second_signal,
                    atr=float(evaluation.frames["4h"]["atr14"].iloc[-1]),
                    created_index=index,
                    regime=evaluation.trends["1d"],
                    tranche_number=2,
                )

    if position is not None:
        timestamp = pd.Timestamp(four_hour.index[replay_positions[-1]])
        row = four_hour.iloc[replay_positions[-1]]
        raw_exit = float(row["close"])
        exit_price = conservative_sell_fill(raw_exit, config.backtest.slippage_rate, trading_rules)
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
                exit_reason="forced_end_of_test",
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
    regime_results = {
        regime.value: _finite(
            sum(trade.pnl for trade in trades if trade.market_regime_detail == regime) / initial_cny
        )
        for regime in MarketRegime
    }
    strategy_results = {
        strategy_id: _finite(
            sum(trade.pnl for trade in trades if trade.strategy_id == strategy_id) / initial_cny
        )
        for strategy_id in sorted({trade.strategy_id for trade in trades})
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
        account_currency=config.risk.account_currency,
        config={
            "market": config.market.model_dump(mode="json"),
            "risk": config.risk.model_dump(mode="json"),
            "strategy": config.strategy.model_dump(mode="json"),
            "backtest": config.backtest.model_dump(mode="json"),
            "random_seed": config.strategy.random_seed,
            "parameter_optimization": False,
            "strategy_evaluator": "evaluate_setup_at_time",
            "timeframes": ["1d", "4h", "1h"],
        },
        research_protocol=ResearchProtocol(
            strategy_version=_package_version(),
            parameter_set_id=_strategy_config_hash(config),
        ),
        metrics=metrics,
        chronological_holdout_split=_time_split_results(equity_series, config),
        rolling_window_results=_rolling_window_results(equity_series),
        yearly_results={str(index.year): _finite(value) for index, value in yearly.items()},
        market_phase_results=phase_results,
        market_regime_results=regime_results,
        strategy_results=strategy_results,
        benchmarks=_benchmarks(four_hour, replay_positions, config, trading_rules),
        generated_signal_count=generated_signal_count,
        executed_entry_count=executed_entry_count,
        cancelled_entry_count=cancelled_entry_count,
        cancelled_entry_reasons=dict(sorted(cancelled_reasons.items())),
        signal_label_counts=dict(sorted(signal_labels.items())),
        decision_blocker_counts=dict(sorted(decision_blockers.items())),
        decision_blocker_counts_by_regime={
            regime: dict(sorted(counts.items()))
            for regime, counts in sorted(blockers_by_regime.items())
        },
        cost_sensitivity={},
        insufficient_sample_warning=insufficient_warning,
        trades=trades,
        warnings=[
            "固定 BTC/ETH 样本不能代表全市场，仍存在样本选择限制。",
            "每次评估只纳入该时刻已经收盘的日线、4 小时线和 1 小时线。",
            "同一根 K 线同时触发止损和目标时按止损优先；入场 K 线不执行止盈。",
            "训练/验证/测试为预先声明的固定时间切分，不是 walk-forward，且没有自动参数优化。",
            *(
                ["集中度警告：最佳单笔交易贡献超过总净利润的 35%。"]
                if metrics.best_trade_profit_contribution > 0.35
                else []
            ),
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
