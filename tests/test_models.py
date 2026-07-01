from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from crypto_strategy_analyst.models import Availability, Candle, DataPoint


def test_candle_validation():
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        Candle(
            open_time=now,
            close_time=now - timedelta(hours=1),
            open=1,
            high=2,
            low=0.5,
            close=1,
            volume=1,
        )
    with pytest.raises(ValidationError):
        Candle(
            open_time=now,
            close_time=now + timedelta(hours=1),
            open=1,
            high=0.8,
            low=0.5,
            close=1,
            volume=1,
        )


def test_completed_boundary(snapshot_factory):
    snapshot = snapshot_factory(future_spike=True)
    assert all(bar.close_time <= snapshot.as_of for bar in snapshot.completed("1h"))
    assert len(snapshot.completed("1h")) == 80


def test_strict_models_reject_unknown_field():
    with pytest.raises(ValidationError):
        DataPoint(status=Availability.AVAILABLE, source="x", surprise=True)
