"""Structured JSON logging without secrets."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SAFE_EVENT_FIELDS = {
    "event_name",
    "timestamp",
    "symbol",
    "operation",
    "attempt",
    "duration_ms",
    "result",
    "error_type",
    "evaluation_time",
    "state_version",
    "command_id",
    "signal",
    "score",
    "bars",
}


class JsonFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload["data"] = {
                key: value for key, value in event_data.items() if key in SAFE_EVENT_FIELDS
            }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(log_dir: str | Path) -> Path:
    """Configure package logging and return the active log file."""

    directory = Path(log_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / f"strategy-{datetime.now(UTC):%Y%m%d}.jsonl"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    package_logger = logging.getLogger("crypto_strategy_analyst")
    package_logger.handlers.clear()
    package_logger.addHandler(handler)
    package_logger.setLevel(logging.INFO)
    package_logger.propagate = False
    return log_path
