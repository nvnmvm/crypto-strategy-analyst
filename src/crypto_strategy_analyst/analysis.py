"""Multi-timeframe analysis orchestration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .config import AppConfig
from .data import BinancePublicClient, drop_incomplete_last_bar, validate_market_data
from .indicators import add_indicators, snapshot
from .levels import detect_zones, merge_timeframe_zones
from .models import AnalysisReport, QualityGrade
from .risk import RiskState, calculate_position
from .signal import generate_signal
from .structure import classify_trend, detect_confirmed_swings

LOGGER = logging.getLogger(__name__)


def analyze_symbol(
    symbol: str,
    config: AppConfig,
    *,
    client: BinancePublicClient | None = None,
    risk_state: RiskState | None = None,
) -> AnalysisReport:
    """Fetch, validate, analyze, risk-size, and build one typed report."""

    market_client = client or BinancePublicClient(config.market)
    frames = {}
    quality = {}
    trends = {}
    indicators = {}
    timeframe_zones = []
    for timeframe in ("1d", "4h", "1h"):
        raw = market_client.fetch_klines(symbol, timeframe, limit=config.market.history_limit)
        completed = drop_incomplete_last_bar(raw, timeframe)
        quality[timeframe] = validate_market_data(completed, timeframe)
        enriched = add_indicators(completed, enable_adx=config.strategy.enable_adx)
        frames[timeframe] = enriched
        swings = detect_confirmed_swings(
            enriched,
            left=config.strategy.swing_left,
            right=config.strategy.swing_right,
        )
        trends[timeframe] = classify_trend(enriched, swings)
        indicators[timeframe] = snapshot(enriched, enable_adx=config.strategy.enable_adx)
        supports, resistances = detect_zones(
            enriched,
            swings,
            timeframe,
            merge_percent=config.strategy.level_merge_percent,
        )
        timeframe_zones.extend([*supports[:5], *resistances[:5]])

    current_price = float(frames["4h"]["close"].iloc[-1])
    merged = merge_timeframe_zones(timeframe_zones, current_price)
    supports = sorted(
        (zone for zone in merged if zone.level_type == "support"),
        key=lambda zone: zone.center_price,
        reverse=True,
    )[:8]
    resistances = sorted(
        (zone for zone in merged if zone.level_type == "resistance"),
        key=lambda zone: zone.center_price,
    )[:8]
    complete = all(item.grade == QualityGrade.VALID for item in quality.values())
    decision = generate_signal(
        daily_trend=trends["1d"],
        four_hour_trend=trends["4h"],
        one_hour_frame=frames["1h"],
        four_hour_frame=frames["4h"],
        supports=supports,
        resistances=resistances,
        data_is_complete=complete,
        config=config,
        risk_state=risk_state,
    )
    position = None
    if decision.entry_zone and decision.stop_loss and decision.label.value.endswith("candidate"):
        position = calculate_position(
            entry_price=current_price,
            stop_price=decision.stop_loss,
            config=config.risk,
        )
    warnings = [
        "仅使用公开现货行情，不包含订单簿、私有账户或执行能力。",
        "CNY/USDT 换算使用配置值，不是实时外汇报价。",
    ]
    warnings.extend(f"{tf}: {issue}" for tf, item in quality.items() for issue in item.issues)
    warnings.extend(f"阻断条件：{blocker}" for blocker in decision.blockers)
    reasons = [
        f"日线趋势={trends['1d'].value}",
        f"4小时趋势={trends['4h'].value}",
        *decision.confirmations,
    ]
    if not decision.confirmations:
        reasons.append("未满足足够的确定性确认条件")
    report = AnalysisReport(
        generated_at=datetime.now(UTC),
        symbol=symbol.upper().replace("-", "/"),
        data_source="Binance public spot REST /api/v3/klines (completed candles only)",
        analysis_timeframes=["1d", "4h", "1h"],
        current_price=current_price,
        data_quality=quality,
        daily_trend=trends["1d"],
        four_hour_trend=trends["4h"],
        one_hour_confirmation=(
            "、".join(item for item in decision.confirmations if item) or "没有足够的入场确认"
        ),
        support_zones=supports,
        resistance_zones=resistances,
        indicators=indicators,
        signal=decision.label,
        signal_score=decision.score,
        score_breakdown=decision.breakdown,
        entry_zone=decision.entry_zone or "not_available",
        stop_loss=decision.stop_loss or "not_available",
        take_profit_1=decision.take_profit_1 or "not_available",
        take_profit_2=decision.take_profit_2 or "not_available",
        trailing_stop_method=config.risk.trailing_stop_method,
        risk_reward_ratio=(
            round(decision.reward_risk, 4) if decision.reward_risk is not None else "not_available"
        ),
        suggested_position_size=position or "not_available",
        maximum_loss_amount=position.risk_amount_cny if position else "not_available",
        reasons=reasons,
        invalidation_conditions=[
            "日线趋势转为 bearish",
            "关键支撑区域被有效跌破",
            "盈亏比低于 2:1 或上方阻力过近",
            "单日两次止损、单日亏损达到 2% 或最大回撤达到 10%",
            "任何必需周期出现数据缺口、重复、倒序或 OHLC 异常",
        ],
        missing_data={
            "news_sentiment": "not_available",
            "fear_greed_index": "not_available",
            "on_chain_data": "not_available",
            "capital_flow": "not_available",
            "machine_learning_model": "not_available",
        },
        warnings=warnings,
    )
    LOGGER.info(
        "analysis completed",
        extra={
            "event_data": {
                "symbol": report.symbol,
                "signal": report.signal,
                "score": report.signal_score,
            }
        },
    )
    return report
