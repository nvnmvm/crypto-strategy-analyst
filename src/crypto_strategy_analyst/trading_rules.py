"""Public spot trading-rule normalization helpers."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


def floor_to_increment(value: float, increment: float) -> float:
    """Round a positive value down to an exchange tick or step without floats."""

    if value < 0 or increment <= 0:
        raise ValueError("value must be non-negative and increment must be positive")
    decimal_value = Decimal(str(value))
    decimal_increment = Decimal(str(increment))
    units = (decimal_value / decimal_increment).to_integral_value(rounding=ROUND_DOWN)
    return float(units * decimal_increment)
