from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .sleeper import SleeperClient

RISK_SCHEMA_VERSION = 1
RISK_PARSER = "draft-advisor-risk"
RISK_PARSER_VERSION = "1"
KNOWN_STATES = {"available", "limited", "unavailable", "suspended", "exempt", "under_review", "unknown", "stale"}
NEUTRAL_STATES = {"unknown", "stale", "under_review"}
DISCIPLINE_STATES = {"suspended", "exempt"}
PENALTY_STATES = {"unavailable", "suspended", "exempt"}
WEAK_EVIDENCE_KINDS = {"allegation", "rumor", "report", "fine", "investigation", "under_review"}
OVERRIDABLE_REVIEW_REASONS = {
    "conflicting_evidence", "weak_or_disciplinary_evidence", "high_impact",
    "stale", "unknown_status",
}


def risk_injury_status(state: Any) -> str | None:
    normalized = str(state or "unknown")
    return "OUT" if normalized in PENALTY_STATES else None


def risk_is_visible(state: Any) -> bool:
    return str(state or "unknown") in NEUTRAL_STATES


def _timestamp(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _source_payload() -> list[dict[str, Any]]:
    root = os.environ.get("DRAFT_ADVISOR_FIXTURES")
    if not root:
        return []
    directory = Path(root)
    paths = [directory / name for name in ("risk-observations.json", "risk.json", "player-risk.json")]
    paths += sorted(directory.glob("risk__*.json"))
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"risk source is malformed: {path.name}") from exc
        if isinstance(payload, dict):
            payload = payload.get("observations", payload.get("items", []))
        if not isinstance(payload, list):
            raise ValueError(f"risk source must contain an observations array: {path.name}")
        for row in payload:
            if not isinstance(row, dict):
                raise ValueError(f"risk observation is malformed: {path.name}")
            item = dict(row)
            item.setdefault("source", path.stem)
            rows.append(item)
    return rows


def _sleeper_payload(client: SleeperClient) -> list[dict[str, Any]]:
    """Convert one Sleeper player response into the risk observation format."""
    players = client.players()
    if not isinstance(players, dict) or not players:
        raise ValueError("Sleeper players response is unavailable or empty")

    observed_at = time.time()
    observations: list[dict[str, Any]] = []
    for player_id, player in players.items():
        if not isinstance(player, dict):
            raise ValueError("Sleeper players response contains a malformed player")
        # Sleeper's injury designation is more specific than its general status.
        raw_status = player.get("injury_status") or player.get("status")
        if raw_status in (None, ""):
            continue
        observations.append({
            "player_id": str(player_id),
            "status": raw_status,
            "observed_at": observed_at,
            "source": "sleeper",
            "source_tier": "sleeper",
            "confidence": 1.0,
            "evidence_kind": "status",
            "evidence_url": "https://api.sleeper.app/v1/players/nfl",
        })
    return observations


