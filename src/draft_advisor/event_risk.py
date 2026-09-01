from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


EVENT_SCHEMA_VERSION = 1
EVENT_TYPES = {
    "availability", "suspension", "team_change", "role_change", "workload_change",
}
IMPACT_TIERS = {"none": 0, "material": 1, "severe": 2}
EVALUATION_CAP = 0.10
MATERIAL_ADJUSTMENT = -0.03
SEVERE_ADJUSTMENT = -0.08
SCHEDULE_SIGNAL_CAP = 6.0


def _timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None


def _norm(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _source_name(value: Any) -> str:
    raw = _norm(value)
    return {
        "team": "official_team",
        "officialteam": "official_team",
        "nfl": "official_nfl",
        "officialnfl": "official_nfl",
        "sleeper": "sleeper",
    }.get(raw, str(value or "").strip().lower().replace(" ", "_"))


def _authority(event_type: str, source: str) -> int:
    if event_type == "availability":
        return 3 if source in {"sleeper", "official_team", "official_nfl"} else 0
    if event_type == "suspension":
        return 3 if source in {"official_team", "official_nfl"} else 0
    if event_type in {"team_change", "role_change", "workload_change"}:
        return 3 if source in {"official_team", "official_nfl"} else 0
    return 0


def _tier(value: Any) -> str:
    normalized = _norm(value)
    if normalized in {"severe", "high", "major"}:
        return "severe"
    if normalized in {"material", "moderate", "medium"}:
        return "material"
    if normalized in {"none", "low", "minor", ""}:
        return "none"
    raise ValueError(f"event impact tier is invalid: {value!r}")


def read_event_packet(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Read a pre-draft/day-of research packet without assigning football meaning."""
    raw_path = path or os.environ.get("DRAFT_ADVISOR_EVENT_SOURCE")
    if not raw_path:
        return []
    source_path = Path(raw_path)
    try:
        payload = json.loads(source_path.read_text())
    except FileNotFoundError as exc:
        raise ValueError(f"research event packet is missing: {source_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"research event packet is invalid: {source_path}") from exc
    if isinstance(payload, dict):
        payload = payload.get("events", payload.get("items", []))
    if not isinstance(payload, list):
        raise ValueError("research event packet must contain an events array")
    return payload


def _normalize_events(events: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(events):
        if not isinstance(raw, dict):
            raise ValueError(f"research event {index} must be an object")
        player_id = str(raw.get("player_id") or "")
        event_type = _norm(raw.get("event_type"))
        event_type = {
            "availability": "availability",
            "suspension": "suspension",
            "teamchange": "team_change",
            "rolechange": "role_change",
            "workloadchange": "workload_change",
        }.get(event_type, "")
        source = _source_name(raw.get("source"))
        observed_at = _timestamp(raw.get("observed_at"))
        effective_at = _timestamp(raw.get("effective_at"))
        expires_at = _timestamp(raw.get("expires_at"))
        if not player_id or event_type not in EVENT_TYPES or not raw.get("summary") or not source or not raw.get("evidence_url"):
            raise ValueError(f"research event {index} is missing required fields")
        if observed_at is None:
            raise ValueError(f"research event {index} has an invalid observed_at")
        if effective_at is not None and effective_at > now:
            continue
        if expires_at is not None and expires_at <= now:
            continue
        authority = _authority(event_type, source)
        tier = _tier(raw.get("impact_tier"))
        if authority == 0 or tier == "none":
            continue
        item = {
            "player_id": player_id,
            "event_type": event_type,
            "impact_tier": tier,
            "summary": str(raw["summary"]).strip(),
            "observed_at": raw["observed_at"],
            "observed_timestamp": observed_at,
            "effective_at": raw.get("effective_at"),
            "expires_at": raw.get("expires_at"),
            "source": source,
            "evidence_url": str(raw["evidence_url"]),
            "source_authority": authority,
            "_sequence": index,
        }
        item["event_id"] = _digest({key: item[key] for key in (
            "player_id", "event_type", "impact_tier", "summary", "observed_at", "source", "evidence_url",
        )})
        normalized.append(item)
    return normalized


def _sleeper_events(risk_snapshot: dict[str, Any], now: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for player_id, item in (risk_snapshot.get("players") or {}).items():
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "unknown")
        if state in {"unknown", "stale", "under_review"}:
            continue
        tier = "severe" if state in {"unavailable", "suspended", "exempt"} else "material" if state == "limited" else "none"
        if tier == "none":
            continue
        observations = item.get("observations") or []
        selected = observations or [{
            "source": "sleeper", "evidence_url": "https://api.sleeper.app/v1/players/nfl",
            "observed_at": now, "raw_status": state,
        }]
        for index, observation in enumerate(selected):
            if not isinstance(observation, dict):
                continue
            observed = observation.get("observed_timestamp", observation.get("observed_at"))
            timestamp = _timestamp(observed)
            if timestamp is None:
                continue
            result.append({
                "player_id": str(player_id),
                "event_type": "suspension" if state in {"suspended", "exempt"} else "availability",
                "impact_tier": tier,
                "summary": f"Sleeper designation: {observation.get('raw_status') or state}",
                "observed_at": observation.get("observed_at", observed),
                "observed_timestamp": timestamp,
                "effective_at": observation.get("effective_at"),
                "expires_at": None,
                "source": "sleeper",
                "evidence_url": observation.get("evidence_url") or "https://api.sleeper.app/v1/players/nfl",
                "source_authority": 3,
                "_sequence": index,
                "event_id": observation.get("observation_id") or _digest({"player_id": player_id, "state": state, "observed": observed}),
            })
    return result


def _select_events(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault((event["player_id"], event["event_type"]), []).append(event)
    selected: dict[str, list[dict[str, Any]]] = {}
    for (player_id, _event_type), candidates in grouped.items():
        winner = max(candidates, key=lambda item: (item["observed_timestamp"], item["source_authority"], item.get("_sequence", -1)))
        selected.setdefault(player_id, []).append(winner)
    return selected


def _schedule_detail(schedule: dict[str, Any] | None, player_id: str) -> tuple[dict[str, Any], str, float]:
    if not isinstance(schedule, dict) or (schedule.get("data_quality") or {}).get("status") != "complete":
        return {"data_quality": "unavailable", "regular_season": {}, "playoffs": {}}, "none", 0.0
    summaries = schedule.get("player_schedule_summaries") or {}
    summary = summaries.get(player_id)
    if not isinstance(summary, dict):
        return {"data_quality": "incomplete", "regular_season": {}, "playoffs": {}}, "none", 0.0
    regular = summary.get("regular_season") if isinstance(summary.get("regular_season"), dict) else {}
    playoffs = summary.get("playoffs") if isinstance(summary.get("playoffs"), dict) else {}
    regular_average = float(regular.get("average_matchup_delta") or 0.0)
    playoff_average = float(playoffs.get("average_matchup_delta") or 0.0)
    playoff_window = bool((schedule.get("league_rules") or {}).get("playoff_week_start") is not None)
    signal = regular_average + (2.0 * playoff_average if playoff_window else 0.0)
    signal = min(SCHEDULE_SIGNAL_CAP, max(-SCHEDULE_SIGNAL_CAP, signal))
    tier = "severe" if signal <= -4.0 else "material" if signal <= -2.0 else "none"
    return {
        "data_quality": "complete",
        "regular_season": deepcopy(regular),
        "playoffs": deepcopy(playoffs),
        "signal": round(signal, 3),
        "playoff_weight_applied": playoff_window,
    }, tier, signal


def _event_adjustment(tier: str) -> float:
    return {"none": 0.0, "material": MATERIAL_ADJUSTMENT, "severe": SEVERE_ADJUSTMENT}[tier]


def _max_tier(*tiers: str) -> str:
    return max(tiers, key=lambda tier: IMPACT_TIERS[tier])


def evaluate_schedule_event_risk(
    players: dict[str, Any],
    schedule: dict[str, Any] | None,
    risk_snapshot: dict[str, Any],
    research_events: list[dict[str, Any]] | None = None,
    *,
    phase: str,
    clock: Callable[[], float],
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if phase not in {"baseline", "day-of"}:
        raise ValueError("risk evaluation phase must be baseline or day-of")
    now = clock()
    active_events = _normalize_events(research_events or [], now) + _sleeper_events(risk_snapshot, now)
    events_by_player = _select_events(active_events)
    evaluated: dict[str, dict[str, Any]] = {}
    for player_id, player in players.items():
        if not isinstance(player, dict) or player.get("value") is None or not player.get("position"):
            continue
        player_id = str(player_id)
        schedule_detail, schedule_tier, signal = _schedule_detail(schedule, player_id)
        schedule_pct = round(min(EVALUATION_CAP, max(-EVALUATION_CAP, signal / SCHEDULE_SIGNAL_CAP * EVALUATION_CAP)), 6)
        selected_events = sorted(events_by_player.get(player_id, []), key=lambda item: item["event_id"])
        event_tier = "none"
        if selected_events:
            event_tier = _max_tier(*(event["impact_tier"] for event in selected_events))
        event_pct = _event_adjustment(event_tier)
        combined_pct = round(min(EVALUATION_CAP, max(-EVALUATION_CAP, schedule_pct + event_pct)), 6)
        overall_tier = _max_tier(schedule_tier, event_tier)
        evaluated[player_id] = {
            "player_id": player_id,
            "schedule_tier": schedule_tier,
            "event_tier": event_tier,
            "impact_tier": overall_tier,
            "schedule_adjustment_pct": schedule_pct,
            "event_adjustment_pct": event_pct,
            "combined_adjustment_pct": combined_pct,
            "schedule": schedule_detail,
            "events": [
                {key: event[key] for key in (
                    "event_id", "event_type", "impact_tier", "summary", "observed_at", "effective_at", "expires_at", "source", "evidence_url",
                )}
                for event in selected_events
            ],
            "reasons": [
                *([f"schedule {schedule_tier} impact"] if schedule_tier != "none" else []),
                *[event["summary"] for event in selected_events],
            ],
        }

    changes: list[dict[str, Any]] = []
    if phase == "day-of":
        if not isinstance(baseline, dict):
            raise ValueError("day-of evaluation requires a baseline evaluation")
        for player_id, current in evaluated.items():
            previous = (baseline.get("players") or {}).get(player_id)
            if not isinstance(previous, dict):
                continue
            adjustment_delta = abs(float(current["combined_adjustment_pct"]) - float(previous.get("combined_adjustment_pct", 0.0)))
            tier_changed = current["impact_tier"] != previous.get("impact_tier")
            material = tier_changed or adjustment_delta >= abs(MATERIAL_ADJUSTMENT)
            severe_change = tier_changed and (current["impact_tier"] == "severe" or previous.get("impact_tier") == "severe")
            if material or severe_change:
                changes.append({
                    "player_id": player_id,
                    "old_tier": previous.get("impact_tier", "none"),
                    "new_tier": current["impact_tier"],
                    "old_adjustment_pct": previous.get("combined_adjustment_pct", 0.0),
                    "new_adjustment_pct": current["combined_adjustment_pct"],
                    "reason": current["reasons"] or ["evaluation changed"],
                    "source": sorted({event["source"] for event in current["events"]}),
                })
        changes.sort(key=lambda item: (item["new_tier"] != "severe", item["player_id"]))
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "phase": phase,
        "generated_at": now,
        "player_count": len(evaluated),
        "players": evaluated,
        "changes": changes,
        "sources": sorted({event["source"] for event in active_events}),
        "schedule_source": (schedule or {}).get("source", {}),
        "evaluation_cap_pct": EVALUATION_CAP,
    }


def attach_evaluation(risk_snapshot: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(risk_snapshot)
    result["schedule_event_evaluation"] = deepcopy(evaluation)
    for player_id, item in evaluation.get("players", {}).items():
        if isinstance(result.get("players", {}).get(player_id), dict):
            result["players"][player_id]["event_evaluation"] = deepcopy(item)
    return result


def validate_evaluation(evaluation: Any) -> dict[str, Any]:
    if not isinstance(evaluation, dict) or evaluation.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ValueError("risk evaluation must be a schema-version 1 object")
    if evaluation.get("phase") not in {"baseline", "day-of"} or not isinstance(evaluation.get("players"), dict):
        raise ValueError("risk evaluation is incomplete")
    return evaluation
