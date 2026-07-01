import json
from pathlib import Path

import pytest

from crypto_strategy_analyst.journal import add_entry, read_entries
from crypto_strategy_analyst.portfolio import PaperBroker
from crypto_strategy_analyst.storage import atomic_json_write, read_json


def test_atomic_write_backup_and_corruption_recovery(tmp_path: Path):
    path = tmp_path / "state.json"
    atomic_json_write(path, {"version": 1})
    atomic_json_write(path, {"version": 2})
    path.write_text("broken", encoding="utf-8")
    assert read_json(path, {}) == {"version": 1}


def test_missing_and_fully_corrupt_state_use_default(tmp_path: Path):
    path = tmp_path / "missing.json"
    assert read_json(path, {"safe": True}) == {"safe": True}
    path.write_text("[]", encoding="utf-8")
    assert read_json(path, {"safe": True}) == {"safe": True}


def test_paper_buy_sell_and_safety(tmp_path: Path):
    broker = PaperBroker(tmp_path / "paper-account.json", tmp_path / "paper-trades.jsonl")
    bought = broker.execute("BTCUSDT", "buy", 1, 100)
    assert bought.cash == pytest.approx(499.9)
    assert bought.positions["BTCUSDT"] == 1
    sold = broker.execute("BTCUSDT", "sell", 0.5, 110)
    assert sold.positions["BTCUSDT"] == 0.5
    assert len((tmp_path / "paper-trades.jsonl").read_text().splitlines()) == 2
    with pytest.raises(ValueError, match="insufficient"):
        broker.execute("BTCUSDT", "sell", 2, 110)
    with pytest.raises(ValueError, match="positive"):
        broker.execute("BTCUSDT", "buy", 0, 110)
    with pytest.raises(ValueError, match="side"):
        broker.execute("BTCUSDT", "hold", 1, 110)


def test_manual_journal_tolerates_bad_line(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    add_entry(path, {"symbol": "BTCUSDT", "pnl": 4})
    with path.open("a", encoding="utf-8") as handle:
        handle.write("bad\n")
    values = read_entries(path)
    assert values[0]["symbol"] == "BTCUSDT"
    assert json.loads(path.read_text().splitlines()[0])["pnl"] == 4
