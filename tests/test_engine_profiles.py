from datetime import timedelta

import pytest

from crypto_strategy_analyst.backtest import replay_signal
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.engine import analyze_snapshot
from crypto_strategy_analyst.models import Availability, DataPoint, Horizon, SignalStatus
from crypto_strategy_analyst.profiles.registry import get_profile, profile_for_symbol
from crypto_strategy_analyst.rendering import report_markdown
from crypto_strategy_analyst.structure import ChartPattern
from crypto_strategy_analyst.technical_snapshot import (
    analyze_technical_snapshot,
    technical_markdown,
)


@pytest.mark.parametrize(
    ("symbol", "name"),
    [
        ("BTC/USDT", "btc"),
        ("ETHUSDT", "eth"),
        ("BNB-USDT", "bnb"),
        ("SOL_USDT", "sol"),
        ("XRP/USDT", "generic"),
    ],
)
def test_auto_profile(symbol, name):
    assert profile_for_symbol(symbol).name == name


def test_profile_override_and_unknown():
    assert get_profile("btc", "ETH/USDT").name == "btc"
    with pytest.raises(ValueError):
        get_profile("unknown", "BTC/USDT")


def test_report_schema_horizons_and_events(snapshot_factory):
    report = analyze_snapshot(snapshot_factory(), AppConfig())
    assert report.schema_version == "3.0"
    assert set(report.horizons) == set(Horizon)
    assert any(event.event_type == "analysis_completed" for event in report.events)
    assert report.scores.data_completeness < 100
    assert report.scores.derivatives is None


def test_report_exposes_explainable_technical_indicator_panel(snapshot_factory):
    report = analyze_snapshot(snapshot_factory(), AppConfig())
    daily = report.market["technical_analysis"]["1d"]
    assert set(daily) == {
        "close",
        "bias",
        "confluence_score",
        "bullish_votes",
        "bearish_votes",
        "ema",
        "sma",
        "rsi",
        "macd",
        "atr",
        "volume",
    }
    assert daily["ema"]["periods"] == [20, 50, 200]
    assert daily["sma"]["periods"] == [20, 50, 200]
    assert 0 <= daily["rsi"]["value"] <= 100
    assert daily["macd"]["line"] - daily["macd"]["signal"] == pytest.approx(
        daily["macd"]["histogram"]
    )
    assert "## 技术指标" in report_markdown(report)


def test_technical_only_snapshot_is_compact_and_uses_closed_candles(snapshot_factory):
    baseline = snapshot_factory()
    future = snapshot_factory(future_spike=True)
    report = analyze_technical_snapshot(baseline, AppConfig())
    assert report["analysis_scope"] == "technical_indicators_only"
    assert set(report["timeframes"]) == {"1w", "1d", "4h", "1h"}
    assert set(report["horizons"]) == {"short", "swing", "long"}
    assert not {"candles", "key_levels", "chart_patterns", "auxiliary"}.intersection(report)
    assert "## 周期指标" in technical_markdown(report)
    assert report == analyze_technical_snapshot(future, AppConfig())


def test_future_candle_does_not_change_report(snapshot_factory):
    baseline = snapshot_factory()
    future = snapshot_factory(future_spike=True)
    assert (
        replay_signal(baseline, baseline.as_of, AppConfig()).scores
        == replay_signal(future, future.as_of, AppConfig()).scores
    )


def test_required_candle_missing_is_no_trade(snapshot_factory):
    snapshot = snapshot_factory()
    snapshot.candles["1w"] = []
    report = analyze_snapshot(snapshot, AppConfig())
    assert all(plan.status == SignalStatus.NO_TRADE for plan in report.horizons.values())
    assert any("candles:1w" in warning for warning in report.warnings)


