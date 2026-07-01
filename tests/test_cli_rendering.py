import json

from crypto_strategy_analyst.cli import TOP_LEVEL_COMMANDS, build_parser, main
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.engine import analyze_snapshot
from crypto_strategy_analyst.rendering import report_json, report_markdown


def test_cli_has_exact_top_level_commands():
    parser = build_parser()
    action = next(action for action in parser._actions if action.dest == "command")
    assert tuple(action.choices) == TOP_LEVEL_COMMANDS


def test_renderers(snapshot_factory):
    report = analyze_snapshot(snapshot_factory(), AppConfig())
    assert json.loads(report_json(report))["schema_version"] == "2.0"
    markdown = report_markdown(report)
    assert "分周期计划" in markdown
    assert "不保证收益" in markdown


def test_validate_entry_cli(tmp_path, snapshot_factory, capsys):
    report = analyze_snapshot(snapshot_factory(), AppConfig())
    path = tmp_path / "report.json"
    path.write_text(report_json(report), encoding="utf-8")
    assert main(["validate-entry", str(path)]) == 0
    assert "valid" in capsys.readouterr().out


def test_research_cli(capsys):
    assert main(["research", "diagnose"]) == 0
    assert "no_auto_optimization" in capsys.readouterr().out


def test_removed_risk_command_prints_migration_hint(capsys):
    assert main(["risk", "--help"]) == 0
    assert "removed" in capsys.readouterr().out


def test_portfolio_and_journal_cli(tmp_path, capsys):
    config = tmp_path / "config.yaml"
    config.write_text(
        f"storage:\n  paper_account_file: {tmp_path}/paper.json\n  paper_trades_file: {tmp_path}/trades.jsonl\n  journal_file: {tmp_path}/journal.jsonl\n",
        encoding="utf-8",
    )
    assert main(["portfolio", "--config", str(config), "show"]) == 0
    assert main(["journal", "--config", str(config), "add", '{"symbol":"ETHUSDT"}']) == 0
    assert "ETHUSDT" in capsys.readouterr().out
