from __future__ import annotations

import json
from pathlib import Path

import pytest

import crypto_strategy_analyst.cli as cli_module
from crypto_strategy_analyst.backtest import run_backtest
from crypto_strategy_analyst.cli import main
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.dataset import fetch_dataset, load_dataset
from crypto_strategy_analyst.errors import DatasetIntegrityError


class _DatasetClient:
    def __init__(self, frames, trading_rules):
        self.frames = frames
        self.trading_rules = trading_rules

    def fetch_klines(self, symbol, timeframe, *, start, end):
        del symbol, start, end
        return self.frames[timeframe].copy()

    def fetch_symbol_trading_rules(self, symbol):
        del symbol
        return self.trading_rules


def _create_dataset(tmp_path, market_frames, trading_rules):
    client = _DatasetClient(market_frames, trading_rules)
    start = market_frames["1d"].index[0]
    end = market_frames["1d"].index[-1] + cli_module.pd.Timedelta(days=1)
    fetch_dataset(
        client,
        symbol="BTC/USDT",
        start=start.to_pydatetime(),
        end=end.to_pydatetime(),
        output_dir=tmp_path,
    )
    return load_dataset(tmp_path)


def test_manifest_hashes_load_and_csv_tampering_fails(tmp_path, market_frames, trading_rules):
    snapshot = _create_dataset(tmp_path, market_frames, trading_rules)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert snapshot.dataset_hash == manifest["dataset_hash"]
    assert set(manifest["files"]) == {"1d", "4h", "1h"}
    assert all(item["sha256"] for item in manifest["files"].values())

    csv_path = tmp_path / "4h.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(DatasetIntegrityError, match="hash mismatch"):
        load_dataset(tmp_path)


def test_manifest_hash_covers_trading_rule_values(tmp_path, market_frames, trading_rules):
    _create_dataset(tmp_path, market_frames, trading_rules)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["trading_rules"]["minimum_notional"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DatasetIntegrityError, match="manifest hash mismatch"):
        load_dataset(tmp_path)


def test_same_dataset_and_config_reproduce_metrics(tmp_path, market_frames, trading_rules):
    snapshot = _create_dataset(tmp_path, market_frames, trading_rules)
    start = market_frames["1d"].index[220] + cli_module.pd.Timedelta(days=1)
    kwargs = {
        "start": start.to_pydatetime(),
        "end": (start + cli_module.pd.Timedelta(hours=12)).to_pydatetime(),
        "trading_rules": snapshot.trading_rules,
        "dataset_hash": snapshot.dataset_hash,
    }
    first = run_backtest(snapshot.frames, snapshot.symbol, AppConfig(), **kwargs)
    second = run_backtest(snapshot.frames, snapshot.symbol, AppConfig(), **kwargs)
    assert first.metrics == second.metrics
    assert first.dataset_hash == second.dataset_hash
    assert first.strategy_config_hash == second.strategy_config_hash


def test_offline_backtest_path_never_constructs_network_client(
    tmp_path, market_frames, trading_rules, monkeypatch, capsys
):
    snapshot = _create_dataset(tmp_path / "dataset", market_frames, trading_rules)

    class _NoNetwork:
        def __init__(self, *args, **kwargs):
            raise AssertionError("offline backtest attempted network access")

    class _Metrics:
        def model_dump(self):
            return {"trade_count": 0}

    class _Result:
        metrics = _Metrics()

    monkeypatch.setattr(cli_module, "BinancePublicClient", _NoNetwork)
    monkeypatch.setattr(cli_module, "run_backtest", lambda *args, **kwargs: _Result())
    monkeypatch.setattr(cli_module, "save_backtest", lambda *args, **kwargs: Path("result.json"))

    assert main(["backtest", "--dataset-dir", str(tmp_path / "dataset")]) == 0
    assert json.loads(capsys.readouterr().out)["metrics"]["trade_count"] == 0
    assert snapshot.symbol == "BTC/USDT"
