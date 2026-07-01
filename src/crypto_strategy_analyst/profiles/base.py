"""Profile contract and shared defaults."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import DataPoint, MarketSnapshot


@dataclass(frozen=True)
class AssetProfile:
    name: str
    context_fields: tuple[str, ...]
    hard_filter_fields: tuple[str, ...] = ()
    confidence_cap: float = 100
    position_multiplier: float = 1
    stop_atr: float = 1.8
    timeframe_weights: dict[str, float] = field(
        default_factory=lambda: {"1w": 0.25, "1d": 0.35, "4h": 0.25, "1h": 0.15}
    )

    def hard_filters(self, snapshot: MarketSnapshot) -> list[str]:
        blocked: list[str] = []
        for name in self.hard_filter_fields:
            point = snapshot.auxiliary.get(name)
            if (
                point
                and (point.observed_at is None or point.observed_at <= snapshot.as_of)
                and _severe(point)
            ):
                blocked.append(f"{name}:severe")
        return blocked


def _severe(point: DataPoint) -> bool:
    if isinstance(point.value, dict):
        return point.value.get("severity") in {"severe", "critical"}
    return str(point.value).lower() in {"severe", "critical", "halted"}
