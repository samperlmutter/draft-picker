from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


SCHEDULE_SCHEMA_VERSION = 1


class ScheduleUnavailable(ValueError):
    """No schedule source is configured or a recorded source is absent."""


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def league_rules_identity(league_rules: dict[str, Any]) -> str:
    """Return the stable identity used to key a prepared schedule cache."""
    return _digest(league_rules)


def _team(value: Any) -> str:
    return str(value or "").strip().upper()


def _week(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"schedule week is invalid: {value!r}") from exc
    if result < 1 or result > 18:
        raise ValueError(f"schedule week must be between 1 and 18: {result}")
    return result


def _weeks(value: Any, label: str) -> list[int]:
    if not isinstance(value, list):
        raise ValueError(f"schedule {label} must be an array")
    result = sorted({_week(item) for item in value})
    if len(result) != len(value):
        raise ValueError(f"schedule {label} must not contain duplicate weeks")
    return result


def _rating(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("matchup_delta", value.get("delta", value.get("rating")))
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"schedule matchup rating is invalid: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError("schedule matchup rating must be finite")
    return result


def _unit_ratings(team_ratings: Any, unit: str) -> dict[str, Any]:
    if not isinstance(team_ratings, dict):
        return {}
    selected = team_ratings.get(unit)
    if selected is None and unit == "defense":
        selected = team_ratings.get("defence")
    if isinstance(selected, dict):
        return selected
    # A flat team rating map is a useful fixture shorthand for offensive
    # matchup ratings. It remains normalized as defensive input.
    if not any(key in team_ratings for key in ("offense", "defense", "defence")):
        return team_ratings
    return {}


def _position_rating(
    ratings: dict[str, Any], opponent: str, position: str
) -> tuple[float | None, str]:
    opponent_ratings = ratings.get(opponent) or {}
    is_defense = position in {"DEF", "DST"}
    unit = "offense" if is_defense else "defense"
    values = _unit_ratings(opponent_ratings, unit)
    candidates = [position]
    if is_defense:
        candidates += ["DEF", "DST"]
    if position == "K":
        candidates += ["ALL", "FLEX"]
    candidates += ["ALL", "FLEX", "default"]
    for candidate in candidates:
        if candidate in values:
            return _rating(values[candidate]), unit
    return None, unit


def _summary(items: list[dict[str, Any]], weeks: list[int]) -> dict[str, Any]:
    deltas = [item["matchup_delta"] for item in items if item["matchup_delta"] is not None]
    games = sum(not item["bye"] for item in items)
    missing = sum(not item["bye"] and item["matchup_delta"] is None for item in items)
    return {
        "weeks": weeks,
        "games": games,
        "byes": len(items) - games,
        "rated_games": len(deltas),
        "missing_ratings": missing,
        "average_matchup_delta": round(sum(deltas) / len(deltas), 6) if deltas else None,
        "matchup_delta_total": round(sum(deltas), 6),
    }


def _raw_games(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_games = payload.get("games")
    if not isinstance(raw_games, list) or not raw_games:
        raise ValueError("schedule source must contain a non-empty games array")
    games: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for index, raw in enumerate(raw_games):
        if not isinstance(raw, dict):
            raise ValueError(f"schedule game {index} must be an object")
        week = _week(raw.get("week"))
        home = _team(raw.get("home_team", raw.get("home")))
        away = _team(raw.get("away_team", raw.get("away")))
        if not home or not away or home == away:
            raise ValueError(f"schedule game {index} must contain two different teams")
        for team in (home, away):
            key = (week, team)
            if key in seen:
                raise ValueError(f"team {team} has multiple games in schedule week {week}")
            seen.add(key)
        games.append({
            "game_id": str(raw.get("game_id", raw.get("id", f"{week}-{home}-{away}"))),
            "week": week,
            "home_team": home,
            "away_team": away,
        })
    return sorted(games, key=lambda item: (item["week"], item["home_team"], item["away_team"]))


def _playoff_weeks(payload: dict[str, Any], league_rules: dict[str, Any], weeks: list[int]) -> list[int]:
    if "playoff_weeks" in payload:
        result = _weeks(payload["playoff_weeks"], "playoff_weeks")
    else:
        start = league_rules.get("playoff_week_start")
        if start is None:
            return []
        start = _week(start)
        rounds = int(league_rules.get("playoff_rounds") or 3)
        if rounds < 1 or rounds > 4:
            raise ValueError("League Rules playoff_rounds must be between 1 and 4")
        result = list(range(start, start + rounds))
    unknown = sorted(set(result) - set(weeks))
    if unknown:
        raise ValueError(f"schedule playoff weeks are not present in the schedule: {unknown}")
    return result


def build_schedule_snapshot(
    payload: Any,
    players: dict[str, dict[str, Any]],
    league_rules: dict[str, Any],
    *,
    season: int,
    clock: Callable[[], float],
    source_url: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("schedule source must be an object")
    try:
        source_season = int(payload.get("season", season))
    except (TypeError, ValueError) as exc:
        raise ValueError("schedule source season is invalid") from exc
    if source_season != int(season):
        raise ValueError(f"schedule source is for season {source_season}, expected {season}")
    if not isinstance(players, dict):
        raise ValueError("schedule snapshot requires a player map")
    if not isinstance(league_rules, dict):
        raise ValueError("schedule snapshot requires League Rules")
    ratings = payload.get("opponent_ratings", payload.get("matchup_ratings", payload.get("ratings")))
    if not isinstance(ratings, dict) or not ratings:
        raise ValueError("schedule source must contain opponent_ratings")

    games = _raw_games(payload)
    game_weeks = sorted({game["week"] for game in games})
    playoff_weeks = _playoff_weeks(payload, league_rules, game_weeks)
    if "regular_season_weeks" in payload:
        regular_weeks = _weeks(payload["regular_season_weeks"], "regular_season_weeks")
    else:
        regular_weeks = [week for week in game_weeks if week not in playoff_weeks]
    if set(regular_weeks) & set(playoff_weeks):
        raise ValueError("schedule regular-season and playoff weeks must be disjoint")
    all_weeks = sorted(set(regular_weeks) | set(playoff_weeks))
    if not all_weeks:
        raise ValueError("schedule source must contain at least one season week")

    teams = {_team(team) for team in payload.get("teams", []) if _team(team)}
    teams.update({team for game in games for team in (game["home_team"], game["away_team"])})
    player_inputs: dict[str, dict[str, str]] = {}
    for player_id, player in players.items():
        if not isinstance(player, dict):
            raise ValueError(f"schedule player {player_id} must be an object")
        team = _team(player.get("team"))
        position = str(player.get("position") or "").strip().upper()
        if team and position:
            teams.add(team)
            player_inputs[str(player_id)] = {"team": team, "position": position}

    by_team_week: dict[tuple[str, int], dict[str, Any]] = {}
    collisions: dict[str, list[int]] = {}
    for game in games:
        home, away, week = game["home_team"], game["away_team"], game["week"]
        by_team_week[(home, week)] = {"opponent": away, "home": True, "game_id": game["game_id"]}
        by_team_week[(away, week)] = {"opponent": home, "home": False, "game_id": game["game_id"]}
        key = "|".join(sorted((home, away)))
        collisions.setdefault(key, []).append(week)
    for weeks in collisions.values():
        weeks.sort()

    team_schedule: dict[str, dict[str, dict[str, Any]]] = {}
    bye_weeks: dict[str, list[int]] = {}
    for team in sorted(teams):
        team_schedule[team] = {}
        bye_weeks[team] = []
        for week in all_weeks:
            game = by_team_week.get((team, week))
            if game is None:
                bye_weeks[team].append(week)
            else:
                team_schedule[team][str(week)] = deepcopy(game)

    player_matchups: dict[str, dict[str, dict[str, Any]]] = {}
    player_summaries: dict[str, dict[str, Any]] = {}
    missing_ratings: list[dict[str, Any]] = []
    for player_id, player in sorted(player_inputs.items()):
        weekly: dict[str, dict[str, Any]] = {}
        for week in all_weeks:
            game = by_team_week.get((player["team"], week))
            if game is None:
                weekly[str(week)] = {"week": week, "bye": True, "opponent": None, "home": None, "matchup_delta": 0.0}
                continue
            delta, unit = _position_rating(ratings, game["opponent"], player["position"])
            if delta is None:
                missing_ratings.append({"player_id": player_id, "week": week, "opponent": game["opponent"], "unit": unit, "position": player["position"]})
            weekly[str(week)] = {"week": week, "bye": False, "opponent": game["opponent"], "home": game["home"], "game_id": game["game_id"], "matchup_delta": delta}
        player_matchups[player_id] = weekly
        regular_items = [weekly[str(week)] for week in regular_weeks]
        playoff_items = [weekly[str(week)] for week in playoff_weeks]
        player_summaries[player_id] = {
            "regular_season": _summary(regular_items, regular_weeks),
            "playoffs": _summary(playoff_items, playoff_weeks),
        }

    normalized_ratings = {
        _team(team): deepcopy(value) for team, value in ratings.items() if _team(team)
    }
    source = {
        "name": str(payload.get("source") or "configured-schedule"),
        "updated_at": payload.get("source_updated_at", payload.get("updated_at")),
    }
    if source_url:
        source["url"] = source_url
    league_rules_copy = deepcopy(league_rules)
    input_checksum = _digest({
        "season": season,
        "payload": payload,
        "players": player_inputs,
        "league_rules": league_rules_copy,
    })
    quality = "complete" if not missing_ratings else "partial"
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "updated_at": clock(),
        "season": int(season),
        "league_rules": league_rules_copy,
        "league_rules_identity": league_rules_identity(league_rules_copy),
        "source": source,
        "source_updated_at": source.get("updated_at"),
        "input_checksum": input_checksum,
        "regular_season_weeks": regular_weeks,
        "playoff_weeks": playoff_weeks,
        "teams": sorted(teams),
        "team_schedule": team_schedule,
        "bye_weeks": bye_weeks,
        "opponent_ratings": normalized_ratings,
        "player_matchups": player_matchups,
        "player_schedule_summaries": player_summaries,
        "team_collisions": collisions,
        "data_quality": {"status": quality, "missing_ratings": missing_ratings},
    }


def validate_schedule_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != SCHEDULE_SCHEMA_VERSION:
        raise ValueError("schedule snapshot must be a schema-version 1 object")
    required = ("season", "league_rules_identity", "input_checksum", "team_schedule", "bye_weeks", "player_matchups", "player_schedule_summaries", "team_collisions", "source")
    missing = [field for field in required if field not in snapshot]
    if missing:
        raise ValueError(f"schedule snapshot is missing {', '.join(missing)}")
    try:
        season = int(snapshot["season"])
    except (TypeError, ValueError) as exc:
        raise ValueError("schedule snapshot season is invalid") from exc
    if season < 2000:
        raise ValueError("schedule snapshot season is invalid")
    if not isinstance(snapshot["league_rules_identity"], str) or not snapshot["league_rules_identity"]:
        raise ValueError("schedule snapshot League Rules identity is invalid")
    for field in ("team_schedule", "bye_weeks", "player_matchups", "player_schedule_summaries", "team_collisions", "source"):
        if not isinstance(snapshot[field], dict):
            raise ValueError(f"schedule snapshot {field} must be an object")
    for key, weeks in snapshot["team_collisions"].items():
        if not isinstance(key, str) or "|" not in key or not isinstance(weeks, list) or any(not isinstance(week, int) for week in weeks):
            raise ValueError("schedule snapshot team collisions are invalid")
    quality = snapshot.get("data_quality", {})
    if not isinstance(quality, dict) or quality.get("status") not in {"complete", "partial"}:
        raise ValueError("schedule snapshot data quality is invalid")
    return snapshot


def fetch_schedule_payload(config: Any, season: int, client: Any = None) -> tuple[Any, str | None]:
    schedule_method = getattr(client, "schedule", None)
    if callable(schedule_method):
        return schedule_method(season), None

    fixtures = os.environ.get("DRAFT_ADVISOR_FIXTURES")
    if fixtures:
        root = Path(fixtures)
        for filename in (f"schedule__{season}.json", "schedule.json"):
            path = root / filename
            if path.exists():
                try:
                    return json.loads(path.read_text()), None
                except json.JSONDecodeError as exc:
                    raise ValueError(f"recorded schedule response is invalid: {filename}") from exc
        raise ScheduleUnavailable(f"recorded schedule response is missing: schedule__{season}.json")

    configured_url = getattr(config, "schedule_source_url", None) or os.environ.get("DRAFT_ADVISOR_SCHEDULE_URL")
    if not configured_url:
        raise ScheduleUnavailable("no schedule source is configured")
    url = configured_url.format(season=season)
    request = urllib.request.Request(url, headers={"User-Agent": "draft-advisor/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response), url
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(f"schedule request failed: {exc}") from exc
