from __future__ import annotations

import time
from typing import Any

from .config import Config
from .recommend import calculate
from .sleeper import SleeperClient
from .storage import Storage
from .values import build_value_snapshot, validate_value_snapshot


def read_values(storage: Storage) -> dict[str, Any]:
    return storage.read_json(storage.values_path, "no player-value snapshot is available; refresh external data first")


def refresh_values(storage: Storage, client: SleeperClient | None = None) -> dict[str, Any]:
    # Build and validate in memory; only a complete matched snapshot reaches disk.
    snapshot = validate_value_snapshot(build_value_snapshot(client))
    storage.write_json(storage.values_path, snapshot)
    return snapshot


def ensure_values(config: Config, storage: Storage, client: SleeperClient | None = None, force: bool = False) -> tuple[dict[str, Any], bool]:
    try:
        snapshot = read_values(storage)
    except ValueError:
        snapshot = None
    stale = snapshot is None or time.time() - float(snapshot["updated_at"]) >= config.external_refresh_interval_seconds
    if force or stale:
        return refresh_values(storage, client), True
    return snapshot, False


def recalculate(storage: Storage, state: dict[str, Any] | None = None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    recommendation = calculate(state or storage.read_state(), snapshot or read_values(storage))
    storage.write_json(storage.recommendation_path, recommendation)
    return recommendation


def read_recommendation(storage: Storage) -> dict[str, Any]:
    return storage.read_json(storage.recommendation_path, "no warm Recommendation is available; run prepare first")
