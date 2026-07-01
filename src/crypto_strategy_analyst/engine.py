"""One deterministic strategy engine for current and historical evaluation."""

from __future__ import annotations

import hashlib

import numpy as np

from .config import AppConfig
from .models import (
    AnalysisEvent,
    AnalysisReport,
    Availability,
    ComponentScores,
    DataPoint,
    Horizon,
    HorizonPlan,
    MarketSnapshot,
    PriceLevel,
    SignalStatus,
)
from .profiles.base import AssetProfile
from .profiles.registry import get_profile

HORIZON_FRAMES = {
    Horizon.SHORT: ["4h", "1h", "15m"],
    Horizon.SWING: ["1d", "4h", "1h"],
    Horizon.LONG: ["1w", "1d", "4h"],
}


def _series(snapshot: MarketSnapshot, frame: str) -> np.ndarray:
    return np.array([bar.close for bar in snapshot.completed(frame)], dtype=float)


def _atr(snapshot: MarketSnapshot, frame: str) -> float:
    bars = snapshot.completed(frame)
    if len(bars) < 2:
        return snapshot.price * 0.02
    values = [
        max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
        for prev, bar in zip(bars[-15:-1], bars[-14:], strict=False)
    ]
    return float(np.mean(values)) if values else snapshot.price * 0.02


def _trend_score(values: np.ndarray) -> float:
    if len(values) < 20:
        return 50
    fast = float(np.mean(values[-10:]))
    slow = float(np.mean(values[-20:]))
    distance = (fast / slow - 1) * 500
    momentum = (values[-1] / values[-10] - 1) * 250
    return float(np.clip(50 + distance + momentum, 0, 100))


def _levels(snapshot: MarketSnapshot, config: AppConfig) -> list[PriceLevel]:
    """Cluster pivots and count separated reactions, not adjacent candle noise."""
    levels: list[PriceLevel] = []
    for frame in ("1w", "1d", "4h", "1h"):
        bars = snapshot.completed(frame)
        if len(bars) < 8:
            continue
        atr = _atr(snapshot, frame)
        tolerance = atr * config.strategy.level_tolerance_atr
        candidates: list[tuple[float, str, int]] = []
        for index in range(2, len(bars) - 2):
            window = bars[index - 2 : index + 3]
            if bars[index].low == min(item.low for item in window):
                candidates.append((bars[index].low, "support", index))
            if bars[index].high == max(item.high for item in window):
                candidates.append((bars[index].high, "resistance", index))
        for price, kind, _first_index in candidates:
            matching = [x for x in candidates if x[1] == kind and abs(x[0] - price) <= tolerance]
            separated: list[int] = []
            for _, _, index in matching:
                if not separated or index - separated[-1] >= config.strategy.touch_cooldown_bars:
                    separated.append(index)
            levels.append(
                PriceLevel(
                    kind=kind,
                    price=float(np.mean([x[0] for x in matching])),
                    timeframe=frame,
                    strength=min(100, 25 + len(separated) * 15),
                    touches=max(1, len(separated)),
                )
            )
    levels.sort(key=lambda level: (abs(level.price - snapshot.price), -level.strength))
    deduped: list[PriceLevel] = []
    tolerance = _atr(snapshot, "1d") * config.strategy.level_tolerance_atr
    for level in levels:
        duplicate = next(
            (
                x
                for x in deduped
                if x.kind == level.kind and abs(x.price - level.price) <= tolerance
            ),
            None,
        )
        if duplicate is None:
            deduped.append(level)
        elif level.strength > duplicate.strength:
            deduped[deduped.index(duplicate)] = level
    return deduped[:12]


def _aux_score(snapshot: MarketSnapshot, names: tuple[str, ...], keyword: str) -> float:
    values: list[float] = []
    for name in names:
        point = snapshot.auxiliary.get(name)
        if (
            point
            and point.status == Availability.AVAILABLE
            and (point.observed_at is None or point.observed_at <= snapshot.as_of)
        ):
            value = point.value
            if isinstance(value, (int, float)):
                values.append(float(np.clip(50 + value, 0, 100)))
            elif isinstance(value, dict) and isinstance(value.get("score"), (int, float)):
                values.append(float(value["score"]))
    return float(np.mean(values)) if values else (45 if keyword else 50)


