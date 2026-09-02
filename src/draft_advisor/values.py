from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .sleeper import SleeperClient
from .rules import LEGAL_POSITIONS, canonical_position


FANTASYCALC_URL = "https://api.fantasycalc.com/values/current?isDynasty=false&numQbs=1&numTeams=12&ppr=1"
FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/ppr?teams=12&year=2026"
SPECIAL_POSITIONS = frozenset({"K", "DEF"})


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _composite(name: Any, team: Any, position: Any) -> tuple[str, str, str]:
    return _normalize(name), _normalize(team), _normalize(position)


def _fixture_or_url(filename: str, url: str) -> Any:
    fixtures = os.environ.get("DRAFT_ADVISOR_FIXTURES")
    if fixtures:
        path = Path(fixtures) / filename
        try:
            return json.loads(path.read_text())
        except FileNotFoundError as exc:
            raise ValueError(f"recorded external response is missing: {filename}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"recorded external response is invalid: {filename}") from exc
    request = urllib.request.Request(url, headers={"User-Agent": "draft-advisor/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(f"external value request failed: {exc}") from exc


def _fantasycalc_rows(payload: Any) -> list[dict[str, Any]]:
    rows = payload.get("players") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("FantasyCalc returned no player values")
    result = []
    for row in rows:
        player = row.get("player") or row
        value = row.get("value", row.get("redraftValue", player.get("value")))
        if value is None:
            continue
        position = canonical_position(player.get("position") or row.get("position"))
        if position not in LEGAL_POSITIONS:
            continue
        result.append({
            "sleeper_id": player.get("sleeperId") or player.get("sleeper_id") or row.get("sleeperId"),
            "name": player.get("name") or row.get("name"),
            "team": player.get("maybeTeam") or player.get("team") or row.get("team"),
            "position": position,
            "value": float(value),
            "stability": float(row.get("stability", player.get("stability", 0.5)) or 0.5),
            "upside": float(row.get("upside", player.get("upside", 0.5)) or 0.5),
        })
    if len(result) < 5:
        raise ValueError("FantasyCalc response is incomplete (fewer than five usable players)")
    return result


def _ffc_rows(payload: Any) -> list[dict[str, Any]]:
    rows = payload.get("players") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("Fantasy Football Calculator returned no ADP players")
    result = []
    for row in rows:
        adp = row.get("adp") or row.get("overall_pick")
        if adp is None:
            continue
        position = canonical_position(row.get("position"))
        if position not in LEGAL_POSITIONS:
            continue
        result.append({"name": row.get("name"), "team": row.get("team"), "position": position, "adp": float(adp)})
    if len(result) < 5:
        raise ValueError("Fantasy Football Calculator response is incomplete (fewer than five usable players)")
    return result


def _adp_fallback_value(adp: float, position_adps: list[float]) -> float:
    """Give special teams players a relative value when FantasyCalc omits them.

    This is intentionally not presented as projected fantasy points.  It is a
    small, position-local signal derived from the ADP feed so K/DEF players can
    remain on the draft board and be compared in the rounds where they are
    eligible.
    """
    ordered = sorted(position_adps)
    rank = ordered.index(adp) + 1
    return round(max(0.5, 6.0 - (rank - 1) * 0.25), 3)


def build_value_snapshot(client: SleeperClient | None = None, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    sleeper_players = (client or SleeperClient()).players()
    fantasycalc = _fantasycalc_rows(_fixture_or_url("fantasycalc.json", FANTASYCALC_URL))
    adp_rows = _ffc_rows(_fixture_or_url("ffc-adp.json", FFC_URL))
    composite_index: dict[tuple[str, str, str], list[str]] = {}
    for player_id, player in sleeper_players.items():
        name = player.get("full_name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
        composite_index.setdefault(_composite(name, player.get("team"), player.get("position")), []).append(str(player_id))

    omitted: list[dict[str, Any]] = []

    def match(row: dict[str, Any], source: str) -> str | None:
        native = row.get("sleeper_id")
        if native and str(native) in sleeper_players:
            return str(native)
        matches = composite_index.get(_composite(row.get("name"), row.get("team"), row.get("position")), [])
        if len(matches) == 1:
            return matches[0]
        omitted.append({"source": source, "name": row.get("name"), "reason": "ambiguous" if matches else "unmatched"})
        return None

    values: dict[str, dict[str, Any]] = {}
    for row in fantasycalc:
        player_id = match(row, "fantasycalc")
        if player_id:
            values[player_id] = {key: value for key, value in row.items() if key != "sleeper_id"}
    adp: dict[str, float] = {}
    adp_rows_by_player: dict[str, dict[str, Any]] = {}
    for row in adp_rows:
        player_id = match(row, "ffc_adp")
        if player_id:
            adp[player_id] = row["adp"]
            adp_rows_by_player[player_id] = row
    if len(adp) < 5:
        raise ValueError("external snapshot is incomplete after ADP player matching")

    special_position_adps = {
        position: [
            adp_value for player_id, adp_value in adp.items()
            if adp_rows_by_player[player_id]["position"] == position
        ]
        for position in SPECIAL_POSITIONS
    }
    for player_id, row in adp_rows_by_player.items():
        if player_id in values or row["position"] not in SPECIAL_POSITIONS:
            continue
        sleeper = sleeper_players[player_id]
        values[player_id] = {
            "name": sleeper.get("full_name") or row.get("name"),
            "team": sleeper.get("team") or row.get("team"),
            "position": sleeper.get("position") or row.get("position"),
            "value": _adp_fallback_value(row["adp"], special_position_adps[row["position"]]),
            "stability": 0.5,
            "upside": 0.5,
            "value_source": "ffc_adp_fallback",
        }
    for player_id, player in values.items():
        player["adp"] = adp.get(player_id)
        sleeper = sleeper_players[player_id]
        player.update({
            "player_id": player_id,
            "name": sleeper.get("full_name") or player.get("name"),
            "team": sleeper.get("team") or player.get("team"),
            "position": sleeper.get("position") or player.get("position"),
            "status": sleeper.get("status"),
            "injury_status": sleeper.get("injury_status"),
            "bye_week": sleeper.get("bye_week"),
        })
        player.setdefault("value_source", "fantasycalc")
    if len(values) < 5:
        raise ValueError("external snapshot is incomplete after player matching")
    return {"schema_version": 1, "updated_at": clock(), "format": "12-team one-QB full-PPR", "players": values, "omitted": omitted}


def validate_value_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ValueError("value snapshot must be a schema-version 1 object")
    players = snapshot.get("players")
    if not isinstance(players, dict) or len(players) < 5:
        raise ValueError("value snapshot must contain at least five matched players")
    for player_id, player in players.items():
        if not isinstance(player, dict) or player.get("value") is None or not player.get("position"):
            raise ValueError(f"value snapshot player {player_id} is incomplete")
        value = float(player["value"])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"value snapshot player {player_id} has an invalid value")
        if canonical_position(player.get("position")) not in LEGAL_POSITIONS:
            raise ValueError(f"value snapshot player {player_id} has an unsupported position")
    if not isinstance(snapshot.get("omitted", []), list):
        raise ValueError("value snapshot omissions must be an array")
    return snapshot
