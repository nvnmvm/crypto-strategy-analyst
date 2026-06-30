"""Current-time analysis built on the shared strategy evaluator."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime

import pandas as pd

from .config import AppConfig
from .data import (
    INTERVAL_SECONDS,
    BinancePublicClient,
    drop_incomplete_last_bar,
    validate_market_data,
)
from .errors import MarketDataError, PositionConstraintError
from .freshness import DataFreshnessResult, check_data_freshness
from .models import AnalysisReport, DataQuality, QualityGrade, SignalLabel, SymbolTradingRules
from .risk import RiskState, calculate_position, risk_blockers
from .strategy import (
    REQUIRED_TIMEFRAMES,
    SetupEvaluation,
    align_evaluation_time,
    closed_bars_at,
    evaluate_setup_at_time,
    prepare_market_frames,
)

LOGGER = logging.getLogger(__name__)


def _build_report(
    symbol: str,
    config: AppConfig,
    evaluation: SetupEvaluation,
    quality: dict[str, DataQuality],
    risk_state: RiskState,
    freshness: DataFreshnessResult,
    freshness_retry_attempts: int,
    trading_rules: SymbolTradingRules | None,
    *,
    risk_state_initialized: bool,
) -> AnalysisReport:
    decision = evaluation.decision
    current_price = float(evaluation.frames["4h"]["close"].iloc[-1])
    position = None
    if (
        decision.entry_zone
        and decision.stop_loss
        and decision.take_profit_1
        and decision.take_profit_2
        and decision.label.value.endswith("candidate")
        and freshness.is_fresh
        and trading_rules is not None
    ):
        try:
            position = calculate_position(
                entry_price=current_price,
                stop_price=decision.stop_loss,
                config=config.risk,
                account_equity_cny=risk_state.current_equity_cny,
                trading_rules=trading_rules,
            )
        except PositionConstraintError as exc:
            decision = replace(
                decision,
                label=SignalLabel.NO_TRADE,
                blockers=[*decision.blockers, str(exc)],
            )
    warnings = [
        "仅使用公开现货行情，不包含订单簿、私有账户或执行能力。",
        "CNY/USDT 换算使用配置值，不是实时外汇报价。",
        "当前报告是候选计划，实际执行前需要根据下一根4小时开盘价重新验证。",
    ]
    warnings.extend(f"{tf}: {issue}" for tf, item in quality.items() for issue in item.issues)
    warnings.extend(f"阻断条件：{blocker}" for blocker in decision.blockers)
    if trading_rules is None:
        warnings.append("阻断条件：trading_rules_not_available")
    if freshness_retry_attempts:
        warnings.append(f"数据新鲜度重试 {freshness_retry_attempts} 次。")
    warnings.append(f"仓位计算使用持久化当前权益 ¥{risk_state.current_equity_cny:.2f}。")
    if risk_state_initialized:
        warnings.append("风险状态文件原先缺失，已使用配置中的首次初始化权益安全创建。")
    reasons = [
        f"日线趋势={evaluation.trends['1d'].value}",
        f"4小时趋势={evaluation.trends['4h'].value}",
        *decision.confirmations,
    ]
    if not decision.confirmations:
        reasons.append("未满足足够的确定性确认条件")
    return AnalysisReport(
        generated_at=datetime.now(UTC),
        requested_at=evaluation.requested_at,
        evaluation_time=evaluation.evaluation_time,
        evaluation_timeframe="4h",
        time_alignment_applied=evaluation.time_alignment_applied,
        latest_completed_candle_close={
            timeframe: (
                evaluation.frames[timeframe].index[-1]
                + pd.Timedelta(seconds=INTERVAL_SECONDS[timeframe])
            ).to_pydatetime()
            for timeframe in REQUIRED_TIMEFRAMES
        },
        data_freshness=freshness.timeframes,
        freshness_retry_attempts=freshness_retry_attempts,
        symbol=symbol.upper().replace("-", "/"),
        data_source="Binance public spot REST /api/v3/klines (completed candles only)",
        analysis_timeframes=list(REQUIRED_TIMEFRAMES),
        current_price=current_price,
        account_equity_cny=risk_state.current_equity_cny,
        risk_locks=risk_blockers(config.risk, risk_state),
        trading_rules=trading_rules or "not_available",
        trading_rules_status=(
            "available" if trading_rules is not None else "trading_rules_not_available"
        ),
        data_quality=quality,
        daily_trend=evaluation.trends["1d"],
        four_hour_trend=evaluation.trends["4h"],
        one_hour_trend=evaluation.trends["1h"],
        one_hour_confirmation=(
            "、".join(item for item in decision.confirmations if item) or "没有足够的入场确认"
        ),
        support_zones=evaluation.supports,
        resistance_zones=evaluation.resistances,
        indicators=evaluation.indicators,
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
            "最近关键阻力无法同时容纳合规 TP1 与 TP2",
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


def analyze_frames_at_time(
    symbol: str,
    frames: Mapping[str, pd.DataFrame],
    config: AppConfig,
    *,
    evaluated_at: datetime,
    risk_state: RiskState | None = None,
    risk_state_initialized: bool = False,
    freshness_retry_attempts: int = 0,
    trading_rules: SymbolTradingRules | None = None,
) -> AnalysisReport:
    """Analyze open-time-indexed frames at one aligned completed 4h decision time."""

    prepared = prepare_market_frames(frames, config)
    evaluation_time = align_evaluation_time(evaluated_at)
    freshness = check_data_freshness(frames, evaluation_time, REQUIRED_TIMEFRAMES)
    visible_quality: dict[str, DataQuality] = {}
    for timeframe in REQUIRED_TIMEFRAMES:
        visible = closed_bars_at(
            prepared[timeframe],
            timeframe,
            evaluation_time,
            history_limit=config.market.history_limit,
        )
        visible_quality[timeframe] = validate_market_data(visible, timeframe)
    complete = all(item.grade == QualityGrade.VALID for item in visible_quality.values())
    complete = complete and freshness.is_fresh
    state = risk_state or RiskState(
        date=evaluation_time.date(),
        daily_start_equity_cny=config.risk.account_equity_cny,
        current_equity_cny=config.risk.account_equity_cny,
        peak_equity_cny=config.risk.account_equity_cny,
    )
    evaluation = evaluate_setup_at_time(
        prepared,
        config,
        requested_at=evaluated_at,
        risk_state=state,
        data_is_complete=complete,
    )
    if not freshness.is_fresh:
        evaluation = replace(
            evaluation,
            decision=replace(
                evaluation.decision,
                label=SignalLabel.NO_TRADE,
                blockers=[*evaluation.decision.blockers, *freshness.blockers],
                entry_zone=None,
                stop_loss=None,
                take_profit_1=None,
                take_profit_2=None,
                reward_risk=None,
                planned_entry_price=None,
            ),
        )
    return _build_report(
        symbol,
        config,
        evaluation,
        visible_quality,
        state,
        freshness,
        freshness_retry_attempts,
        trading_rules,
        risk_state_initialized=risk_state_initialized,
    )


def analyze_symbol(
    symbol: str,
    config: AppConfig,
    *,
    client: BinancePublicClient | None = None,
    risk_state: RiskState | None = None,
    risk_state_initialized: bool = False,
    requested_at: datetime | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> AnalysisReport:
    """Fetch public frames and align them to the shared completed 4h decision time."""

    market_client = client or BinancePublicClient(config.market)
    as_of = requested_at or datetime.now(UTC)
    evaluation_time = align_evaluation_time(as_of)
    within_grace = (
        pd.Timestamp(as_of) - pd.Timestamp(evaluation_time)
    ).total_seconds() <= config.market.freshness_grace_seconds
    frames: dict[str, pd.DataFrame] = {}
    retry_attempts = 0
    for attempt in range(config.market.freshness_retry_count + 1):
        attempt_now = datetime.now(UTC) if requested_at is None else as_of
        frames = {}
        for timeframe in REQUIRED_TIMEFRAMES:
            raw = market_client.fetch_klines(symbol, timeframe, limit=config.market.history_limit)
            frames[timeframe] = drop_incomplete_last_bar(raw, timeframe, now=attempt_now)
        freshness = check_data_freshness(frames, evaluation_time, REQUIRED_TIMEFRAMES)
        if freshness.is_fresh or not within_grace or attempt >= config.market.freshness_retry_count:
            break
        retry_attempts += 1
        if config.market.freshness_retry_delay_seconds:
            sleep_fn(config.market.freshness_retry_delay_seconds)
    trading_rules: SymbolTradingRules | None = None
    try:
        trading_rules = market_client.fetch_symbol_trading_rules(symbol)
    except (AttributeError, MarketDataError):
        LOGGER.warning("public trading rules unavailable", extra={"event_data": {"symbol": symbol}})
    report = analyze_frames_at_time(
        symbol,
        frames,
        config,
        evaluated_at=as_of,
        risk_state=risk_state,
        risk_state_initialized=risk_state_initialized,
        freshness_retry_attempts=retry_attempts,
        trading_rules=trading_rules,
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