def _scores(snapshot: MarketSnapshot, profile: AssetProfile) -> ComponentScores:
    trends = [_trend_score(_series(snapshot, frame)) for frame in ("1w", "1d", "4h", "1h")]
    technical = sum(
        score * weight
        for score, weight in zip(trends, profile.timeframe_weights.values(), strict=True)
    )
    return ComponentScores(
        technical=technical,
        derivatives=_aux_score(snapshot, ("funding", "open_interest", "liquidations"), "d"),
        onchain=_aux_score(snapshot, ("onchain", "chain_activity", "network_health"), "o"),
        macro=_aux_score(snapshot, ("macro", "etf_flow", "btc_dominance"), "m"),
        relative_strength=_aux_score(snapshot, ("eth_btc", "bnb_btc", "sol_btc", "sol_eth"), "r"),
        asset_specific=_aux_score(snapshot, profile.context_fields, "a"),
    )


def _required_failures(snapshot: MarketSnapshot) -> list[str]:
    failures: list[str] = []
    for name, point in {
        "trading_rules": snapshot.trading_rules,
        "timestamp": snapshot.timestamp,
        "volume": snapshot.volume,
    }.items():
        if point.status != Availability.AVAILABLE:
            failures.append(name)
    for frame in ("1w", "1d", "4h", "1h"):
        if not snapshot.completed(frame):
            failures.append(f"candles:{frame}")
    return failures


def _plan(
    horizon: Horizon,
    snapshot: MarketSnapshot,
    levels: list[PriceLevel],
    confidence: float,
    profile: AssetProfile,
    config: AppConfig,
    blocked: bool,
) -> HorizonPlan:
    frames = [x for x in HORIZON_FRAMES[horizon] if snapshot.completed(x)]
    trend = float(np.mean([_trend_score(_series(snapshot, frame)) for frame in frames]))
    support = next((x for x in levels if x.kind == "support" and x.price < snapshot.price), None)
    resistance = next(
        (x for x in levels if x.kind == "resistance" and x.price > snapshot.price), None
    )
    atr = _atr(snapshot, frames[0]) if frames else snapshot.price * 0.02
    stop = (
        min(snapshot.price - profile.stop_atr * atr, support.price - 0.2 * atr)
        if support
        else snapshot.price - profile.stop_atr * atr
    )
    risk = snapshot.price - stop
    target_2r = snapshot.price + risk * config.strategy.minimum_reward_risk
    target_3r = snapshot.price + risk * 3
    strategies = [
        name
        for name in (
            "trend_pullback",
            "support_rebound",
            "breakout_retest",
            "range_reversal",
            "bear_reversal",
            "bear_accumulation",
        )
        if getattr(config.strategy, name)
    ]
    strategy = strategies[0] if strategies else "disabled"
    reasons = [f"trend_score={trend:.1f}", f"confidence={confidence:.1f}"]
    if blocked or not strategies:
        status = SignalStatus.NO_TRADE
        reasons.append("required data, hard filter, or strategy toggle blocked entry")
    elif trend < 45 or confidence < config.strategy.minimum_confidence:
        status = SignalStatus.WATCH
    elif resistance and resistance.price < target_2r:
        status = SignalStatus.WATCH
        reasons.append("nearest resistance leaves less than 2R")
    elif confidence >= config.strategy.entry_confidence:
        status = SignalStatus.CANDIDATE
    else:
        status = SignalStatus.NEAR_KEY_LEVEL
    tp1 = min(target_2r, resistance.price - 0.1 * atr) if resistance else target_2r
    higher_resistance = next(
        (x for x in levels if x.kind == "resistance" and x.price > tp1 + atr), None
    )
    tp2 = (
        min(target_3r, higher_resistance.price - 0.1 * atr)
        if higher_resistance
        else (target_3r if resistance is None else None)
    )
    if status in {SignalStatus.NO_TRADE, SignalStatus.WATCH}:
        return HorizonPlan(
            horizon=horizon,
            status=status,
            strategy=strategy,
            timeframes=frames,
            reasons=reasons,
            invalidation=["trend or data quality deteriorates"],
        )
    if tp2 is None or tp2 < target_2r:
        status = SignalStatus.NEAR_KEY_LEVEL
        reasons.append("TP2 cannot be placed honestly; signal downgraded")
    return HorizonPlan(
        horizon=horizon,
        status=status,
        direction="long",
        strategy=strategy,
        timeframes=frames,
        entry=snapshot.price,
        stop=stop,
        take_profit_1=tp1,
        take_profit_2=tp2,
        reward_risk_1=(tp1 - snapshot.price) / risk,
        reward_risk_2=(tp2 - snapshot.price) / risk if tp2 else None,
        position_fraction=min(
            config.risk.maximum_position_fraction,
            config.risk.risk_per_trade / (risk / snapshot.price),
        )
        * profile.position_multiplier,
        reasons=reasons,
        invalidation=[f"close below {stop:.8g}"],
    )


