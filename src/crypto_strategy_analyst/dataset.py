"""Reproducible directory datasets with file hashes and manifest metadata."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .models import Candle, DataPoint, MarketSnapshot


def _version() -> str:
    return __version__


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_dataset(snapshot: MarketSnapshot, directory: str | Path) -> Path:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for timeframe, bars in snapshot.candles.items():
        path = target / f"{timeframe}.json"
        path.write_text(
            json.dumps([bar.model_dump(mode="json") for bar in bars], indent=2), encoding="utf-8"
        )
        files[path.name] = _digest(path)
    auxiliary = target / "auxiliary.json"
    auxiliary.write_text(
        json.dumps(
            {name: point.model_dump(mode="json") for name, point in snapshot.auxiliary.items()},
            indent=2,
        ),
        encoding="utf-8",
    )
    files[auxiliary.name] = _digest(auxiliary)
    manifest = {
        "schema_version": 1,
        "symbol": snapshot.symbol,
        "exchange": snapshot.exchange,
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": snapshot.as_of.isoformat(),
        "data_source": "public_composite",
        "software_version": _version(),
        "price": snapshot.price,
        "timeframes": sorted(snapshot.candles),
        "time_range": {
            frame: {"start": bars[0].open_time.isoformat(), "end": bars[-1].close_time.isoformat()}
            for frame, bars in snapshot.candles.items()
            if bars
        },
        "files": files,
        "trading_rules": snapshot.trading_rules.model_dump(mode="json"),
    }
    manifest_path = target / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def load_dataset(directory: str | Path) -> MarketSnapshot:
    target = Path(directory)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        if _digest(target / name) != expected:
            raise ValueError(f"dataset hash mismatch: {name}")
    candles = {
        frame: [
            Candle.model_validate(item)
            for item in json.loads((target / f"{frame}.json").read_text())
        ]
        for frame in manifest["timeframes"]
    }
    auxiliary = {
        name: DataPoint.model_validate(item)
        for name, item in json.loads((target / "auxiliary.json").read_text()).items()
    }
    return MarketSnapshot(
        symbol=manifest["symbol"],
        exchange=manifest["exchange"],
        as_of=manifest["as_of"],
        price=manifest["price"],
        candles=candles,
        trading_rules=DataPoint.model_validate(manifest["trading_rules"]),
        auxiliary=auxiliary,
    )
