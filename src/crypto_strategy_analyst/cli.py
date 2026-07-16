"""Six-command OpenClaw analysis CLI."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backtest import run_backtest
from .config import load_config
from .data_sources import BinanceMarketData, CompositeDataSource
from .data_sources.composite import load_external_context
from .dataset import load_dataset, save_dataset
from .engine import analyze_snapshot
from .models import AnalysisReport, Horizon
from .profiles.registry import profile_for_symbol
from .rendering import report_json, report_markdown
from .research import (
    ablation,
    attribution,
    compare,
    cost_sensitivity,
    diagnose,
    parameter_stability,
    walk_forward,
)
from .technical_snapshot import analyze_technical_snapshot, technical_json, technical_markdown
from .validation import validate_entry

TOP_LEVEL_COMMANDS = (
    "analyze",
    "compare",
    "validate-entry",
    "fetch-dataset",
    "backtest",
    "research",
)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config")
    parser.add_argument("--profile", default="auto")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crypto-strategy-analyst")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze")
    _common(analyze)
    analyze.add_argument("symbol", nargs="?")
    analyze.add_argument("--symbol", dest="symbol_option")
    analyze.add_argument(
        "--horizons",
        nargs="+",
        choices=[item.value for item in Horizon],
        default=[item.value for item in Horizon],
    )
    analyze.add_argument("--dataset")
    analyze.add_argument("--external-data")
    analyze.add_argument("--output-dir")
    analyze.add_argument("--format", choices=("json", "markdown"), default="json")
    analyze.add_argument(
        "--technical-only",
        action="store_true",
        help="return compact EMA/MA/RSI/MACD/ATR analysis without patterns, levels, or auxiliary data",
    )

    compare_parser = commands.add_parser("compare")
    _common(compare_parser)
    compare_parser.add_argument("symbols", nargs="+")
    compare_parser.add_argument("--format", choices=("json", "markdown"), default="json")

    validate = commands.add_parser("validate-entry")
    validate.add_argument("report")
    validate.add_argument("--dataset")
    validate.add_argument("--horizon", choices=[item.value for item in Horizon], default="swing")
    validate.add_argument("--config")

    fetch = commands.add_parser("fetch-dataset")
    fetch.add_argument("symbol")
    fetch.add_argument("output")
    fetch.add_argument("--limit", type=int, default=500)
    fetch.add_argument("--start", help="UTC history start (YYYY-MM-DD or ISO-8601)")
    fetch.add_argument("--end", help="UTC history end (YYYY-MM-DD or ISO-8601)")
    fetch.add_argument("--include-15m", action="store_true")
    fetch.add_argument("--external-data")
    fetch.add_argument("--config")

    backtest = commands.add_parser("backtest")
    _common(backtest)
    backtest.add_argument("dataset")
    backtest.add_argument(
        "--horizons",
        nargs="+",
        choices=[item.value for item in Horizon],
        default=[item.value for item in Horizon],
    )
    backtest.add_argument("--output-dir")

    research = commands.add_parser("research")
    _common(research)
    research_sub = research.add_subparsers(dest="research_command", required=True)
    for name in (
        "diagnose",
        "attribution",
        "ablation",
        "walk-forward",
        "cost-sensitivity",
        "parameter-stability",
        "compare",
    ):
        child = research_sub.add_parser(name)
        child.add_argument("dataset")
    return parser


def _profile_name(requested: str, symbol: str) -> str:
    return profile_for_symbol(symbol).name if requested == "auto" else requested


def _config(args, symbol: str):
    return load_config(args.config, _profile_name(getattr(args, "profile", "auto"), symbol))


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _save_report(report: AnalysisReport, output_dir: str | None, format_name: str) -> None:
    if not output_dir:
        return
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    safe = report.symbol.replace("/", "-")
    suffix = "json" if format_name == "json" else "md"
    content = report_json(report) if format_name == "json" else report_markdown(report)
    (target / f"{safe}-report.{suffix}").write_text(content, encoding="utf-8")


def _live_or_dataset(
    symbol: str,
    dataset: str | None,
    config,
    external: str | None = None,
    technical_only: bool = False,
):
    if config.data.exchange != "binance":
        raise ValueError("only the Binance public market source is implemented")
    snapshot = (
        load_dataset(dataset)
        if dataset
        else (
            BinanceMarketData(timeout=config.data.request_timeout_seconds).indicator_snapshot(
                symbol, config.data.timeframes, config.data.history_limit
            )
            if technical_only
            else CompositeDataSource(timeout=config.data.request_timeout_seconds).snapshot(
                symbol, config.data.timeframes, config.data.history_limit
            )
        )
    )
    if external:
        snapshot = snapshot.model_copy(
            update={"auxiliary": {**snapshot.auxiliary, **load_external_context(external)}}
        )
    return snapshot


def _save_technical_report(
    report: dict[str, Any], output_dir: str | None, format_name: str
) -> None:
    if not output_dir:
        return
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    safe = report["symbol"].replace("/", "-")
    suffix = "json" if format_name == "json" else "md"
    content = technical_json(report) if format_name == "json" else technical_markdown(report)
    (target / f"{safe}-technical.{suffix}").write_text(content, encoding="utf-8")


def _run_research(command: str, snapshot, config, profile: str):
    result = run_backtest(snapshot, config, profile)
    functions = {
        "diagnose": lambda: diagnose(result),
        "attribution": lambda: attribution(result),
        "ablation": lambda: ablation(snapshot, config, profile),
        "walk-forward": lambda: walk_forward(result, config.research.rolling_days),
        "cost-sensitivity": lambda: cost_sensitivity(snapshot, config, profile),
        "parameter-stability": lambda: parameter_stability(snapshot, config, profile),
        "compare": lambda: compare(snapshot, config, profile),
    }
    return functions[command]()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "analyze":
        symbol = args.symbol_option or args.symbol
        if not symbol:
            raise SystemExit("analyze requires a symbol")
        config = _config(args, symbol)
        if args.technical_only and args.external_data:
            raise SystemExit("--external-data is not used with --technical-only")
        if args.technical_only:
            technical = analyze_technical_snapshot(
                _live_or_dataset(symbol, args.dataset, config, technical_only=True), config
            )
            selected = set(args.horizons)
            technical["horizons"] = {
                key: value for key, value in technical["horizons"].items() if key in selected
            }
            output = technical_json(technical) if args.format == "json" else technical_markdown(technical)
            print(output)
            _save_technical_report(technical, args.output_dir or config.output.output_dir, args.format)
            return 0
        report = analyze_snapshot(
            _live_or_dataset(symbol, args.dataset, config, args.external_data), config, args.profile
        )
        selected = {Horizon(value) for value in args.horizons}
        report = report.model_copy(
            update={
                "horizons": {
                    key: value for key, value in report.horizons.items() if key in selected
                }
            }
        )
        output = report_json(report) if args.format == "json" else report_markdown(report)
        print(output)
        _save_report(report, args.output_dir or config.output.output_dir, args.format)
    elif args.command == "compare":
        rows = []
        for symbol in args.symbols:
            try:
                config = _config(args, symbol)
                report = analyze_snapshot(
                    _live_or_dataset(symbol, None, config), config, args.profile
                )
                rows.append(
                    {
                        "symbol": report.symbol,
                        "profile": report.profile,
                        "confidence": report.confidence,
                        "regime": report.market["regime"],
                        "horizons": {
                            key.value: value.status.value for key, value in report.horizons.items()
                        },
                    }
                )
            except Exception as exc:
                rows.append({"symbol": symbol, "status": "failed", "error": type(exc).__name__})
        _emit(sorted(rows, key=lambda item: item.get("confidence", -1), reverse=True))
    elif args.command == "validate-entry":
        report = AnalysisReport.model_validate_json(Path(args.report).read_text(encoding="utf-8"))
        config = load_config(args.config, report.profile)
        snapshot = (
            load_dataset(args.dataset)
            if args.dataset
            else CompositeDataSource(timeout=config.data.request_timeout_seconds).snapshot(
                report.symbol, config.data.timeframes, config.data.history_limit
            )
        )
        _emit(validate_entry(report, snapshot, Horizon(args.horizon)).model_dump(mode="json"))
    elif args.command == "fetch-dataset":
        config = load_config(args.config, profile_for_symbol(args.symbol).name)
        frames = list(config.data.timeframes) + (
            ["15m"] if args.include_15m and "15m" not in config.data.timeframes else []
        )
        source = CompositeDataSource(timeout=config.data.request_timeout_seconds)
        snapshot = (
            source.history(
                args.symbol,
                frames,
                _parse_utc(args.start),
                _parse_utc(args.end) if args.end else None,
            )
            if args.start
            else source.snapshot(args.symbol, frames, args.limit)
        )
        if args.external_data:
            snapshot = snapshot.model_copy(
                update={
                    "auxiliary": {**snapshot.auxiliary, **load_external_context(args.external_data)}
                }
            )
        _emit({"manifest": str(save_dataset(snapshot, args.output)), "symbol": snapshot.symbol})
    elif args.command == "backtest":
        snapshot = load_dataset(args.dataset)
        config = _config(args, snapshot.symbol)
        result = run_backtest(
            snapshot, config, args.profile, [Horizon(value) for value in args.horizons]
        )
        _emit(result.model_dump(mode="json"))
    elif args.command == "research":
        snapshot = load_dataset(args.dataset)
        config = _config(args, snapshot.symbol)
        _emit(_run_research(args.research_command, snapshot, config, args.profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
