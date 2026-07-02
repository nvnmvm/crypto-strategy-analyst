"""Stable, machine-readable OpenClaw event construction."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from .models import Horizon, OpenClawEvent


def stable_key(
    event_type: str,
    symbol: str,
    profile: str,
    horizon: Horizon | None,
    condition: str,
) -> str:
    raw = "|".join((event_type, symbol, profile, horizon.value if horizon else "all", condition))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def make_event(
    event_type: str,
    symbol: str,
    profile: str,
    horizon: Horizon | None,
    occurred_at: datetime,
    condition: str,
    payload: dict[str, Any],
    severity: str = "info",
    ttl_hours: int = 24,
) -> OpenClawEvent:
    key = stable_key(event_type, symbol, profile, horizon, condition)
    return OpenClawEvent(
        event_id=hashlib.sha256(f"{key}|{occurred_at.isoformat()}".encode()).hexdigest()[:24],
        event_type=event_type,
        severity=severity,
        symbol=symbol,
        profile=profile,
        horizon=horizon,
        occurred_at=occurred_at,
        deduplication_key=key,
        expires_at=occurred_at + timedelta(hours=ttl_hours),
        payload=payload,
    )
