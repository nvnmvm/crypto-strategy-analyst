import json
from pathlib import Path

import jsonschema

from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.engine import analyze_snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_openclaw_assets_exist():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: crypto-strategy-analyst")
    for name in (
        "analysis-engine.md",
        "asset-profiles.md",
        "risk-and-execution.md",
        "backtesting.md",
    ):
        assert (ROOT / "references" / name).is_file()
    for name in ("btc", "eth", "bnb", "sol", "generic"):
        assert (ROOT / "config" / "profiles" / f"{name}.yaml").is_file()


def test_report_matches_public_schema(snapshot_factory):
    schema = json.loads((ROOT / "schemas" / "analysis-report.schema.json").read_text())
    report = analyze_snapshot(snapshot_factory(), AppConfig()).model_dump(mode="json")
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        report
    )


def test_real_trading_defaults_are_fail_closed():
    config = AppConfig()
    assert config.trading.trading_enabled is False
    assert config.trading.futures_enabled is False
    assert config.trading.testnet is True
    assert config.trading.require_human_confirmation is True
