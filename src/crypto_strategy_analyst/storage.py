"""Small crash-safe JSON/JSONL stores used by paper trading and journals."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_json_write(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_suffix(target.suffix + ".bak")
    if target.exists():
        backup.write_bytes(target.read_bytes())
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def append_jsonl(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        file_lock(target.with_suffix(target.suffix + ".lock")),
        target.open("a", encoding="utf-8") as handle,
    ):
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_json(path: str | Path, default: dict[str, Any]) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return default
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        backup = target.with_suffix(target.suffix + ".bak")
        if backup.exists():
            try:
                value = json.loads(backup.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else default
            except (OSError, json.JSONDecodeError):
                pass
        return default
