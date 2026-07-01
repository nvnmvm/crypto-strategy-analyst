"""Deterministic profile selection."""

from __future__ import annotations

from .base import AssetProfile
from .bnb import PROFILE as BNB
from .btc import PROFILE as BTC
from .eth import PROFILE as ETH
from .generic import PROFILE as GENERIC
from .sol import PROFILE as SOL

PROFILES = {profile.name: profile for profile in (BTC, ETH, BNB, SOL, GENERIC)}


def profile_for_symbol(symbol: str) -> AssetProfile:
    base = symbol.upper().replace("-", "/").replace("_", "/").split("/")[0]
    if base.endswith("USDT"):
        base = base[:-4]
    return PROFILES.get(base.lower(), GENERIC)


def get_profile(name: str, symbol: str) -> AssetProfile:
    if name == "auto":
        return profile_for_symbol(symbol)
    try:
        return PROFILES[name.lower()]
    except KeyError as exc:
        raise ValueError(f"unknown profile: {name}") from exc
