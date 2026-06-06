"""Durable last-seen state so restarts don't re-alert or miss transitions.

Stored as a single JSON file written atomically (temp file + os.replace) so a
crash mid-write can't corrupt it.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import ROOT
from .models import Status

STATE_FILE = ROOT / "state.json"


class StateStore:
    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        self._data: dict[str, dict[str, str]] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, target_name: str) -> dict[str, Status]:
        raw = self._data.get(target_name, {})
        return {k: Status(v) for k, v in raw.items()}

    def set(self, target_name: str, snapshot_map: dict[str, Status]) -> None:
        self._data[target_name] = {k: v.value for k, v in snapshot_map.items()}
        self._flush()

    # Generic string-keyed storage, used by the discovery watcher to remember
    # which event IDs it has already seen (id -> title).
    def has(self, key: str) -> bool:
        """Whether a key was ever recorded (distinguishes a stored-empty
        baseline from a never-initialised one)."""
        return key in self._data

    def get_raw(self, key: str) -> dict[str, str]:
        return dict(self._data.get(key, {}))

    def set_raw(self, key: str, mapping: dict[str, str]) -> None:
        self._data[key] = dict(mapping)
        self._flush()

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
