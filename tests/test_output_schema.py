from __future__ import annotations

import json
from pathlib import Path

from conftest import make_ohlcv
from jsonschema import validate

from crypto_strategy_analyst.analysis import analyze_symbol
from crypto_strategy_analyst.config import AppConfig


class FakeClient:
    def fetch_klines(self, symbol, interval, **kwargs):
        frequency = {"1d": "1d", "4h": "4h", "1h": "1h"}[interval]
        return make_ohlcv(periods=500, freq=frequency, seed={"1d": 1, "4h": 2, "1h": 3}[interval])


def test_analysis_json_matches_committed_schema():
    report = analyze_symbol("BTC/USDT", AppConfig(), client=FakeClient())
    schema_path = Path(__file__).parents[1] / "schemas" / "analysis-report.schema.json"
    validate(instance=report.model_dump(mode="json"), schema=json.loads(schema_path.read_text()))
    assert all(value == "not_available" for value in report.missing_data.values())
