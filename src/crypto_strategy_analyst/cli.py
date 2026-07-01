"""Command-line interface for analysis and reproducible backtests."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .account import (
    AccountState,
    AccountStateStore,
    CancelPendingPlan,
    CreatePendingPlan,
    PendingPlan,
    RecordExternalResult,
    ResetDailyRisk,
    UpdateExternalEquity,
)
from .analysis import analyze_symbol
from .backtest import run_backtest
from .config import AppConfig, load_config
from .data import BinancePublicClient, drop_incomplete_last_bar, validate_market_data
from .dataset import fetch_dataset, load_dataset
from .errors import CryptoStrategyError
from .indicators import add_indicators
from .levels import detect_zones
from .logging_utils import configure_logging
from .models import AnalysisReport, SignalLabel
from .report import find_latest, save_analysis, save_backtest
from .risk import calculate_position, risk_status
from .structure import classify_trend, detect_confirmed_swings


def _frame_from_csv(path: str) -> pd.DataFrame:
    frame = pd.read_csv(Path(path).expanduser().resolve())
    timestamp_column = "timestamp" if "timestamp" in frame.columns else "open_time"
    if timestamp_column not in frame.columns:
        raise ValueError("CSV must contain timestamp or open_time")
    frame[timestamp_column] = pd.to_datetime(frame[timestamp_column], utc=True)
    return frame.set_index(timestamp_column).sort_index()


def _json_print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False))


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="YAML override file")


def _add_risk_state(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--risk-state", help="Persistent risk-state JSON path")
    _add_common(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crypto-strategy-analyst")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Run full multi-timeframe analysis")
    analyze.add_argument("--symbol", required=True)
    analyze.add_argument("--output-dir")
    analyze.add_argument("--risk-state", help="Persistent risk-state JSON path")
    _add_common(analyze)

    compare = subparsers.add_parser(
        "compare", help="Compare supported pairs by deterministic score"
    )
    compare.add_argument("--symbols", nargs="+", default=["BTC/USDT", "ETH/USDT"])
    compare.add_argument("--output-dir")
    compare.add_argument("--risk-state", help="Persistent risk-state JSON path")
    _add_common(compare)

    backtest = subparsers.add_parser("backtest", help="Run strict time-forward 4h backtest")
    backtest.add_argument("--symbol")
    backtest.add_argument("--dataset-dir")
    backtest.add_argument("--start")
    backtest.add_argument("--end")
    backtest.add_argument("--limit", type=int)
    backtest.add_argument("--output-dir")
    _add_common(backtest)

    research = subparsers.add_parser("research", help="Run bounded strategy research workflows")
    research_commands = research.add_subparsers(dest="research_command", required=True)
    diagnose = research_commands.add_parser(
        "diagnose", help="Report candidate blockers and next-open cancellations"
    )
    diagnose.add_argument("--dataset-dir", required=True)
    diagnose.add_argument("--output-dir", required=True)
    diagnose.add_argument("--start", default="2019-01-01")
    diagnose.add_argument("--end")
    _add_common(diagnose)
    compare_strategies = research_commands.add_parser(
        "compare-strategies", help="Compare the four preregistered strategy versions"
    )
    compare_strategies.add_argument("--dataset-dir", required=True)
    compare_strategies.add_argument("--output-dir", required=True)
    compare_strategies.add_argument("--start", default="2019-01-01")
    compare_strategies.add_argument("--end")
    compare_strategies.add_argument(
        "--with-cost-sensitivity",
        action="store_true",
        help="Run the four fixed cost scenarios for every version",
    )
    _add_common(compare_strategies)

    fetch = subparsers.add_parser("fetch", help="Fetch public completed klines")
    fetch.add_argument("--symbol", required=True)
    fetch.add_argument("--interval", choices=["1h", "4h", "1d"], required=True)
    fetch.add_argument("--limit", type=int, default=500)
    fetch.add_argument("--start")
    fetch.add_argument("--end")
    fetch.add_argument("--output", required=True)
    _add_common(fetch)

    fetch_dataset_parser = subparsers.add_parser(
        "fetch-dataset", help="Fetch a checksummed offline three-timeframe dataset"
    )
    fetch_dataset_parser.add_argument("--symbol", required=True)
    fetch_dataset_parser.add_argument("--start", required=True)
    fetch_dataset_parser.add_argument("--end", required=True)
    fetch_dataset_parser.add_argument("--output-dir", required=True)
    _add_common(fetch_dataset_parser)

    indicators = subparsers.add_parser("indicators", help="Calculate indicators from an OHLCV CSV")
    indicators.add_argument("--input", required=True)
    indicators.add_argument("--output", required=True)
    _add_common(indicators)

    structure = subparsers.add_parser("structure", help="Detect confirmed swings from an OHLCV CSV")
    structure.add_argument("--input", required=True)
    structure.add_argument("--timeframe", default="4h")
    _add_common(structure)

    levels = subparsers.add_parser("levels", help="Detect zones from an OHLCV CSV")
    levels.add_argument("--input", required=True)
    levels.add_argument("--timeframe", default="4h")
    _add_common(levels)

    position = subparsers.add_parser("position", help="Calculate risk-sized spot position")
    position.add_argument("--entry", type=float, required=True)
    position.add_argument("--stop", type=float, required=True)
    position.add_argument("--symbol", default="BTC/USDT")
    position.add_argument("--risk-state", help="Persistent risk-state JSON path")
    position.add_argument("--equity-cny", type=float, help="Explicit equity override")
    _add_common(position)

    risk = subparsers.add_parser("risk", help="Manage persistent account risk state")
    risk_commands = risk.add_subparsers(dest="risk_command", required=True)

    risk_status_parser = risk_commands.add_parser("status", help="Show risk state and locks")
    _add_risk_state(risk_status_parser)

    initialize = risk_commands.add_parser("initialize", help="Create the first risk state")
    initialize.add_argument("--equity-cny", type=float, required=True)
    initialize.add_argument("--force", action="store_true")
    _add_risk_state(initialize)

    update_equity = risk_commands.add_parser("update-equity", help="Set current account equity")
    update_equity.add_argument("--equity-cny", type=float, required=True)
    _add_risk_state(update_equity)

    record_trade = risk_commands.add_parser("record-trade", help="Record realized trade PnL")
    record_trade.add_argument("--trade-id", required=True)
    record_trade.add_argument("--pnl-cny", type=float, required=True)
    record_trade.add_argument("--stopped-out", action="store_true")
    _add_risk_state(record_trade)

    reset_daily = risk_commands.add_parser(
        "reset-daily",
        help="Manually clear only today's counters",
    )
    _add_risk_state(reset_daily)

    history = risk_commands.add_parser("history", help="Show recent risk-state audit events")
    history.add_argument("--limit", type=int, default=20)
    _add_risk_state(history)

    latest = subparsers.add_parser("latest", help="Print the latest saved Markdown report path")
    latest.add_argument("--output-dir", default="outputs")
    latest.add_argument("--symbol")
    return parser


def _config(args: argparse.Namespace) -> AppConfig:
    return load_config(getattr(args, "config", None))


def _risk_store(args: argparse.Namespace, config: AppConfig) -> AccountStateStore:
    custom_state = getattr(args, "risk_state", None)
    if custom_state:
        state_path = Path(custom_state).expanduser().resolve()
        audit_path = state_path.with_name("account-events.jsonl")
    else:
        state_path = Path(config.output.account_state_file)
        audit_path = Path(config.output.account_events_file)
    return AccountStateStore(
        state_path,
        events_path=audit_path,
        cny_per_usdt=config.risk.cny_per_usdt,
    )


def _legacy_risk(state: AccountState, config: AppConfig):
    return state.as_legacy_risk_state(cny_per_usdt=config.risk.cny_per_usdt)


def _roll_account_date(
    store: AccountStateStore,
    state: AccountState,
    current_date,
) -> AccountState:
    if current_date <= state.risk.date:
        return state
    updated, _ = store.execute(
        ResetDailyRisk(
            command_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            expected_state_version=state.state_version,
            new_date=current_date,
        )
    )
    return updated


def _persist_pending_plan(
    store: AccountStateStore,
    state: AccountState,
    report: AnalysisReport,
    config: AppConfig,
) -> tuple[AccountState, str | None]:
    now = datetime.now(UTC)
    for plan in list(state.pending_plans):
        if plan.symbol == report.symbol and plan.expires_at < now:
            state, _ = store.execute(
                CancelPendingPlan(
                    command_id=str(uuid.uuid4()),
                    timestamp=now,
                    expected_state_version=state.state_version,
                    plan_id=plan.plan_id,
                    reason="signal_expired",
                )
            )
    existing = next((plan for plan in state.pending_plans if plan.symbol == report.symbol), None)
    if existing:
        return state, existing.plan_id
    if report.signal not in {
        SignalLabel.BUY_CANDIDATE,
        SignalLabel.STRONG_BUY_CANDIDATE,
    }:
        return state, None
    if (
        isinstance(report.entry_zone, str)
        or isinstance(report.stop_loss, str)
        or isinstance(report.take_profit_1, str)
    ):
        return state, None
    planned_entry = (
        float(report.planned_entry_price)
        if not isinstance(report.planned_entry_price, str)
        else min(
            max(report.current_price, report.entry_zone.lower_price),
            report.entry_zone.upper_price,
        )
    )
    plan_id = f"{report.symbol.replace('/', '')}-{report.evaluation_time:%Y%m%dT%H%M%SZ}"
    plan = PendingPlan(
        plan_id=plan_id,
        symbol=report.symbol,
        created_at=report.evaluation_time,
        expires_at=report.evaluation_time
        + timedelta(hours=4 * config.strategy.pending_signal_valid_bars),
        entry_lower=report.entry_zone.lower_price,
        entry_upper=report.entry_zone.upper_price,
        planned_entry=planned_entry,
        stop_price=report.stop_loss,
        take_profit_1=report.take_profit_1,
        take_profit_2=(None if isinstance(report.take_profit_2, str) else report.take_profit_2),
        initial_risk_quote=(
            config.risk.risk_per_trade * report.risk_multiplier * state.risk.current_equity
        ),
        strategy_id=report.selected_strategy,
        strategy_horizon=report.strategy_horizon,
        risk_multiplier=max(report.risk_multiplier, 0.01),
    )
    updated, _ = store.execute(
        CreatePendingPlan(
            command_id=str(uuid.uuid4()),
            timestamp=now,
            expected_state_version=state.state_version,
            plan=plan,
        )
    )
    return updated, plan_id


def execute(args: argparse.Namespace) -> int:
    if args.command == "latest":
        print(find_latest(args.output_dir, args.symbol))
        return 0

    config = _config(args)
    configure_logging(config.output.log_dir)
    output_dir = getattr(args, "output_dir", None) or config.output.output_dir
    current_date = datetime.now(UTC).date()

    if args.command == "research":
        snapshot = load_dataset(args.dataset_dir)
        directory = Path(args.output_dir).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        if args.research_command == "diagnose":
            result = run_backtest(
                snapshot.frames,
                snapshot.symbol,
                config,
                start=args.start,
                end=args.end,
                trading_rules=snapshot.trading_rules,
                dataset_hash=snapshot.dataset_hash,
                include_cost_sensitivity=False,
            )
            conversion = (
                result.executed_entry_count / result.generated_signal_count
                if result.generated_signal_count
                else 0.0
            )
            payload = {
                "strategy_variant": config.strategy.strategy_variant,
                "symbol": snapshot.symbol,
                "dataset_hash": snapshot.dataset_hash,
                "generated_candidates": result.generated_signal_count,
                "cancelled_at_next_open": result.cancelled_entry_count,
                "executed_entries": result.executed_entry_count,
                "candidate_to_entry_conversion": conversion,
                "signal_label_counts": result.signal_label_counts,
                "blocker_counts": result.decision_blocker_counts,
                "blocker_counts_by_regime": result.decision_blocker_counts_by_regime,
                "cancellation_reasons": result.cancelled_entry_reasons,
                "metrics": result.metrics.model_dump(mode="json"),
                "diagnostic_interpretation": {
                    "most_frequent_blockers": sorted(
                        result.decision_blocker_counts.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )[:10],
                    "known_overlapping_families": [
                        ["fewer_than_two_confirmations", "score_below_candidate"],
                        [
                            "no_key_resistance_for_targets",
                            "reward_risk_below_minimum",
                            "second_target_unavailable_before_resistance",
                        ],
                    ],
                    "safety_critical_blockers": [
                        "required_market_data_incomplete",
                        "daily_stop_count_reached",
                        "daily_loss_limit_reached",
                        "maximum_drawdown_protection_active",
                        "open_below_stop",
                    ],
                    "frequency_only_without_oos_benefit": "requires_controlled_ablation",
                },
            }
            path = directory / f"diagnosis-{snapshot.symbol.replace('/', '-')}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            _json_print({"diagnosis": str(path), **payload})
            return 0
        variants = (
            "baseline_v0_1_2",
            "relaxed_trend",
            "relaxed_trend_plus_breakout",
            "relaxed_trend_plus_bear_reversal",
        )
        results = []
        for variant in variants:
            strategy = config.strategy.model_copy(update={"strategy_variant": variant})
            variant_config = config.model_copy(update={"strategy": strategy})
            result = run_backtest(
                snapshot.frames,
                snapshot.symbol,
                variant_config,
                start=args.start,
                end=args.end,
                trading_rules=snapshot.trading_rules,
                dataset_hash=snapshot.dataset_hash,
                include_cost_sensitivity=args.with_cost_sensitivity,
            )
            result_path = directory / f"{snapshot.symbol.replace('/', '-')}-{variant}.json"
            result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
            results.append(
                {
                    "strategy_variant": variant,
                    "result": str(result_path),
                    "metrics": result.metrics.model_dump(mode="json"),
                    "generated_candidates": result.generated_signal_count,
                    "executed_entries": result.executed_entry_count,
                    "cancelled_entries": result.cancelled_entry_count,
                    "chronological_holdout_split": result.chronological_holdout_split,
                    "cost_sensitivity": {
                        key: value.model_dump(mode="json")
                        for key, value in result.cost_sensitivity.items()
                    },
                    "market_regime_results": result.market_regime_results,
                    "strategy_results": result.strategy_results,
                    "rolling_window_results": result.rolling_window_results,
                    "benchmarks": {
                        key: value.model_dump(mode="json")
                        for key, value in result.benchmarks.items()
                    },
                }
            )
        comparison = {
            "symbol": snapshot.symbol,
            "dataset_hash": snapshot.dataset_hash,
            "selection_rule": (
                "positive_oos_then_drawdown_then_cost_stability_then_parameter_stability_then_return"
            ),
            "parameter_search_performed": False,
            "number_of_strategy_versions_evaluated": len(results),
            "results": results,
        }
        comparison_path = directory / f"comparison-{snapshot.symbol.replace('/', '-')}.json"
        comparison_path.write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _json_print({"comparison": str(comparison_path), "results": results})
        return 0

    if args.command == "risk":
        store = _risk_store(args, config)
        if args.risk_command == "initialize":
            state = store.initialize(
                timestamp=datetime.now(UTC),
                initial_cash=args.equity_cny / config.risk.cny_per_usdt,
                force=args.force,
            )
            payload = risk_status(config.risk, _legacy_risk(state, config))
            payload["risk_state"] = str(store.path)
            if args.force:
                payload["warning"] = "已强制覆盖原风险状态；历史风控数据已被替换。"
            _json_print(payload)
            return 0
        if args.risk_command == "status":
            state = _roll_account_date(store, store.load(), current_date)
            payload = risk_status(config.risk, _legacy_risk(state, config))
            payload.update(
                {
                    "account_schema_version": state.schema_version,
                    "account_state_version": state.state_version,
                    "available_cash_usdt": state.portfolio.available_cash,
                    "reserved_cash_usdt": state.portfolio.reserved_cash,
                    "aggregate_open_risk_usdt": state.risk.aggregate_open_risk,
                    "open_positions": sorted(state.portfolio.positions),
                    "pending_plan_count": len(state.pending_plans),
                    "audit_consistent": store.verify_consistency(),
                }
            )
            _json_print(payload)
            return 0
        if args.risk_command == "history":
            _json_print(
                {
                    "risk_state": str(store.path),
                    "audit_log": str(store.audit_path),
                    "events": store.history(limit=args.limit),
                }
            )
            return 0
        if args.risk_command == "update-equity":
            current = _roll_account_date(store, store.load(), current_date)
            state, _ = store.execute(
                UpdateExternalEquity(
                    command_id=str(uuid.uuid4()),
                    timestamp=datetime.now(UTC),
                    expected_state_version=current.state_version,
                    current_equity=args.equity_cny / config.risk.cny_per_usdt,
                )
            )
            payload = risk_status(config.risk, _legacy_risk(state, config))
            payload["operation"] = "update_equity"
            _json_print(payload)
            return 0
        if args.risk_command == "record-trade":
            current = _roll_account_date(store, store.load(), current_date)
            state, _ = store.execute(
                RecordExternalResult(
                    command_id=args.trade_id,
                    timestamp=datetime.now(UTC),
                    expected_state_version=current.state_version,
                    pnl=args.pnl_cny / config.risk.cny_per_usdt,
                    stopped_out=args.stopped_out,
                )
            )
            payload = risk_status(config.risk, _legacy_risk(state, config))
            payload["operation"] = "record_trade"
            payload["equity_rule"] = "new_equity = previous_equity + pnl_cny"
            _json_print(payload)
            return 0
        if args.risk_command == "reset-daily":
            current = store.load()
            state, _ = store.execute(
                ResetDailyRisk(
                    command_id=str(uuid.uuid4()),
                    timestamp=datetime.now(UTC),
                    expected_state_version=current.state_version,
                    new_date=current_date,
                )
            )
            payload = risk_status(config.risk, _legacy_risk(state, config))
            payload["warning"] = "已人工重置每日风控计数；仅用于纠错和测试。"
            _json_print(payload)
            return 0

    if args.command == "analyze":
        client = BinancePublicClient(config.market)
        risk_store = _risk_store(args, config)
        account_state, initialized = risk_store.load_or_initialize(
            timestamp=datetime.now(UTC),
            initial_cash=config.risk.account_equity_cny / config.risk.cny_per_usdt,
        )
        account_state = _roll_account_date(risk_store, account_state, current_date)
        risk_state = _legacy_risk(account_state, config)
        report = analyze_symbol(
            args.symbol,
            config,
            client=client,
            risk_state=risk_state,
            risk_state_initialized=initialized,
            account_state=account_state,
        )
        account_state, pending_plan_id = _persist_pending_plan(
            risk_store, account_state, report, config
        )
        json_path, markdown_path = save_analysis(report, output_dir)
        _json_print(
            {
                "signal": report.signal,
                "score": report.signal_score,
                "requested_at": report.requested_at,
                "evaluation_time": report.evaluation_time,
                "account_equity_cny": report.account_equity_cny,
                "risk_state_initialized": initialized,
                "data_freshness": {
                    timeframe: item.model_dump(mode="json")
                    for timeframe, item in report.data_freshness.items()
                },
                "freshness_retry_attempts": report.freshness_retry_attempts,
                "trading_rules_status": report.trading_rules_status,
                "pending_plan_id": pending_plan_id,
                "account_state_version": account_state.state_version,
                "json_report": str(json_path),
                "markdown_report": str(markdown_path),
            }
        )
        return 0
    if args.command == "compare":
        client = BinancePublicClient(config.market)
        risk_store = _risk_store(args, config)
        account_state, initialized = risk_store.load_or_initialize(
            timestamp=datetime.now(UTC),
            initial_cash=config.risk.account_equity_cny / config.risk.cny_per_usdt,
        )
        account_state = _roll_account_date(risk_store, account_state, current_date)
        risk_state = _legacy_risk(account_state, config)
        rows = []
        for symbol in args.symbols:
            report = analyze_symbol(
                symbol,
                config,
                client=client,
                risk_state=risk_state,
                risk_state_initialized=initialized,
                account_state=account_state,
            )
            account_state, pending_plan_id = _persist_pending_plan(
                risk_store, account_state, report, config
            )
            paths = save_analysis(report, output_dir)
            rows.append(
                {
                    "symbol": report.symbol,
                    "signal": report.signal,
                    "score": report.signal_score,
                    "daily_trend": report.daily_trend,
                    "report": str(paths[1]),
                    "pending_plan_id": pending_plan_id,
                }
            )
        rows.sort(key=lambda row: float(row["score"]), reverse=True)
        _json_print(
            {
                "ranking": rows,
                "account_equity_cny": risk_state.current_equity_cny,
                "risk_state_initialized": initialized,
                "note": "评分只是确定性候选排序，不是收益预测。",
            }
        )
        return 0
    if args.command == "backtest":
        if args.dataset_dir:
            snapshot = load_dataset(args.dataset_dir)
            if args.symbol and args.symbol.upper().replace("-", "/") != snapshot.symbol:
                raise ValueError("--symbol does not match the offline dataset manifest")
            frames = snapshot.frames
            symbol = snapshot.symbol
            trading_rules = snapshot.trading_rules
            dataset_hash = snapshot.dataset_hash
        else:
            if not args.symbol:
                raise ValueError("--symbol is required unless --dataset-dir is provided")
            client = BinancePublicClient(config.market)
            symbol = args.symbol
            trading_rules = client.fetch_symbol_trading_rules(symbol)
            dataset_hash = None
            frames = {}
            online_start = args.start or "2021-01-01"
            warmup_days = {"1d": 365, "4h": 60, "1h": 15}
            for timeframe in ("1d", "4h", "1h"):
                requested_start = pd.Timestamp(online_start)
                requested_start = (
                    requested_start.tz_localize("UTC")
                    if requested_start.tzinfo is None
                    else requested_start.tz_convert("UTC")
                )
                fetch_start = requested_start - pd.Timedelta(days=warmup_days[timeframe])
                frame = client.fetch_klines(
                    symbol,
                    timeframe,
                    start=fetch_start.to_pydatetime(),
                    end=args.end,
                    limit=args.limit,
                )
                frame = drop_incomplete_last_bar(frame, timeframe)
                quality = validate_market_data(frame, timeframe, minimum_bars=210)
                if quality.grade.value == "invalid":
                    raise CryptoStrategyError(
                        f"backtest {timeframe} data failed quality gate: {quality.model_dump()}"
                    )
                frames[timeframe] = frame
        result = run_backtest(
            frames,
            symbol,
            config,
            start=args.start,
            end=args.end,
            trading_rules=trading_rules,
            dataset_hash=dataset_hash,
            include_cost_sensitivity=True,
        )
        path = save_backtest(result, output_dir)
        _json_print({"result": str(path), "metrics": result.metrics.model_dump()})
        return 0
    if args.command == "fetch":
        client = BinancePublicClient(config.market)
        frame = client.fetch_klines(
            args.symbol,
            args.interval,
            start=args.start,
            end=args.end,
            limit=args.limit,
        )
        frame = drop_incomplete_last_bar(frame, args.interval)
        quality = validate_market_data(
            frame, args.interval, minimum_bars=min(210, max(2, len(frame)))
        )
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index_label="timestamp")
        _json_print({"output": str(output), "quality": quality.model_dump(mode="json")})
        return 0
    if args.command == "fetch-dataset":
        client = BinancePublicClient(config.market)
        manifest_path = fetch_dataset(
            client,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            output_dir=args.output_dir,
        )
        _json_print({"manifest": str(manifest_path)})
        return 0
    if args.command == "position":
        warning = None
        if args.equity_cny is not None:
            equity_cny = args.equity_cny
            equity_source = "explicit_override"
            warning = "显式 --equity-cny 覆盖了持久化风险状态中的当前权益。"
        else:
            store = _risk_store(args, config)
            account_state = _roll_account_date(store, store.load(), current_date)
            state = _legacy_risk(account_state, config)
            equity_cny = state.current_equity_cny
            equity_source = str(store.path)
        rules = BinancePublicClient(config.market).fetch_symbol_trading_rules(args.symbol)
        suggestion = calculate_position(
            entry_price=args.entry,
            stop_price=args.stop,
            config=config.risk,
            account_equity_cny=equity_cny,
            trading_rules=rules,
        )
        payload = {
            "equity_source": equity_source,
            "account_equity_cny": equity_cny,
            "risk_per_trade": config.risk.risk_per_trade,
            "maximum_loss_cny": suggestion.risk_amount_cny,
            "position_notional_cny": suggestion.position_notional_cny,
            "quantity": suggestion.quantity,
            "trading_rules": rules.model_dump(mode="json"),
        }
        if warning:
            payload["warning"] = warning
        _json_print(payload)
        return 0

    frame = _frame_from_csv(args.input)
    enriched = add_indicators(frame, enable_adx=config.strategy.enable_adx)
    if args.command == "indicators":
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        enriched.replace([np.inf, -np.inf], np.nan).to_csv(output, index_label="timestamp")
        print(output)
        return 0
    swings = detect_confirmed_swings(
        enriched,
        left=config.strategy.swing_left,
        right=config.strategy.swing_right,
    )
    if args.command == "structure":
        _json_print(
            {
                "trend": classify_trend(enriched, swings),
                "swings": [
                    {
                        "timestamp": item.timestamp,
                        "price": item.price,
                        "kind": item.kind,
                        "confirmed_at": item.confirmed_at,
                    }
                    for item in swings
                ],
            }
        )
        return 0
    supports, resistances = detect_zones(
        enriched,
        swings,
        args.timeframe,
        merge_percent=config.strategy.level_merge_percent,
    )
    _json_print(
        {
            "supports": [item.model_dump(mode="json") for item in supports],
            "resistances": [item.model_dump(mode="json") for item in resistances],
        }
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        return execute(parser.parse_args(argv))
    except (CryptoStrategyError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
