"""Command-line interface for analysis and reproducible backtests."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import analyze_symbol
from .backtest import run_backtest
from .config import AppConfig, load_config
from .data import BinancePublicClient, drop_incomplete_last_bar, validate_market_data
from .errors import CryptoStrategyError
from .indicators import add_indicators
from .levels import detect_zones
from .logging_utils import configure_logging
from .report import find_latest, save_analysis, save_backtest
from .risk import RiskStateStore, calculate_position, risk_status
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
    backtest.add_argument("--symbol", required=True)
    backtest.add_argument("--start", default="2021-01-01")
    backtest.add_argument("--end")
    backtest.add_argument("--limit", type=int)
    backtest.add_argument("--output-dir")
    _add_common(backtest)

    fetch = subparsers.add_parser("fetch", help="Fetch public completed klines")
    fetch.add_argument("--symbol", required=True)
    fetch.add_argument("--interval", choices=["1h", "4h", "1d"], required=True)
    fetch.add_argument("--limit", type=int, default=500)
    fetch.add_argument("--start")
    fetch.add_argument("--end")
    fetch.add_argument("--output", required=True)
    _add_common(fetch)

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
    record_trade.add_argument("--pnl-cny", type=float, required=True)
    record_trade.add_argument("--stopped-out", action="store_true")
    _add_risk_state(record_trade)

    reset_daily = risk_commands.add_parser(
        "reset-daily",
        help="Manually clear only today's counters",
    )
    _add_risk_state(reset_daily)

    latest = subparsers.add_parser("latest", help="Print the latest saved Markdown report path")
    latest.add_argument("--output-dir", default="outputs")
    latest.add_argument("--symbol")
    return parser


def _config(args: argparse.Namespace) -> AppConfig:
    return load_config(getattr(args, "config", None))


def execute(args: argparse.Namespace) -> int:
    if args.command == "latest":
        print(find_latest(args.output_dir, args.symbol))
        return 0

    config = _config(args)
    configure_logging(config.output.log_dir)
    output_dir = getattr(args, "output_dir", None) or config.output.output_dir
    current_date = datetime.now(UTC).date()

    if args.command == "risk":
        store = RiskStateStore(args.risk_state or config.output.risk_state_file)
        if args.risk_command == "initialize":
            state = store.initialize(
                current_date=current_date,
                equity_cny=args.equity_cny,
                force=args.force,
            )
            payload = risk_status(config.risk, state)
            payload["risk_state"] = str(store.path)
            if args.force:
                payload["warning"] = "已强制覆盖原风险状态；历史风控数据已被替换。"
            _json_print(payload)
            return 0
        if args.risk_command == "status":
            state = store.load_existing(
                current_date=current_date,
                initial_equity_cny=config.risk.account_equity_cny,
            )
            _json_print(risk_status(config.risk, state))
            return 0
        if args.risk_command == "update-equity":
            state = store.update_equity(
                current_date=current_date,
                initial_equity_cny=config.risk.account_equity_cny,
                equity_cny=args.equity_cny,
            )
            payload = risk_status(config.risk, state)
            payload["operation"] = "update_equity"
            _json_print(payload)
            return 0
        if args.risk_command == "record-trade":
            state = store.record_trade(
                current_date=current_date,
                initial_equity_cny=config.risk.account_equity_cny,
                pnl_cny=args.pnl_cny,
                stopped_out=args.stopped_out,
            )
            payload = risk_status(config.risk, state)
            payload["operation"] = "record_trade"
            payload["equity_rule"] = "new_equity = previous_equity + pnl_cny"
            _json_print(payload)
            return 0
        if args.risk_command == "reset-daily":
            state = store.reset_daily(
                current_date=current_date,
                initial_equity_cny=config.risk.account_equity_cny,
            )
            payload = risk_status(config.risk, state)
            payload["warning"] = "已人工重置每日风控计数；仅用于纠错和测试。"
            _json_print(payload)
            return 0

    client = BinancePublicClient(config.market)

    if args.command == "analyze":
        risk_store = RiskStateStore(args.risk_state or config.output.risk_state_file)
        risk_state, initialized = risk_store.load_or_initialize(
            current_date=current_date,
            initial_equity_cny=config.risk.account_equity_cny,
        )
        report = analyze_symbol(
            args.symbol,
            config,
            client=client,
            risk_state=risk_state,
            risk_state_initialized=initialized,
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
                "json_report": str(json_path),
                "markdown_report": str(markdown_path),
            }
        )
        return 0
    if args.command == "compare":
        risk_store = RiskStateStore(args.risk_state or config.output.risk_state_file)
        risk_state, initialized = risk_store.load_or_initialize(
            current_date=current_date,
            initial_equity_cny=config.risk.account_equity_cny,
        )
        rows = []
        for symbol in args.symbols:
            report = analyze_symbol(
                symbol,
                config,
                client=client,
                risk_state=risk_state,
                risk_state_initialized=initialized,
            )
            paths = save_analysis(report, output_dir)
            rows.append(
                {
                    "symbol": report.symbol,
                    "signal": report.signal,
                    "score": report.signal_score,
                    "daily_trend": report.daily_trend,
                    "report": str(paths[1]),
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
        frames: dict[str, pd.DataFrame] = {}
        warmup_days = {"1d": 365, "4h": 60, "1h": 15}
        for timeframe in ("1d", "4h", "1h"):
            fetch_start = None
            if args.start:
                requested_start = pd.Timestamp(args.start)
                requested_start = (
                    requested_start.tz_localize("UTC")
                    if requested_start.tzinfo is None
                    else requested_start.tz_convert("UTC")
                )
                fetch_start = requested_start - pd.Timedelta(days=warmup_days[timeframe])
            frame = client.fetch_klines(
                args.symbol,
                timeframe,
                start=fetch_start.to_pydatetime() if fetch_start is not None else None,
                end=args.end,
                limit=args.limit,
            )
            frame = drop_incomplete_last_bar(frame, timeframe)
            quality = validate_market_data(frame, timeframe, minimum_bars=210)
            if quality.grade.value == "invalid" or quality.gap_count:
                raise CryptoStrategyError(
                    f"backtest {timeframe} data failed quality gate: {quality.model_dump()}"
                )
            frames[timeframe] = frame
        result = run_backtest(frames, args.symbol, config, start=args.start, end=args.end)
        path = save_backtest(result, output_dir)
        _json_print({"result": str(path), "metrics": result.metrics.model_dump()})
        return 0
    if args.command == "fetch":
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
    if args.command == "position":
        _json_print(
            calculate_position(
                entry_price=args.entry, stop_price=args.stop, config=config.risk
            ).model_dump()
        )
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
