"""Reproducible local OHLCV dataset snapshots for offline backtests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pandas as pd

from .data import (
    INTERVAL_SECONDS,
    BinancePublicClient,
    drop_incomplete_last_bar,
    validate_market_data,
)
from .errors import DatasetIntegrityError
from .models import SymbolTradingRules

DATASET_TIMEFRAMES = ("1d", "4h", "1h")


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    frames: dict[str, pd.DataFrame]
    symbol: str
    dataset_hash: str
    trading_rules: SymbolTradingRules
    manifest: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_hash_for_files(
    files: Mapping[str, str],
    trading_rules: Mapping[str, Any],
) -> str:
    reproducible_rules = {
        key: trading_rules.get(key)
        for key in (
            "symbol",
            "price_tick_size",
            "quantity_step_size",
            "minimum_quantity",
            "maximum_quantity",
            "minimum_notional",
        )
    }
    canonical = json.dumps(
        {"files": dict(sorted(files.items())), "trading_rules": reproducible_rules},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dataset_hash_for_manifest(manifest: Mapping[str, Any]) -> str:
    """Hash every manifest field except the self-referential digest."""

    payload = {key: value for key, value in manifest.items() if key != "dataset_hash"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _package_version() -> str:
    source_version = Path(__file__).resolve().parents[2] / "VERSION"
    if source_version.is_file():
        return source_version.read_text(encoding="utf-8").strip()
    try:
        return version("crypto-strategy-analyst")
    except PackageNotFoundError:  # pragma: no cover
        return "0.1.3"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
        raise DatasetIntegrityError(f"failed to save dataset manifest: {path}") from exc


def fetch_dataset(
    client: BinancePublicClient,
    *,
    symbol: str,
    start: str | datetime,
    end: str | datetime,
    output_dir: str | Path,
) -> Path:
    """Download three public spot timeframes and write a checksummed manifest."""

    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    end_time = pd.Timestamp(end)
    end_time = end_time.tz_localize("UTC") if end_time.tzinfo is None else end_time.tz_convert("UTC")
    file_metadata: dict[str, dict[str, Any]] = {}
    trading_rules = client.fetch_symbol_trading_rules(symbol)
    for timeframe in DATASET_TIMEFRAMES:
        frame = client.fetch_klines(symbol, timeframe, start=start, end=end)
        frame = drop_incomplete_last_bar(frame, timeframe, now=end_time.to_pydatetime())
        quality = validate_market_data(frame, timeframe, minimum_bars=210)
        if quality.grade.value == "invalid":
            raise DatasetIntegrityError(
                f"downloaded {timeframe} data failed quality gate: {quality.model_dump()}"
            )
        path = directory / f"{timeframe}.csv"
        frame.to_csv(path, index_label="timestamp", float_format="%.12g")
        digest = sha256_file(path)
        first_open = pd.Timestamp(frame.index[0])
        last_open = pd.Timestamp(frame.index[-1])
        last_close = last_open + pd.to_timedelta(INTERVAL_SECONDS[timeframe], unit="s")
        file_metadata[timeframe] = {
            "file": path.name,
            "rows": len(frame),
            "sha256": digest,
            "first_open_time": first_open.isoformat(),
            "last_open_time": last_open.isoformat(),
            "last_close_time": last_close.isoformat(),
            "quality": quality.model_dump(mode="json"),
        }
    rules_payload = trading_rules.model_dump(mode="json")
    manifest = {
        "manifest_version": 2,
        "symbol": symbol.upper().replace("-", "/"),
        "exchange": "binance",
        "market": "spot",
        "start": pd.Timestamp(start).isoformat(),
        "end": end_time.isoformat(),
        "downloaded_at": datetime.now(UTC).isoformat(),
        "data_source": "Binance public spot REST /api/v3/klines and /api/v3/exchangeInfo",
        "software_version": _package_version(),
        "files": file_metadata,
        "trading_rules": rules_payload,
    }
    manifest["dataset_hash"] = dataset_hash_for_manifest(manifest)
    manifest_path = directory / "manifest.json"
    _write_json_atomic(manifest_path, manifest)
    return manifest_path


def _load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "timestamp" not in frame.columns:
        raise DatasetIntegrityError(f"dataset CSV lacks timestamp: {path}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.set_index("timestamp").sort_index()


def load_dataset(dataset_dir: str | Path) -> DatasetSnapshot:
    """Load an offline snapshot and fail closed if any CSV hash changed."""

    directory = Path(dataset_dir).expanduser().resolve()
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("manifest_version") != 2:
            raise ValueError("unsupported manifest_version")
        files = manifest["files"]
        frames: dict[str, pd.DataFrame] = {}
        for timeframe in DATASET_TIMEFRAMES:
            metadata = files[timeframe]
            path = directory / metadata["file"]
            digest = sha256_file(path)
            if digest != metadata["sha256"]:
                raise DatasetIntegrityError(f"dataset hash mismatch: {path}")
            frame = _load_frame(path)
            if len(frame) != metadata["rows"]:
                raise DatasetIntegrityError(f"dataset row count mismatch: {path}")
            expected_first = pd.Timestamp(metadata["first_open_time"])
            expected_last = pd.Timestamp(metadata["last_open_time"])
            if frame.index[0] != expected_first or frame.index[-1] != expected_last:
                raise DatasetIntegrityError(f"dataset time boundary mismatch: {path}")
            quality = validate_market_data(frame, timeframe, minimum_bars=210)
            if quality.grade.value == "invalid":
                raise DatasetIntegrityError(
                    f"offline {timeframe} data failed quality gate: {quality.model_dump()}"
                )
            frames[timeframe] = frame
        computed_hash = dataset_hash_for_manifest(manifest)
        if computed_hash != manifest["dataset_hash"]:
            raise DatasetIntegrityError("dataset manifest hash mismatch")
        trading_rules = SymbolTradingRules.model_validate(manifest["trading_rules"])
        return DatasetSnapshot(
            frames=frames,
            symbol=manifest["symbol"],
            dataset_hash=computed_hash,
            trading_rules=trading_rules,
            manifest=manifest,
        )
    except DatasetIntegrityError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DatasetIntegrityError(f"invalid dataset manifest: {manifest_path}") from exc
