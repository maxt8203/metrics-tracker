"""Storage. A small get/put/list interface with a JSON backend for now.

Writes can pass the etag they read; if the record changed since, it raises
ConcurrencyError instead of overwriting."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Protocol

from tracker.config import Settings, env

TABLES = ("weeks", "checkins", "events", "settings", "tokens")


class ConcurrencyError(Exception):
    """The record changed since it was read."""


class Store(Protocol):
    def get(self, table: str, key: str) -> tuple[dict | None, str | None]: ...
    def put(self, table: str, key: str, value: dict, if_match: str | None = None) -> str: ...
    def list(self, table: str) -> dict[str, dict]: ...


class JsonStore:
    """One JSON file per table. Atomic replace on write; single-process safe."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, table: str) -> Path:
        if table not in TABLES:
            raise ValueError(f"unknown table {table!r}")
        return self.root / f"{table}.json"

    def _load(self, table: str) -> dict:
        p = self._path(table)
        return json.loads(p.read_text()) if p.exists() else {}

    def _save(self, table: str, data: dict) -> None:
        p = self._path(table)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
        os.replace(tmp, p)

    def get(self, table, key):
        rec = self._load(table).get(key)
        if rec is None:
            return None, None
        return rec["value"], rec["etag"]

    def put(self, table, key, value, if_match=None):
        with self._lock:
            data = self._load(table)
            current = data.get(key)
            if if_match is not None and (current is None or current["etag"] != if_match):
                raise ConcurrencyError(f"{table}/{key} changed since read")
            etag = uuid.uuid4().hex
            data[key] = {"value": value, "etag": etag}
            self._save(table, data)
            return etag

    def list(self, table):
        return {k: rec["value"] for k, rec in sorted(self._load(table).items())}


def open_store(root: str | None = None) -> Store:
    backend = env("TRACKER_STORE", "json")
    if backend != "json":
        raise NotImplementedError(f"store backend {backend!r} not built yet (Azure Tables is Phase A)")
    return JsonStore(root or env("TRACKER_DATA_DIR", "data"))


# typed helpers
def load_settings(store: Store) -> Settings:
    value, _ = store.get("settings", "current")
    return Settings.from_dict(value) if value else Settings()


def save_settings(store: Store, settings: Settings) -> None:
    settings.validate()
    _, etag = store.get("settings", "current")
    store.put("settings", "current", settings.to_dict(), if_match=etag)
