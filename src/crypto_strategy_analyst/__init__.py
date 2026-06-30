"""Deterministic crypto spot strategy research package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("crypto-strategy-analyst")
except PackageNotFoundError:  # pragma: no cover - editable source without installation
    __version__ = "0.1.1"

__all__ = ["__version__"]
