from __future__ import annotations

import time
from typing import Any, Callable

from .config import Config
from .recommend import calculate
from .schedule import (
    ScheduleUnavailable,
    build_schedule_snapshot,
    fetch_schedule_payload,
    league_rules_identity,
    validate_schedule_snapshot,
)
from .sleeper import SleeperClient
from .storage import Storage
from .values import build_value_snapshot, validate_value_snapshot


def read_values(storage: Storage) -> dict[str, Any]:
    return storage.read_json(storage.values_path, "no player-value snapshot is available; refresh external data first")


def read_schedule(storage: Storage) -> dict[str, Any]:
    return validate_schedule_snapshot(
        storage.read_json(storage.schedule_path, "no schedule snapshot is available; configure a schedule source first")
    )


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


def _schedule_season(config: Config, state: dict[str, Any]) -> int:
    configured = config.season
    from_state = (state.get("league_rules") or {}).get("season")
    try:
        return int(configured or from_state or time.gmtime().tm_year)
    except (TypeError, ValueError) as exc:
        raise ValueError("schedule season is invalid") from exc


def refresh_schedule(
    config: Config,
    storage: Storage,
    state: dict[str, Any],
    value_snapshot: dict[str, Any],
    client: SleeperClient | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    season = _schedule_season(config, state)
    payload, source_url = fetch_schedule_payload(config, season, client)
    snapshot = validate_schedule_snapshot(build_schedule_snapshot(
        payload,
        value_snapshot["players"],
        state.get("league_rules") or {},
        season=season,
        clock=clock,
        source_url=source_url,
    ))
    storage.write_json(storage.schedule_path, snapshot)
    return snapshot


def ensure_schedule(
    config: Config,
    storage: Storage,
    state: dict[str, Any],
    value_snapshot: dict[str, Any],
    client: SleeperClient | None = None,
    force: bool = False,
    clock: Callable[[], float] = time.time,
) -> tuple[dict[str, Any] | None, bool]:
    try:
        previous = read_schedule(storage)
    except ValueError:
        previous = None
    season = _schedule_season(config, state)
    rules = state.get("league_rules") or {}
    cache_matches_inputs = (
        previous is not None
        and int(previous.get("season", 0)) == season
        and previous.get("league_rules_identity") == league_rules_identity(rules)
    )
    now = clock()
    if cache_matches_inputs and not force:
        age = now - float(previous.get("updated_at", 0))
        if age < config.schedule_refresh_interval_seconds:
            return previous, False
    try:
        return refresh_schedule(config, storage, state, value_snapshot, client, clock), True
    except ScheduleUnavailable:
        # Schedule intelligence is optional for the existing Draft Assistant;
        # the core value snapshot can still be prepared without it.
        return (previous if cache_matches_inputs else None), False
    except ValueError:
        # A malformed refresh must never replace a complete prior snapshot.
        if cache_matches_inputs:
            return previous, False
        raise


def recalculate(storage: Storage, state: dict[str, Any] | None = None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    recommendation = calculate(state or storage.read_state(), snapshot or read_values(storage))
    storage.write_json(storage.recommendation_path, recommendation)
    return recommendation


def read_recommendation(storage: Storage) -> dict[str, Any]:
    return storage.read_json(storage.recommendation_path, "no warm Recommendation is available; run prepare first")
