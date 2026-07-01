"""Manual real-trade journal; it never places an order."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .storage import append_jsonl


def add_entry(path: str | Path, entry: dict[str, Any]) -> None:
    record = {"recorded_at": datetime.now(UTC).isoformat(), **entry}
    append_jsonl(path, record)


def read_entries(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    result = []
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                result.append(item)
        except json.JSONDecodeError:
            continue
    return result
