"""Fail-closed order drafts, confirmation tokens and policy checks."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from ..config import AppConfig
from ..models import OrderDraft


class SafetyError(RuntimeError):
    pass


def create_draft(
    config: AppConfig, symbol: str, side: str, quantity: float, reference_price: float
) -> tuple[OrderDraft, str]:
    normalized = symbol.upper().replace("/", "").replace("-", "")
    if side.upper() not in {"BUY", "SELL"}:
        raise SafetyError("only spot BUY/SELL is supported")
    now = datetime.now(UTC)
    token = secrets.token_urlsafe(24)
    digest = hashlib.sha256(token.encode()).hexdigest()
    draft_id = secrets.token_hex(8)
    return OrderDraft(
        draft_id=draft_id,
        symbol=normalized,
        side=side.upper(),
        order_type="MARKET",
        quantity=quantity,
        reference_price=reference_price,
        notional=quantity * reference_price,
        client_order_id=f"csa-{draft_id}",
        created_at=now,
        expires_at=now + timedelta(seconds=config.trading.confirmation_ttl_seconds),
        confirmation_digest=digest,
    ), token


def validate_draft(config: AppConfig, draft: OrderDraft, token: str, current_price: float) -> None:
    trading = config.trading
    if not trading.trading_enabled:
        raise SafetyError("real trading is disabled")
    if trading.emergency_stop:
        raise SafetyError("emergency stop is active")
    if trading.futures_enabled:
        raise SafetyError("futures are prohibited")
    if not trading.require_human_confirmation:
        raise SafetyError("human confirmation is mandatory")
    if draft.symbol not in trading.symbol_whitelist:
        raise SafetyError("symbol is not whitelisted")
    if datetime.now(UTC) > draft.expires_at:
        raise SafetyError("confirmation expired")
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not hmac.compare_digest(digest, draft.confirmation_digest):
        raise SafetyError("invalid confirmation token")
    if draft.notional > min(
        config.risk.maximum_order_notional,
        config.risk.account_equity * config.risk.maximum_position_fraction,
    ):
        raise SafetyError("order exceeds configured risk limit")
    deviation = abs(current_price / draft.reference_price - 1)
    if deviation > trading.maximum_price_deviation:
        raise SafetyError("market price deviated beyond limit")
