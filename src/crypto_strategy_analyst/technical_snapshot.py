"""Compact indicator-only analysis for token-efficient OpenClaw calls."""

from __future__ import annotations

import json
from typing import Any

from .config import AppConfig
from .indicators import indicator_map
from .models import MarketSnapshot
from .technical_analysis import analyze_indicators

REQUIRED_TIMEFRAMES = ("1w", "1d", "4h", "1h")
HORIZON_FRAMES = {
    "short": ("4h", "1h"),
    "swing": ("1d", "4h"),
    "long": ("1w", "1d"),
}
_BULLISH = {"bullish", "strengthening"}
_BEARISH = {"bearish", "weakening"}


def _horizon_reading(frames: tuple[str, str], readings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    primary_name, confirmation_name = frames
    primary = readings.get(primary_name)
    confirmation = readings.get(confirmation_name)
    if primary is None or confirmation is None:
        missing = [name for name in frames if name not in readings]
        return {
            "state": "unavailable",
            "confidence": 0,
            "risk_posture": "none",
            "reasons": [f"missing_indicator:{name}" for name in missing],
        }
    primary_trend = primary["ema"]["state"] == primary["sma"]["state"] == "bullish"
    confirmation_bearish = confirmation["bias"] in {"bearish", "bearish_lean"}
    macd_confirmed = primary["macd"]["state"] in _BULLISH
    rsi = float(primary["rsi"]["value"])
    rsi_entry_zone = 50 <= rsi < 70
    confidence = round(0.7 * primary["confluence_score"] + 0.3 * confirmation["confluence_score"], 1)
    reasons = [
        "ema_sma_bullish_alignment" if primary_trend else "ema_sma_alignment_missing",
        "macd_positive_or_improving" if macd_confirmed else "macd_not_confirmed",
        "rsi_entry_zone" if rsi_entry_zone else f"rsi_{primary['rsi']['state']}",
    ]
    if confirmation_bearish:
        reasons.append("confirmation_timeframe_bearish")
        return {
            "state": "risk_off",
            "confidence": confidence,
            "risk_posture": "none",
            "reasons": reasons,
        }
    if primary_trend and macd_confirmed and rsi_entry_zone:
        return {
            "state": "long_bias",
            "confidence": confidence,
            "risk_posture": "normal",
            "reasons": reasons,
        }
    if primary["bias"] in {"bearish", "bearish_lean"}:
        return {
            "state": "risk_off",
            "confidence": confidence,
            "risk_posture": "none",
            "reasons": reasons,
        }
    return {
        "state": "watch",
        "confidence": confidence,
        "risk_posture": "reduced" if primary["rsi"]["state"] == "overbought" else "normal",
        "reasons": reasons,
    }


def analyze_technical_snapshot(snapshot: MarketSnapshot, config: AppConfig) -> dict[str, Any]:
    """Return last-value indicator summaries without levels, patterns, or auxiliary data.

    Candle history remains inside the deterministic calculation path so EMA200 and
    MACD have sufficient warm-up.  It is intentionally omitted from the result
    that OpenClaw receives.
    """

    completed = {timeframe: snapshot.completed(timeframe) for timeframe in REQUIRED_TIMEFRAMES}
    indicators = indicator_map(completed, config.indicators)
    readings = analyze_indicators(indicators, config.indicators)
    missing = [timeframe for timeframe in REQUIRED_TIMEFRAMES if timeframe not in readings]
    return {
        "schema_version": "technical-1.0",
        "analysis_scope": "technical_indicators_only",
        "symbol": snapshot.symbol,
        "generated_at": snapshot.as_of.isoformat(),
        "price": snapshot.price,
        "data": {
            "required_timeframes": list(REQUIRED_TIMEFRAMES),
            "closed_bars": {timeframe: len(completed[timeframe]) for timeframe in REQUIRED_TIMEFRAMES},
            "missing_indicator_timeframes": missing,
        },
        "timeframes": readings,
        "horizons": {
            horizon: _horizon_reading(frames, readings) for horizon, frames in HORIZON_FRAMES.items()
        },
        "limitations": [
            "technical_indicators_only",
            "no_raw_candles_in_output",
            "no_patterns_or_levels",
            "no_trade_execution_or_price_plan",
        ],
    }


def technical_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def technical_markdown(report: dict[str, Any]) -> str:
    state_names = {
        "bullish": "多头",
        "bearish": "空头",
        "mixed": "分歧",
        "bullish_lean": "偏多",
        "bearish_lean": "偏空",
        "strengthening": "增强",
        "weakening": "减弱",
        "neutral": "中性",
        "oversold": "超卖",
        "overbought": "超买",
        "long_bias": "偏多观察",
        "watch": "等待",
        "risk_off": "风险回避",
        "unavailable": "数据不足",
    }
    lines = [
        f"# {report['symbol']} 技术指标快照",
        "",
        f"价格：{report['price']:.8g}；仅使用截至 {report['generated_at']} 的已收盘 K 线。",
        "",
        "## 周期指标",
        "",
    ]
    for timeframe, reading in report["timeframes"].items():
        lines.append(
            f"- {timeframe}：{state_names.get(reading['bias'], reading['bias'])}；"
            f"EMA {state_names.get(reading['ema']['state'], reading['ema']['state'])}；"
            f"MA {state_names.get(reading['sma']['state'], reading['sma']['state'])}；"
            f"RSI {reading['rsi']['value']:.1f}（{state_names.get(reading['rsi']['state'], reading['rsi']['state'])}）；"
            f"MACD {state_names.get(reading['macd']['state'], reading['macd']['state'])}；"
            f"ATR {reading['atr']['percent']:.2%}；量能比 {reading['volume']['ratio']:.2f}。"
        )
    lines += ["", "## 多周期结论", ""]
    labels = {"short": "短线", "swing": "波段", "long": "长期"}
    for horizon, reading in report["horizons"].items():
        lines.append(
            f"- {labels[horizon]}：{state_names.get(reading['state'], reading['state'])}；"
            f"一致性 {reading['confidence']:.1f}/100；风险 {reading['risk_posture']}；"
            f"条件：{'、'.join(reading['reasons'])}。"
        )
    lines += [
        "",
        "仅作技术指标研究：不分析形态、支撑阻力或情绪，不生成价格计划，也不执行交易。",
    ]
    return "\n".join(lines)
