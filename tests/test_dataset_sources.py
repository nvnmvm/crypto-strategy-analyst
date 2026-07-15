import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from crypto_strategy_analyst.data_sources.binance_derivatives import BinanceDerivativesData
from crypto_strategy_analyst.data_sources.binance_market import BinanceMarketData
from crypto_strategy_analyst.data_sources.composite import (
    CompositeDataSource,
    load_external_context,
)
from crypto_strategy_analyst.data_sources.dominance import DominanceData
from crypto_strategy_analyst.data_sources.etf import ETFData
from crypto_strategy_analyst.data_sources.macro import MacroData
from crypto_strategy_analyst.data_sources.onchain import OnchainData
from crypto_strategy_analyst.data_sources.relative_strength import RelativeStrengthData
from crypto_strategy_analyst.dataset import load_dataset, save_dataset
from crypto_strategy_analyst.models import Availability, DataPoint


class Response:
    def __init__(self, value, status=200):
        self.value = value
        self.status_code = status

    def json(self):
        return self.value

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://test")
            raise httpx.HTTPStatusError(
                "bad", request=request, response=httpx.Response(self.status_code, request=request)
            )


class Client:
    def __init__(self, router):
        self.router = router

    def get(self, url, params=None):
        return self.router(url, params or {})


def kline_rows(count=25):
    now = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000)
    return [
        [
            now + index * 3_600_000,
            "100",
            "200",
            "99",
            str(100 + index),
            "20",
            now + (index + 1) * 3_600_000 - 1,
        ]
        for index in range(count)
    ]


def test_binance_market_source():
    def router(url, params):
        if "klines" in url:
            return Response(kline_rows())
        if "ticker/price" in url:
            return Response({"price": "125"})
        return Response({"symbols": [{"symbol": "BTCUSDT"}]})

    snapshot = BinanceMarketData(client=Client(router)).snapshot("BTC/USDT", ["1h"], 25)
    assert snapshot.symbol == "BTC/USDT"
    assert snapshot.price == 125
    assert len(snapshot.candles["1h"]) == 25


def test_binance_history_paginates_from_start_time():
    rows = kline_rows(1001)
    for row in rows:
        row[2] = "2000"
    requested_starts: list[int] = []

    def router(url, params):
        if "klines" in url:
            requested_starts.append(params["startTime"])
            return Response(rows[:1000] if params["startTime"] <= rows[0][0] else rows[1000:])
        if "ticker/price" in url:
            return Response({"price": "125"})
        return Response({"symbols": [{"symbol": "BTCUSDT"}]})

    start = datetime.fromtimestamp(rows[0][0] / 1000, UTC)
    end = datetime.fromtimestamp((rows[-1][6] + 1) / 1000, UTC)
    snapshot = BinanceMarketData(client=Client(router)).history("BTC/USDT", ["1h"], start, end)
    assert len(snapshot.candles["1h"]) == 1001
    assert requested_starts == [rows[0][0], rows[1000][0]]


def test_derivatives_success_and_failure():
    success = BinanceDerivativesData(
        client=Client(
            lambda url, params: Response(
                {"lastFundingRate": "0.001"} if "premium" in url else {"openInterest": "123"}
            )
        )
    ).fetch("BTCUSDT")
    assert success["funding"].status == Availability.AVAILABLE
    failed = BinanceDerivativesData(client=Client(lambda url, params: Response({}, 500))).fetch(
        "BTCUSDT"
    )
    assert all(point.status == Availability.FAILED for point in failed.values())


def test_relative_strength_and_dominance():
    relative = RelativeStrengthData(
        client=Client(lambda url, params: Response(kline_rows()))
    ).fetch("SOLUSDT")
    assert set(relative) == {"sol_btc", "sol_eth"}
    dominance = DominanceData(
        client=Client(
            lambda url, params: Response({"data": {"market_cap_percentage": {"btc": 54}}})
        )
    ).fetch("BTCUSDT")
    assert dominance["btc_dominance"].value == 54


def test_unavailable_pluggable_sources():
    assert ETFData().fetch("BTCUSDT")["etf_flow"].status == Availability.NOT_AVAILABLE
    assert MacroData().fetch("BTCUSDT")["macro"].status == Availability.NOT_AVAILABLE
    assert "network_health" in OnchainData().fetch("SOLUSDT")


def test_composite_source_merges(snapshot_factory):
    class Market:
        def snapshot(self, symbol, timeframes, limit):
            return snapshot_factory(symbol)

    class Aux:
        def fetch(self, symbol):
            return {"x": DataPoint(status=Availability.AVAILABLE, source="x", value=1)}

    assert (
        CompositeDataSource(Market(), [Aux()]).snapshot("BTC/USDT", ["1h"], 10).auxiliary["x"].value
        == 1
    )


def test_dataset_roundtrip_and_hash_detection(tmp_path: Path, snapshot_factory):
    snapshot = snapshot_factory(count=20)
    save_dataset(snapshot, tmp_path)
    loaded = load_dataset(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["software_version"] == "0.3.0"
    assert loaded.symbol == snapshot.symbol
    assert set(loaded.candles) == set(snapshot.candles)
    (tmp_path / "1h.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_dataset(tmp_path)


def test_external_context_json(tmp_path: Path):
    path = tmp_path / "context.json"
    path.write_text(
        json.dumps(
            {
                "macro": {
                    "status": "available",
                    "source": "caller",
                    "value": {"score": 40},
                    "detail": "",
                }
            }
        ),
        encoding="utf-8",
    )
    assert load_external_context(path)["macro"].source == "caller"
