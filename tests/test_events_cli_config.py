import argparse
import ast
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import BaseModel

from crypto_strategy_analyst.cli import TOP_LEVEL_COMMANDS, build_parser
from crypto_strategy_analyst.config import AppConfig, load_config
from crypto_strategy_analyst.engine import analyze_snapshot
from crypto_strategy_analyst.events import make_event, stable_key
from crypto_strategy_analyst.models import Horizon
from crypto_strategy_analyst.rendering import report_json, report_markdown


def test_cli_has_exact_six_commands_and_removed_commands_absent():
    parser = build_parser()
    action = next(item for item in parser._actions if isinstance(item, argparse._SubParsersAction))
    assert tuple(action.choices) == TOP_LEVEL_COMMANDS
    assert not {"exchange", "portfolio", "journal", "risk", "position", "latest"}.intersection(
        action.choices
    )


def test_analyze_supports_position_or_option():
    parser = build_parser()
    assert parser.parse_args(["analyze", "BTC/USDT"]).symbol == "BTC/USDT"
    assert parser.parse_args(["analyze", "--symbol", "ETH/USDT"]).symbol_option == "ETH/USDT"
    assert parser.parse_args(["analyze", "BTC/USDT", "--technical-only"]).technical_only


def test_research_commands_are_complete():
    parser = build_parser()
    args = parser.parse_args(["research", "diagnose", "data/BTC"])
    assert args.research_command == "diagnose"


def test_layered_config_and_extra_rejected(tmp_path: Path):
    path = tmp_path / "local.yaml"
    path.write_text("strategy:\n  candidate_confidence: 77\n", encoding="utf-8")
    config = load_config(path, "sol", {"levels": {"near_atr": 1.1}})
    assert config.profile == "sol"
    assert config.strategy.candidate_confidence == 77
    assert config.strategy.volume_ratio == 1.3
    assert config.levels.near_atr == 1.1
    with pytest.raises(ValueError):
        AppConfig.model_validate({"trading": {"enabled": True}})


def test_btc_profile_disables_insufficient_support_rebound_sample():
    config = load_config(profile="btc")
    assert config.strategy.trend_pullback is True
    assert config.strategy.breakout_retest is True
    assert config.strategy.support_rebound is False


def test_event_dedup_is_stable_and_level_specific():
    first = stable_key("near_key_level", "BTC/USDT", "btc", Horizon.SWING, "support:100")
    second = stable_key("near_key_level", "BTC/USDT", "btc", Horizon.SWING, "support:100")
    different = stable_key("near_key_level", "BTC/USDT", "btc", Horizon.SWING, "support:110")
    assert first == second
    assert first != different


def test_event_serialization(snapshot_factory):
    at = snapshot_factory().as_of
    event = make_event("analysis_completed", "BTC/USDT", "btc", None, at, "done", {})
    assert json.loads(event.model_dump_json())["deduplication_key"]


def test_renderers(snapshot_factory):
    report = analyze_snapshot(snapshot_factory(), AppConfig())
    assert json.loads(report_json(report))["schema_version"] == "3.0"
    markdown = report_markdown(report)
    for heading in (
        "当前环境",
        "关键点位",
        "接近提醒",
        "短线计划",
        "波段计划",
        "长期计划",
        "缺失数据",
        "风险说明",
    ):
        assert heading in markdown


def test_no_telegram_or_execution_terms_in_source():
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(path.read_text(encoding="utf-8") for path in (root / "src").rglob("*.py"))
    assert "BINANCE_API_KEY" not in source
    assert "BINANCE_API_SECRET" not in source
    assert "confirmation_token" not in source
    assert "client_order_id" not in source
    assert "send_telegram" not in source


def test_report_matches_schema_and_skill_assets(snapshot_factory):
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "analysis-report.schema.json").read_text())
    report = analyze_snapshot(snapshot_factory(), AppConfig()).model_dump(mode="json")
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        report
    )
    assert (root / "SKILL.md").read_text().startswith("---\nname: crypto-strategy-analyst")
    assert not (root / "references" / "risk-and-execution.md").exists()
    for name in (
        "analysis-engine.md",
        "asset-profiles.md",
        "strategies.md",
        "data-sources.md",
        "backtesting.md",
    ):
        assert (root / "references" / name).is_file()


def test_every_config_leaf_is_read_by_production_code():
    def leaves(model):
        values = []
        for name, field in model.model_fields.items():
            annotation = field.annotation
            values.extend(
                leaves(annotation)
                if isinstance(annotation, type) and issubclass(annotation, BaseModel)
                else [name]
            )
        return values

    root = Path(__file__).resolve().parents[1] / "src" / "crypto_strategy_analyst"
    attributes = {
        node.attr
        for path in root.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
    }
    dynamic_strategy_flags = {
        "support_rebound",
        "breakout_retest",
        "trend_pullback",
        "range_reversal",
        "bear_reversal",
        "bear_accumulation",
    }
    assert set(leaves(AppConfig)) - attributes - dynamic_strategy_flags == set()
