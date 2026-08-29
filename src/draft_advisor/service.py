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
    player_input_checksum,
    validate_schedule_snapshot,
)
from .sleeper import SleeperClient
from .storage import Storage
from .values import build_value_snapshot, validate_value_snapshot
from .risk import build_risk_snapshot, validate_authoritative_risk_snapshot, validate_risk


def validate_risk_fixture(storage: Storage, players: dict[str, Any], clock: Callable[[], float] = time.time) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run fixture-backed risk validation and publish only non-authoritative artifacts."""
    snapshot, report = validate_risk(players, clock=clock)
    with storage.publication_lock():
        storage.write_json(storage.risk_validation_path, snapshot)
        storage.write_json(storage.risk_validation_report_path, report)
    return snapshot, report


def refresh_risk(storage: Storage, players: dict[str, Any], clock: Callable[[], float] = time.time) -> dict[str, Any]:
    snapshot = validate_authoritative_risk_snapshot(build_risk_snapshot(players, clock=clock))
    with storage.publication_lock():
        storage.write_json(storage.risk_path, snapshot)
    return snapshot


def read_risk(storage: Storage) -> dict[str, Any] | None:
    try:
        return validate_authoritative_risk_snapshot(storage.read_json(storage.risk_path, "no risk snapshot is available"))
    except ValueError:
        return None


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
    if (snapshot.get("data_quality") or {}).get("status") != "complete":
        raise ValueError("schedule refresh is incomplete; preserving the last valid snapshot")
    rules_season = (state.get("league_rules") or {}).get("season")
    if rules_season is not None and int(snapshot["season"]) != int(rules_season):
        raise ValueError("schedule refresh season does not match current Draft State")
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
        and previous.get("input_checksum") == player_input_checksum(value_snapshot["players"])
        and (rules.get("season") is None or int(previous.get("season", 0)) == int(rules["season"]))
        and (previous.get("data_quality") or {}).get("status") == "complete"
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
        return (previous if cache_matches_inputs else None), False


def _schedule_matches_state(
    schedule: Any, state: dict[str, Any], snapshot: dict[str, Any] | None = None
) -> bool:
    if not isinstance(schedule, dict):
        return False
    rules = state.get("league_rules") or {}
    if schedule.get("league_rules_identity") != league_rules_identity(rules):
        return False
    current_season = rules.get("season")
    if current_season is None:
        current_season = (state.get("draft") or {}).get("season")
    if current_season is not None:
        try:
            if int(schedule.get("season")) != int(current_season):
                return False
        except (TypeError, ValueError):
            return False
    if snapshot is not None:
        players = snapshot.get("players")
        if not isinstance(players, dict):
            return False
        if schedule.get("input_checksum") != player_input_checksum(players):
            return False
    return True


def recalculate(
    storage: Storage,
    state: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_state = state or storage.read_state()
    current_snapshot = snapshot or read_values(storage)
    risk = read_risk(storage)
    if risk is not None:
        current_snapshot = dict(current_snapshot)
        current_snapshot["players"] = {pid: dict(player) for pid, player in current_snapshot["players"].items()}
        for pid, item in risk["players"].items():
            player = current_snapshot["players"].get(pid)
            if player is not None and item.get("state") in {"unavailable", "suspended", "limited", "under_review"}:
                player["injury_status"] = {"unavailable": "OUT", "suspended": "OUT", "limited": "QUESTIONABLE", "under_review": "QUESTIONABLE"}[item["state"]]
    if schedule is None:
        try:
            schedule = read_schedule(storage)
        except ValueError:
            # Schedule context is optional; the core Recommendation remains
            # available with neutral schedule components when it is absent or
            # malformed.
            schedule = None
    elif not _schedule_matches_state(schedule, current_state, current_snapshot):
        schedule = None
    if schedule is not None:
        try:
            schedule = validate_schedule_snapshot(schedule)
        except ValueError:
            schedule = None
        if schedule is not None and not _schedule_matches_state(schedule, current_state, current_snapshot):
            schedule = None
    recommendation = calculate(current_state, current_snapshot, schedule=schedule)
    storage.write_json(storage.recommendation_path, recommendation)
    return recommendation


def read_recommendation(storage: Storage) -> dict[str, Any]:
    return storage.read_json(storage.recommendation_path, "no warm Recommendation is available; run prepare first")