def evaluate_setup_at_time(
    snapshot: MarketSnapshot,
    config: AppConfig,
    profile_name: str = "auto",
) -> AnalysisReport:
    """Public evaluation entry point used unchanged by analyze and backtest."""
    profile = get_profile(profile_name, snapshot.symbol)
    scores = _scores(snapshot, profile)
    available_aux = sum(
        snapshot.auxiliary.get(name) is not None
        and snapshot.auxiliary[name].status == Availability.AVAILABLE
        and (
            snapshot.auxiliary[name].observed_at is None
            or snapshot.auxiliary[name].observed_at <= snapshot.as_of
        )
        for name in profile.context_fields
    )
    completeness = available_aux / max(1, len(profile.context_fields))
    confidence = min(
        profile.confidence_cap,
        scores.technical * 0.55
        + scores.relative_strength * 0.12
        + scores.derivatives * 0.1
        + scores.onchain * 0.08
        + scores.macro * 0.08
        + scores.asset_specific * 0.07,
    )
    confidence *= 0.85 + 0.15 * completeness
    levels = _levels(snapshot, config)
    required = _required_failures(snapshot)
    hard_filters = profile.hard_filters(snapshot)
    plans = {
        horizon: _plan(
            horizon, snapshot, levels, confidence, profile, config, bool(required or hard_filters)
        )
        for horizon in Horizon
    }
    events: list[AnalysisEvent] = []
    for horizon, plan in plans.items():
        digest = hashlib.sha256(
            f"{snapshot.symbol}|{snapshot.as_of.isoformat()}|{horizon}|{plan.status}".encode()
        ).hexdigest()[:20]
        events.append(
            AnalysisEvent(
                event_id=digest,
                event_type=plan.status,
                symbol=snapshot.symbol,
                horizon=horizon,
                occurred_at=snapshot.as_of,
                payload={"confidence": round(confidence, 2), "profile": profile.name},
            )
        )
    availability = {
        "current_price": DataPoint(
            status=Availability.AVAILABLE,
            source="market_snapshot",
            observed_at=snapshot.as_of,
            freshness_seconds=0,
            value=snapshot.price,
        ),
        "trading_rules": snapshot.trading_rules,
        "timestamp": snapshot.timestamp,
        "volume": snapshot.volume,
        **snapshot.auxiliary,
    }
    for frame in ("1w", "1d", "4h", "1h", "15m"):
        bars = snapshot.completed(frame)
        availability[f"candles:{frame}"] = DataPoint(
            status=Availability.AVAILABLE if bars else Availability.NOT_AVAILABLE,
            source="market_snapshot",
            observed_at=bars[-1].close_time if bars else None,
            freshness_seconds=(
                max(0, (snapshot.as_of - bars[-1].close_time).total_seconds()) if bars else None
            ),
            value={"bars": len(bars)},
        )
    warnings = [f"required data unavailable: {name}" for name in required]
    warnings += [f"hard filter: {name}" for name in hard_filters]
    missing_context = [name for name in profile.context_fields if name not in snapshot.auxiliary]
    return AnalysisReport(
        generated_at=snapshot.as_of,
        profile=profile.name,
        market={
            "symbol": snapshot.symbol,
            "price": snapshot.price,
            "as_of": snapshot.as_of,
            "venue": "binance_spot",
        },
        data_availability=availability,
        scores=scores,
        confidence=round(confidence, 2),
        key_levels=levels,
        relative_strength={"score": scores.relative_strength},
        plans=plans,
        events=events,
        chart_data={},
        warnings=warnings,
        limitations=["research output; no profit guarantee"]
        + [f"missing context: {x}" for x in missing_context],
        hard_filters=hard_filters,
    )


def analyze_snapshot(
    snapshot: MarketSnapshot, config: AppConfig, profile: str = "auto"
) -> AnalysisReport:
    return evaluate_setup_at_time(snapshot, config, profile)