def test_stale_and_future_auxiliary_not_scored(snapshot_factory):
    snapshot = snapshot_factory()
    snapshot.auxiliary["funding"] = DataPoint(
        status=Availability.AVAILABLE,
        source="test",
        observed_at=snapshot.as_of,
        freshness_seconds=9999,
        value=100,
    )
    snapshot.auxiliary["open_interest"] = DataPoint(
        status=Availability.AVAILABLE,
        source="future",
        observed_at=snapshot.as_of + timedelta(days=1),
        freshness_seconds=0,
        value=100,
    )
    report = analyze_snapshot(snapshot, AppConfig())
    assert report.data_availability["funding"].status == Availability.STALE
    assert report.scores.derivatives is None


def test_generic_warning_and_limited_confidence(snapshot_factory):
    report = analyze_snapshot(snapshot_factory("DOGE/USDT"), AppConfig())
    assert report.profile_confidence == "limited"
    assert report.confidence <= 68
    assert any(event.event_type == "profile_warning" for event in report.events)


def test_bnb_and_sol_hard_filters(snapshot_factory, available_point):
    cases = [
        ("BNB/USDT", "binance_platform_risk", "critical"),
        ("SOL/USDT", "network_health", "halted"),
    ]
    for symbol, name, value in cases:
        snapshot = snapshot_factory(symbol, auxiliary={name: available_point(value)})
        report = analyze_snapshot(snapshot, AppConfig())
        assert report.hard_filters
        assert all(plan.status == SignalStatus.NO_TRADE for plan in report.horizons.values())


def test_profile_context_changes_scores_and_risk(snapshot_factory, available_point):
    eth_weak = snapshot_factory(
        "ETH/USDT", auxiliary={"eth_btc": available_point({"change_percent": -5})}
    )
    eth_strong = snapshot_factory(
        "ETH/USDT", auxiliary={"eth_btc": available_point({"change_percent": 5})}
    )
    weak = analyze_snapshot(eth_weak, AppConfig())
    strong = analyze_snapshot(eth_strong, AppConfig())
    assert strong.confidence > weak.confidence
    btc = analyze_snapshot(snapshot_factory("BTC/USDT"), AppConfig())
    sol = analyze_snapshot(snapshot_factory("SOL/USDT"), AppConfig())
    assert (
        sol.horizons[Horizon.SWING].risk_suggestion.risk_fraction
        < btc.horizons[Horizon.SWING].risk_suggestion.risk_fraction
    )


def test_extreme_funding_and_oi_reduce_btc_and_sol(snapshot_factory, available_point):
    for symbol, funding in (("BTC/USDT", 0.001), ("SOL/USDT", 0.002)):
        base = analyze_snapshot(snapshot_factory(symbol), AppConfig()).confidence
        crowded = snapshot_factory(
            symbol,
            auxiliary={
                "funding": available_point(funding),
                "open_interest": available_point({"change_percent": 10}),
            },
        )
        assert analyze_snapshot(crowded, AppConfig()).confidence < base


def test_one_hour_noise_cannot_reverse_long_regime(snapshot_factory):
    snapshot = snapshot_factory(mode="bull")
    snapshot.candles["1h"] = snapshot_factory(mode="bear").candles["1h"]
    report = analyze_snapshot(snapshot, AppConfig())
    assert report.horizons[Horizon.LONG].market_regime.value in {
        "strong_bull",
        "bullish",
        "bull_pullback",
    }


def test_confirmed_bearish_pattern_suppresses_long_candidates(snapshot_factory, monkeypatch):
    pattern = ChartPattern(
        name="double_top",
        direction="bearish",
        state="confirmed",
        neckline=100,
        invalidation=110,
        measured_target=90,
        completed_index=12,
    )
    monkeypatch.setattr(
        "crypto_strategy_analyst.engine.detect_chart_patterns", lambda bars, indicator: [pattern]
    )
    report = analyze_snapshot(snapshot_factory(), AppConfig())
    assert all(plan.status == SignalStatus.NO_TRADE for plan in report.horizons.values())
    assert any(
        event.event_type == "risk_alert"
        and event.payload.get("action") == "suppress_long_candidate"
        for event in report.events
    )
    assert report.market["chart_patterns"]["1d"][0]["name"] == "double_top"
