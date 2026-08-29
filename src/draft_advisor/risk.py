from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

RISK_SCHEMA_VERSION = 1
RISK_PARSER = "draft-advisor-risk"
RISK_PARSER_VERSION = "1"
KNOWN_STATES = {"available", "limited", "unavailable", "suspended", "exempt", "under_review", "unknown", "stale"}
NEUTRAL_STATES = {"unknown", "stale", "under_review"}
DISCIPLINE_STATES = {"suspended", "exempt"}


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


def read_risk_source() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the recorded source once, retaining parser/source provenance."""
    return _source_payload(), {"kind": "fixture", "parser": RISK_PARSER, "parser_version": RISK_PARSER_VERSION}


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
    return stable, names


def validate_risk(players: dict[str, Any], observations: list[dict[str, Any]] | None = None, clock: Callable[[], float] = time.time) -> tuple[dict[str, Any], dict[str, Any]]:
    observations = _source_payload() if observations is None else observations
    stable, names = _identity_index(players)
    normalized: dict[str, dict[str, Any]] = {}
    review: list[dict[str, Any]] = []
    malformed = 0
    unmatched = 0
    ambiguous = 0
    for index, raw in enumerate(observations):
        source = str(raw.get("source") or "unknown")
        name_only = not any(raw.get(field) is not None for field in ("player_id", "sleeper_id", "gsis_id", "nfl_id"))
        candidate_ids: list[str] = []
        for field in ("player_id", "sleeper_id", "gsis_id", "nfl_id"):
            if raw.get(field) is not None:
                candidate_ids = stable.get(_norm(raw[field]), [])
                if candidate_ids:
                    break
        if not candidate_ids and raw.get("name"):
            candidate_ids = names.get(_norm(raw["name"]), [])
        if len(candidate_ids) != 1:
            reason = "ambiguous" if len(candidate_ids) > 1 else "unmatched"
            if reason == "ambiguous": ambiguous += 1
            else: unmatched += 1
            review.append({"observation_index": index, "source": source, "reason": reason, "name": raw.get("name"), "candidate_player_ids": sorted(candidate_ids)})
            continue
        observed_at = raw.get("observed_at") or raw.get("timestamp") or raw.get("published_at")
        if not observed_at:
            malformed += 1
            review.append({"observation_index": index, "source": source, "reason": "missing_timestamp"})
            continue
        state = _state(raw.get("state", raw.get("status")))
        evidence = {"source": source, "sources": [source], "source_tier": raw.get("source_tier", raw.get("tier")), "evidence_url": raw.get("evidence_url", raw.get("url")), "evidence_urls": [raw.get("evidence_url", raw.get("url"))] if raw.get("evidence_url", raw.get("url")) else [], "observed_at": observed_at, "effective_at": raw.get("effective_at", raw.get("effective_from")), "confidence": raw.get("confidence"), "raw_status": raw.get("status", raw.get("state")), "evidence_kind": str(raw.get("evidence_kind", raw.get("kind", "status"))).lower(), "high_impact": bool(raw.get("high_impact", raw.get("impact") == "high"))}
        evidence_id = hashlib.sha256(json.dumps({k: evidence[k] for k in ("source", "evidence_url", "observed_at", "raw_status")}, sort_keys=True, default=str).encode()).hexdigest()[:16]
        evidence["observation_id"] = evidence_id
        pid = candidate_ids[0]
        normalized.setdefault(pid, {"player_id": pid, "state": state, "observations": [], "provenance": []})
        item = normalized[pid]
        existing = next((x for x in item["observations"] if x["observation_id"] == evidence_id), None)
        if existing is not None:
            existing["sources"] = sorted(set(existing.get("sources", []) + [source]))
            existing["evidence_urls"] = sorted(set(existing.get("evidence_urls", []) + evidence["evidence_urls"]))
            item["provenance"] = sorted(set(item["provenance"] + [source]))
        else:
            item["observations"].append(evidence)
            item["provenance"].append(source)
            if item["state"] == "unknown" or state in {"suspended", "unavailable", "under_review"}:
                item["state"] = state
        if name_only:
            review.append({"observation_index": index, "source": source, "reason": "name_only", "player_id": pid})
    for pid in players:
        normalized.setdefault(str(pid), {"player_id": str(pid), "state": "unknown", "observations": [], "provenance": []})
    for item in normalized.values():
        item["provenance"] = sorted(set(item["provenance"]))
        item["observations"].sort(key=lambda x: x["observation_id"])
    report = {"schema_version": RISK_SCHEMA_VERSION, "status": "pass" if not (malformed or review) else "review", "player_count": len(players), "observation_count": len(observations), "matched_count": sum(bool(x["observations"]) for x in normalized.values()), "unmatched_count": unmatched, "ambiguous_count": ambiguous, "malformed_count": malformed, "review_count": len(review), "review": review}
    _add_review_queue(normalized, review, clock())
    report["review_count"] = len(review)
    report["status"] = "pass" if not (malformed or review) else "review"
    snapshot = {"schema_version": RISK_SCHEMA_VERSION, "phase": "validation", "authoritative": False, "generated_at": clock(), "players": normalized, "data_quality": report}
    return snapshot, report


def _add_review_queue(players: dict[str, dict[str, Any]], review: list[dict[str, Any]], now: float) -> None:
    """Attach a human queue; uncertain evidence is never converted to discipline."""
    for player in players.values():
        observations = player["observations"]
        states = { _state(o.get("raw_status")) for o in observations }
        if len(states - {"unknown"}) > 1:
            review.append({"player_id": player["player_id"], "reason": "conflicting_evidence", "candidate_states": sorted(states)})
        for observation in observations:
            kind = observation.get("evidence_kind")
            if kind in {"allegation", "rumor", "report", "fine"}:
                review.append({"player_id": player["player_id"], "reason": "weak_or_disciplinary_evidence", "observation_id": observation["observation_id"]})
            if observation.get("high_impact"):
                review.append({"player_id": player["player_id"], "reason": "high_impact", "observation_id": observation["observation_id"]})
            try:
                if now - float(observation["observed_at"]) > 30 * 86400:
                    review.append({"player_id": player["player_id"], "reason": "stale", "observation_id": observation["observation_id"]})
            except (TypeError, ValueError):
                pass
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
    result["authoritative"] = False
    return result


def validate_risk_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != RISK_SCHEMA_VERSION or snapshot.get("authoritative") is not False:
        raise ValueError("risk validation snapshot must be schema-version 1 and non-authoritative")
    if not isinstance(snapshot.get("players"), dict) or not isinstance(snapshot.get("data_quality"), dict):
        raise ValueError("risk validation snapshot is incomplete")
    return snapshot


def build_risk_snapshot(players: dict[str, Any], *, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    observations, source = read_risk_source()
    validated, report = validate_risk(players, observations, clock=clock)
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