def read_risk_source(client: SleeperClient | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read fixtures when configured, otherwise read the live Sleeper source once."""
    if os.environ.get("DRAFT_ADVISOR_FIXTURES"):
        return _source_payload(), {"kind": "fixture", "parser": RISK_PARSER, "parser_version": RISK_PARSER_VERSION}
    observations = _sleeper_payload(client or SleeperClient())
    return observations, {
        "kind": "sleeper",
        "endpoint": "/players/nfl",
        "parser": RISK_PARSER,
        "parser_version": RISK_PARSER_VERSION,
    }


def _state(value: Any) -> str:
    raw = _norm(value)
    mapping = {
        "active": "available", "available": "available", "healthy": "available",
        "questionable": "limited", "limited": "limited", "doubtful": "limited",
        "out": "unavailable", "inactive": "unavailable", "injuredreserve": "unavailable",
        "unavailable": "unavailable", "suspended": "suspended", "suspension": "suspended",
        "exempt": "exempt", "commissionerexempt": "exempt", "investigation": "under_review",
        "underreview": "under_review", "review": "under_review", "unknown": "unknown",
    }
    return mapping.get(raw, "unknown")


def _identity_index(players: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    stable: dict[str, list[str]] = {}
    names: dict[str, list[str]] = {}
    for pid, player in players.items():
        pid = str(pid)
        for key in (pid, player.get("player_id"), player.get("sleeper_id"), player.get("gsis_id"), player.get("nfl_id")):
            if key:
                stable.setdefault(_norm(key), []).append(pid)
        name = player.get("full_name") or " ".join(filter(None, (player.get("first_name"), player.get("last_name"))))
        if name:
            names.setdefault(_norm(name), []).append(pid)
    return ({key: list(dict.fromkeys(value)) for key, value in stable.items()},
            {key: list(dict.fromkeys(value)) for key, value in names.items()})


def _known_status(value: Any) -> bool:
    return _norm(value) in {
        "active", "available", "healthy", "questionable", "limited", "doubtful",
        "out", "inactive", "injuredreserve", "unavailable", "suspended", "suspension",
        "exempt", "commissionerexempt", "investigation", "underreview", "review", "unknown",
    }


def _event_time(observation: dict[str, Any]) -> float:
    effective = _timestamp(observation.get("effective_at"))
    observed = observation.get("observed_timestamp")
    return max(value for value in (effective, observed) if value is not None) if effective is not None or observed is not None else float("-inf")


def _current_state(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return "unknown"
    latest = max(observations, key=lambda item: (_event_time(item), item.get("_sequence", -1)))
    return latest.get("normalized_state", _state(latest.get("raw_status")))


def _weekly_availability(observations: list[dict[str, Any]]) -> dict[str, str]:
    """Return the latest normalized state for each explicitly reported week."""
    result: dict[str, str] = {}
    for observation in sorted(observations, key=lambda item: (_event_time(item), item.get("_sequence", -1))):
        weeks = observation.get("weeks") or observation.get("week")
        if not isinstance(weeks, list):
            weeks = [weeks]
        for week in weeks:
            if week not in (None, ""):
                result[str(week)] = observation.get("normalized_state", "unknown")
    return dict(sorted(result.items()))


def validate_risk(players: dict[str, Any], observations: list[dict[str, Any]] | None = None, clock: Callable[[], float] = time.time) -> tuple[dict[str, Any], dict[str, Any]]:
    observations = _source_payload() if observations is None else observations
    stable, names = _identity_index(players)
    normalized: dict[str, dict[str, Any]] = {}
    review: list[dict[str, Any]] = []
    malformed = 0
    unknown_status = 0
    unmatched = 0
    ambiguous = 0
    for index, raw in enumerate(observations):
        if not isinstance(raw, dict):
            malformed += 1
            review.append({"observation_index": index, "reason": "malformed_observation"})
            continue
        source = str(raw.get("source") or "unknown")
        identifier_fields = ("player_id", "sleeper_id", "gsis_id", "nfl_id")
        supplied_ids = [raw[field] for field in identifier_fields if raw.get(field) not in (None, "")]
        name_only = not supplied_ids
        candidate_ids: list[str] = []
        for identifier in supplied_ids:
            candidate_ids.extend(stable.get(_norm(identifier), []))
        candidate_ids = list(dict.fromkeys(candidate_ids))
        if not candidate_ids and name_only and raw.get("name"):
            candidate_ids = names.get(_norm(raw["name"]), [])
        if len(candidate_ids) > 1:
            ambiguous += 1
            review.append({"observation_index": index, "source": source, "reason": "conflicting_identity" if supplied_ids else "ambiguous", "name": raw.get("name"), "candidate_player_ids": sorted(candidate_ids)})
            continue
        if name_only:
            unmatched += 1
            review.append({"observation_index": index, "source": source, "reason": "name_only", "name": raw.get("name"), "candidate_player_ids": sorted(candidate_ids)})
            continue
        if len(candidate_ids) != 1:
            reason = "ambiguous" if len(candidate_ids) > 1 else "unmatched"
            if reason == "ambiguous": ambiguous += 1
            else: unmatched += 1
            review.append({"observation_index": index, "source": source, "reason": reason, "name": raw.get("name"), "candidate_player_ids": sorted(candidate_ids)})
            continue
        observed_at = next((raw[field] for field in ("observed_at", "timestamp", "published_at") if raw.get(field) not in (None, "")), None)
        observed_timestamp = _timestamp(observed_at)
        if observed_at is None:
            malformed += 1
            review.append({"observation_index": index, "source": source, "reason": "missing_timestamp"})
            continue
        if observed_timestamp is None:
            malformed += 1
            review.append({"observation_index": index, "source": source, "reason": "invalid_timestamp", "observed_at": observed_at})
            continue
        raw_status = raw.get("state", raw.get("status"))
        state = _state(raw_status)
        if not _known_status(raw_status):
            unknown_status += 1
            review.append({"observation_index": index, "source": source, "reason": "unknown_status", "raw_status": raw_status})
        evidence_kind = str(raw.get("evidence_kind", raw.get("kind", "status"))).lower()
        if evidence_kind in WEAK_EVIDENCE_KINDS:
            state = "unknown"
        evidence = {"source": source, "sources": [source], "source_tier": raw.get("source_tier", raw.get("tier")), "evidence_url": raw.get("evidence_url", raw.get("url")), "evidence_urls": [raw.get("evidence_url", raw.get("url"))] if raw.get("evidence_url", raw.get("url")) else [], "observed_at": observed_at, "observed_timestamp": observed_timestamp, "effective_at": raw.get("effective_at", raw.get("effective_from")), "confidence": raw.get("confidence"), "raw_status": raw_status, "normalized_state": state, "week": raw.get("week"), "weeks": raw.get("weeks"), "evidence_kind": evidence_kind, "evidence_kinds": [evidence_kind], "high_impact": bool(raw.get("high_impact", raw.get("impact") == "high")), "_sequence": index}
        # Source is provenance, not identity: syndicated copies should collapse
        # into one observation while retaining every contributing source.
        evidence_id = hashlib.sha256(json.dumps({k: evidence[k] for k in ("evidence_url", "observed_at", "raw_status")}, sort_keys=True, default=str).encode()).hexdigest()[:16]
        evidence["observation_id"] = evidence_id
        pid = candidate_ids[0]
        normalized.setdefault(pid, {"player_id": pid, "state": state, "observations": [], "provenance": []})
        item = normalized[pid]
        existing = next((x for x in item["observations"] if x["observation_id"] == evidence_id), None)
        if existing is not None:
            existing["sources"] = sorted(set(existing.get("sources", []) + [source]))
            existing["evidence_urls"] = sorted(set(existing.get("evidence_urls", []) + evidence["evidence_urls"]))
            existing["evidence_kinds"] = sorted(set(existing.get("evidence_kinds", [existing.get("evidence_kind", "status")]) + [evidence_kind]))
            item["provenance"] = sorted(set(item["provenance"] + [source]))
        else:
            item["observations"].append(evidence)
            item["provenance"].append(source)
        item["state"] = _current_state(item["observations"])
        item["weekly_availability"] = _weekly_availability(item["observations"])
    for pid in players:
        normalized.setdefault(str(pid), {"player_id": str(pid), "state": "unknown", "observations": [], "provenance": [], "weekly_availability": {}})
    for item in normalized.values():
        item["provenance"] = sorted(set(item["provenance"]))
        item["observations"].sort(key=lambda x: x["observation_id"])
    report = {"schema_version": RISK_SCHEMA_VERSION, "status": "pass" if not (malformed or review) else "review", "player_count": len(players), "observation_count": len(observations), "matched_count": sum(bool(x["observations"]) for x in normalized.values()), "unmatched_count": unmatched, "ambiguous_count": ambiguous, "malformed_count": malformed, "unknown_status_count": unknown_status, "review_count": len(review), "review": review}
    _add_review_queue(normalized, review, clock())
    report["review_count"] = len(review)
    report["status"] = "pass" if not (malformed or review) else "review"
    snapshot = {"schema_version": RISK_SCHEMA_VERSION, "phase": "validation", "authoritative": False, "generated_at": clock(), "players": normalized, "data_quality": report}
    return snapshot, report


def _add_review_queue(players: dict[str, dict[str, Any]], review: list[dict[str, Any]], now: float) -> None:
    """Attach a human queue; uncertain evidence is never converted to discipline."""
    for player in players.values():
        observations = player["observations"]
        resolved = [
            observation for observation in observations
            if _state(observation.get("raw_status")) != "unknown"
        ]
        states = {_state(o.get("raw_status")) for o in resolved}
        if len(states) > 1:
            latest_time = max(_event_time(observation) for observation in resolved)
            latest_states = {
                _state(observation.get("raw_status"))
                for observation in resolved
                if _event_time(observation) == latest_time
            }
            if len(latest_states) > 1:
                review.append({"player_id": player["player_id"], "reason": "conflicting_evidence", "candidate_states": sorted(states)})
        for observation in observations:
            kinds = set(observation.get("evidence_kinds", [observation.get("evidence_kind")]))
            if kinds & WEAK_EVIDENCE_KINDS:
                review.append({"player_id": player["player_id"], "reason": "weak_or_disciplinary_evidence", "observation_id": observation["observation_id"]})
            if observation.get("high_impact"):
                review.append({"player_id": player["player_id"], "reason": "high_impact", "observation_id": observation["observation_id"]})
            observed = observation.get("observed_timestamp")
            if observed is not None and now - observed > 30 * 86400:
                observation["stale"] = True
                review.append({"player_id": player["player_id"], "reason": "stale", "observation_id": observation["observation_id"]})
        fresh = [observation for observation in observations if not observation.get("stale")]
        player["state"] = _current_state(fresh) if fresh else ("stale" if observations else player["state"])
        player["weekly_availability"] = _weekly_availability(fresh)
        if player["state"] in NEUTRAL_STATES:
            player.setdefault("review_reasons", []).append("unknown_or_stale")
    # de-duplicate queue entries while retaining order
    seen = set()
    unique = []
    for row in review:
        key = json.dumps(row, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    review[:] = unique


def apply_risk_overrides(snapshot: dict[str, Any], overrides: list[dict[str, Any]], now: float | None = None) -> dict[str, Any]:
    """Apply only active, dated, source-linked human decisions to a copy."""
    result = json.loads(json.dumps(snapshot))
    now = time.time() if now is None else now
    audit = result.setdefault("overrides", [])
    for override in overrides:
        pid = str(override.get("player_id", ""))
        if pid not in result.get("players", {}):
            raise ValueError("override references an unknown player")
        if not override.get("override_id") or not override.get("reason") or not override.get("source"):
            raise ValueError("override requires override_id, source, and reason")
        try:
            expires = float(override["expires_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("override requires a dated expires_at") from exc
        if expires <= now:
            continue
        state = _state(override.get("state"))
        if state in DISCIPLINE_STATES and str(override.get("evidence_kind", "decision")).lower() in {"allegation", "rumor", "fine"}:
            raise ValueError("weak evidence cannot create confirmed discipline")
        if state not in KNOWN_STATES:
            raise ValueError("override state is invalid")
        entry = dict(override, state=state, applied_at=now)
        result["players"][pid]["state"] = state
        audit.append(entry)
    quality = result.get("data_quality")
    if isinstance(quality, dict) and isinstance(quality.get("review"), list):
        active_players = {
            str(entry.get("player_id"))
            for entry in audit
            if float(entry.get("expires_at", 0)) > now
        }
        quality["review"] = [
            item for item in quality["review"]
            if not (
                item.get("reason") in OVERRIDABLE_REVIEW_REASONS
                and str(item.get("player_id", "")) in active_players
            )
        ]
        quality["review_count"] = len(quality["review"])
        quality["status"] = "pass" if not quality["review"] and not quality.get("malformed_count") else "review"
    result["authoritative"] = False
    return result


def validate_risk_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != RISK_SCHEMA_VERSION or snapshot.get("authoritative") is not False:
        raise ValueError("risk validation snapshot must be schema-version 1 and non-authoritative")
    if not isinstance(snapshot.get("players"), dict) or not isinstance(snapshot.get("data_quality"), dict):
        raise ValueError("risk validation snapshot is incomplete")
    return snapshot


def build_risk_snapshot(
    players: dict[str, Any],
    *,
    clock: Callable[[], float] = time.time,
    overrides: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    observations, source = read_risk_source()
    if not observations:
        raise ValueError("risk source is unavailable or empty; preserving the last valid snapshot")
    validated, report = validate_risk(players, observations, clock=clock)
    if overrides:
        validated = apply_risk_overrides(validated, overrides, now=clock())
        report = validated["data_quality"]
    if report["status"] != "pass":
        raise ValueError("risk refresh failed quality gates; preserving the last valid snapshot")
    now = clock()
    return {
        "schema_version": RISK_SCHEMA_VERSION,
        "phase": "authoritative",
        "authoritative": True,
        "generated_at": validated["generated_at"],
        "refreshed_at": now,
        "freshness": {"observed_at": now, "max_age_seconds": 1800},
        "source": source,
        "parser": {"name": RISK_PARSER, "version": RISK_PARSER_VERSION},
        "players": validated["players"],
        "data_quality": report,
        "overrides": validated.get("overrides", []),
    }


def validate_authoritative_risk_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != RISK_SCHEMA_VERSION or snapshot.get("authoritative") is not True or snapshot.get("phase") != "authoritative":
        raise ValueError("risk snapshot is not authoritative")
    for key in ("generated_at", "refreshed_at", "freshness", "source", "parser", "players", "data_quality"):
        if key not in snapshot:
            raise ValueError(f"risk snapshot is missing {key}")
    if snapshot["data_quality"].get("status") != "pass":
        raise ValueError("risk snapshot failed quality gates")
    return snapshot
