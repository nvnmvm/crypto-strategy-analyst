"""Compact OpenClaw-facing command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .backtest import run_backtest
from .config import load_config
from .data_sources import BinancePublicData
from .engine import analyze_snapshot
from .exchange import BinanceAdapter
from .journal import add_entry, read_entries
from .models import MarketSnapshot, OrderDraft
from .portfolio import PaperBroker
from .profiles.registry import profile_for_symbol
from .rendering import report_json, report_markdown

TOP_LEVEL_COMMANDS = (
    "analyze",
    "compare",
    "validate-entry",
    "fetch-dataset",
    "backtest",
    "research",
    "portfolio",
    "journal",
    "exchange",
)


def _base_parser(name: str, subparsers: Any) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name)
    parser.add_argument("--config")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crypto-strategy-analyst")
    subs = parser.add_subparsers(dest="command", required=True)
    analyze = _base_parser("analyze", subs)
    analyze.add_argument("symbol")
    analyze.add_argument("--profile", default="auto")
    analyze.add_argument("--dataset")
    analyze.add_argument("--format", choices=("json", "markdown"), default="json")

    compare = _base_parser("compare", subs)
    compare.add_argument("symbols", nargs="+")
    compare.add_argument("--profile", default="auto")

    validate = _base_parser("validate-entry", subs)
    validate.add_argument("report")
    validate.add_argument("--horizon", choices=("short", "swing", "long"), default="swing")

    fetch = _base_parser("fetch-dataset", subs)
    fetch.add_argument("symbol")
    fetch.add_argument("output")
    fetch.add_argument("--limit", type=int, default=500)
    fetch.add_argument("--include-15m", action="store_true")

    backtest = _base_parser("backtest", subs)
    backtest.add_argument("dataset")
    backtest.add_argument("--profile", default="auto")

    research = _base_parser("research", subs)
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
        research_sub.add_parser(name)

    portfolio = _base_parser("portfolio", subs)
    portfolio_sub = portfolio.add_subparsers(dest="portfolio_command", required=True)
    portfolio_sub.add_parser("show")
    trade = portfolio_sub.add_parser("trade")
    trade.add_argument("symbol")
    trade.add_argument("side", choices=("buy", "sell"))
    trade.add_argument("quantity", type=float)
    trade.add_argument("price", type=float)

    journal = _base_parser("journal", subs)
    journal_sub = journal.add_subparsers(dest="journal_command", required=True)
    journal_sub.add_parser("list")
    journal_sub.add_parser("compare")
    journal_add = journal_sub.add_parser("add")
    journal_add.add_argument("record", help="JSON object")

    exchange = _base_parser("exchange", subs)
    exchange_sub = exchange.add_subparsers(dest="exchange_command", required=True)
    draft = exchange_sub.add_parser("draft")
    draft.add_argument("symbol")
    draft.add_argument("side", choices=("BUY", "SELL"))
    draft.add_argument("quantity", type=float)
    draft.add_argument("reference_price", type=float)
    place = exchange_sub.add_parser("place")
    place.add_argument("draft")
    place.add_argument("confirmation_token")
    status = exchange_sub.add_parser("status")
    status.add_argument("symbol")
    status.add_argument("client_order_id")
    return parser


def _load_snapshot(path: str) -> MarketSnapshot:
    return MarketSnapshot.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _snapshot(symbol: str, dataset: str | None, config: Any) -> MarketSnapshot:
    return (
        _load_snapshot(dataset)
        if dataset
        else BinancePublicData().snapshot(symbol, config.data.timeframes, config.data.history_limit)
    )


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if raw_args and raw_args[0] == "risk":
        print("The v0.1.x risk command was removed; use portfolio or journal in v0.2.0.")
        return 0
    args = build_parser().parse_args(raw_args)
    profile = getattr(args, "profile", "generic")
    config_profile = profile
    if profile == "auto":
        if args.command == "backtest":
            config_profile = profile_for_symbol(_load_snapshot(args.dataset).symbol).name
        elif hasattr(args, "symbol"):
            config_profile = profile_for_symbol(args.symbol).name
        else:
            config_profile = "generic"
    config = load_config(args.config, config_profile)
    if args.command == "fetch-dataset":
        frames = ["1w", "1d", "4h", "1h"] + (["15m"] if args.include_15m else [])
        snapshot = BinancePublicData().snapshot(args.symbol, frames, args.limit)
        Path(args.output).write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        _emit({"saved": args.output, "symbol": snapshot.symbol})
    elif args.command == "analyze":
        report = analyze_snapshot(
            _snapshot(args.symbol, args.dataset, config), config, args.profile
        )
        print(report_markdown(report) if args.format == "markdown" else report_json(report))
    elif args.command == "compare":
        rows = []
        for symbol in args.symbols:
            try:
                symbol_profile = (
                    profile_for_symbol(symbol).name if args.profile == "auto" else args.profile
                )
                symbol_config = load_config(args.config, symbol_profile)
                report = analyze_snapshot(
                    _snapshot(symbol, None, symbol_config), symbol_config, args.profile
                )
                rows.append(
                    {
                        "symbol": symbol,
                        "profile": report.profile,
                        "confidence": report.confidence,
                        "plans": {k.value: v.status.value for k, v in report.plans.items()},
                    }
                )
            except Exception as exc:
                rows.append({"symbol": symbol, "status": "failed", "error": str(exc)})
        _emit(sorted(rows, key=lambda row: row.get("confidence", -1), reverse=True))
    elif args.command == "validate-entry":
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        plan = report["plans"][args.horizon]
        valid = (
            plan["status"] in {"candidate", "entry_validated"}
            and plan.get("stop")
            and plan.get("take_profit_1")
        )
        _emit({"valid": bool(valid), "horizon": args.horizon, "plan": plan})
    elif args.command == "backtest":
        _emit(run_backtest(_load_snapshot(args.dataset), config, args.profile).as_dict())
    elif args.command == "research":
        _emit({"research": args.research_command, "status": "deterministic_no_auto_optimization"})
    elif args.command == "portfolio":
        broker = PaperBroker(config.storage.paper_account_file, config.storage.paper_trades_file)
        account = (
            broker.load()
            if args.portfolio_command == "show"
            else broker.execute(args.symbol, args.side, args.quantity, args.price)
        )
        _emit(account.model_dump(mode="json"))
    elif args.command == "journal":
        if args.journal_command == "add":
            add_entry(config.storage.journal_file, json.loads(args.record))
        entries = read_entries(config.storage.journal_file)
        if args.journal_command == "compare":
            _emit(
                {
                    "trades": len(entries),
                    "realized_pnl": sum(float(item.get("pnl", 0)) for item in entries),
                    "with_plan": sum(bool(item.get("plan_event_id")) for item in entries),
                }
            )
        else:
            _emit(entries)
    elif args.command == "exchange":
        adapter = BinanceAdapter(config)
        if args.exchange_command == "draft":
            order, token = adapter.create_draft(
                args.symbol, args.side, args.quantity, args.reference_price
            )
            _emit(
                {
                    "draft": order.model_dump(mode="json"),
                    "confirmation_token": token,
                    "warning": "token is shown once; user confirmation is required",
                }
            )
        elif args.exchange_command == "place":
            draft = OrderDraft.model_validate_json(Path(args.draft).read_text(encoding="utf-8"))
            result = adapter.place_spot_order(draft, args.confirmation_token)
            record = {"kind": "exchange_order", **result.model_dump(mode="json")}
            add_entry(config.storage.journal_file, record)
            _emit(record)
        else:
            result = adapter.query_order(args.symbol, args.client_order_id)
            _emit(result.model_dump(mode="json") if result else {"status": "not_found"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
