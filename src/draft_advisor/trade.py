from __future__ import annotations

from collections import Counter
from typing import Any

from .rules import LEGAL_POSITIONS, canonical_position


SUPPORTED_TYPES = {"player", "pick"}


def _asset_key(asset: dict[str, Any]) -> tuple[str, str]:
    asset_type = str(asset.get("type") or "").lower()
    identifier = asset.get("player_id") if asset_type == "player" else asset.get("pick_no")
    return asset_type, str(identifier)


def _pick(state: dict[str, Any], pick_no: int) -> dict[str, Any]:
    turn = next((turn for turn in state.get("turns") or [] if int(turn["pick_no"]) == pick_no), None)
    if turn is None:
        raise ValueError(f"current-draft pick #{pick_no} does not exist")
    if pick_no <= len(state.get("picks") or []):
        raise ValueError(f"current-draft pick #{pick_no} has already been used")
    return turn


def _player_owner(state: dict[str, Any], player_id: str) -> int:
    pick = next((pick for pick in state.get("picks") or [] if str(pick.get("player_id")) == player_id), None)
    if pick is None:
        raise ValueError(f"player {player_id} was not drafted in the current draft")
    return int(pick["roster_id"])


def _validate_asset(asset: dict[str, Any], state: dict[str, Any]) -> tuple[str, int, str]:
    if asset.get("season") is not None or asset.get("future"):
        raise ValueError("future-season draft picks are unsupported")
    asset_type = str(asset.get("type") or "").lower()
    if asset_type not in SUPPORTED_TYPES:
        raise ValueError("trade assets must be current-draft 'player' or 'pick' objects")
    if asset_type == "player":
        player_id = str(asset.get("player_id") or "")
        if not player_id:
            raise ValueError("player trade assets require player_id")
        return asset_type, _player_owner(state, player_id), player_id
    try:
        pick_no = int(asset["pick_no"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("pick trade assets require an integer pick_no") from exc
    turn = _pick(state, pick_no)
    return asset_type, int(turn["owner_roster_id"]), str(pick_no)


def _requirements(state: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    for slot in state["league_rules"].get("roster_positions") or []:
        position = str(slot).upper()
        if position in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            result[position] += 1
        elif "FLEX" in position:
            result["FLEX"] += 1
    return result


def _positions(state: dict[str, Any], values: dict[str, Any], roster_id: int) -> Counter[str]:
    result: Counter[str] = Counter()
    roster = state.get("rosters", {}).get(str(roster_id), {})
    for player_id in roster.get("player_ids") or []:
        position = values.get(str(player_id), {}).get("position")
        if position:
            result[str(position).upper()] += 1
    return result


def _pick_value(state: dict[str, Any], values: dict[str, Any], pick_no: int) -> float:
    current = len(state.get("picks") or []) + 1
    available = sorted(
        (_effective_player_value(player) for player_id, player in values.items() if player_id not in set(state.get("selected_player_ids") or []) and str(player.get("status") or "Active").lower() not in {"inactive", "retired"}),
        reverse=True,
    )
    if not available:
        return 0.0
    index = min(len(available) - 1, max(0, pick_no - current))
    return available[index] * 0.9


def _asset_value(asset: dict[str, Any], state: dict[str, Any], values: dict[str, Any]) -> float:
    asset_type, identifier = _asset_key(asset)
    if asset_type == "pick":
        return _pick_value(state, values, int(identifier))
    player = values.get(identifier)
    if player is None:
        raise ValueError(f"no current value is available for player {identifier}")
    base = _effective_player_value(player)
    return base


def _effective_player_value(player: dict[str, Any]) -> float:
    value = float(player["value"])
    if str(player.get("injury_status") or "").upper() in {"OUT", "IR", "PUP"}:
        return value * 0.55
    return value


def _open_starter_slots(positions: Counter[str], requirements: Counter[str]) -> int:
    direct_open = sum(max(0, requirements[position] - positions[position]) for position in ("QB", "RB", "WR", "TE", "K", "DEF"))
    flex_excess = sum(max(0, positions[position] - requirements[position]) for position in ("RB", "WR", "TE"))
    return direct_open + max(0, requirements["FLEX"] - flex_excess)


def evaluate(offer: dict[str, Any], state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(offer, dict):
        raise ValueError("Trade Offer must be a JSON object")
    if offer.get("confirmed") is not True:
        raise ValueError("Trade Offer must be confirmed before evaluation")
    give = offer.get("give")
    receive = offer.get("receive")
    if not isinstance(give, list) or not give or not isinstance(receive, list) or not receive:
        raise ValueError("Trade Offer requires non-empty give and receive arrays")
    if not all(isinstance(asset, dict) for asset in [*give, *receive]):
        raise ValueError("every Trade Offer asset must be an object")
    keys = [_asset_key(asset) for asset in [*give, *receive]]
    if len(keys) != len(set(keys)):
        raise ValueError("Trade Offer assets cannot be duplicated")
    participant = int(state["participant"]["roster_id"])
    partner_ids: set[int] = set()
    for asset in give:
        _, owner, _ = _validate_asset(asset, state)
        if owner != participant:
            raise ValueError("every give asset must be owned by the Participant")
    for asset in receive:
        _, owner, _ = _validate_asset(asset, state)
        if owner == participant:
            raise ValueError("receive assets must be owned by another roster")
        partner_ids.add(owner)
    if len(partner_ids) != 1:
        raise ValueError("a Trade Offer must involve exactly one other roster")
    values = snapshot["players"]
    for asset in [*give, *receive]:
        if asset.get("type", "").lower() == "player":
            player = values.get(str(asset.get("player_id")))
            if player is None or canonical_position(player.get("position")) not in LEGAL_POSITIONS:
                raise ValueError("trade player has an unsupported fantasy position")
    requirements = _requirements(state)
    positions = _positions(state, values, participant)
    give_value = sum(_asset_value(asset, state, values) for asset in give)
    receive_value = sum(_asset_value(asset, state, values) for asset in receive)
    resulting_positions = positions.copy()
    for asset in give:
        if asset["type"].lower() == "player":
            position = str(values[str(asset["player_id"])].get("position") or "").upper()
            resulting_positions[position] = max(0, resulting_positions[position] - 1)
    for asset in receive:
        if asset["type"].lower() == "player":
            position = str(values[str(asset["player_id"])].get("position") or "").upper()
            resulting_positions[position] += 1
    open_before = _open_starter_slots(positions, requirements)
    open_after = _open_starter_slots(resulting_positions, requirements)
    average_asset_value = (give_value + receive_value) / max(1, len(give) + len(receive))
    roster_fit_adjustment = (open_before - open_after) * average_asset_value * 0.08
    receive_value += roster_fit_adjustment
    difference = receive_value - give_value
    scale = max(1.0, give_value, receive_value)
    ratio = difference / scale
    tolerance = 1e-9
    if ratio > 0.05 + tolerance:
        decision = "accept"
        reason = "The incoming value and resulting roster fit improve your draft position."
    elif ratio < -0.05 - tolerance:
        decision = "reject"
        reason = "The outgoing value costs more than the incoming roster and pick opportunities."
    else:
        decision = "close"
        reason = "The value and resulting draft opportunities are within five percent."
    counteroffer = _counteroffer(give, receive, state, snapshot, next(iter(partner_ids)), difference) if decision != "accept" else None
    return {
        "schema_version": 1, "decision": decision, "reason": reason,
        "participant_roster_id": participant, "other_roster_id": next(iter(partner_ids)),
        "give": give, "receive": receive,
        "evaluation": {"give_value": round(give_value, 3), "receive_value": round(receive_value, 3), "net_value": round(difference, 3), "roster_fit_adjustment": round(roster_fit_adjustment, 3), "open_starter_slots_before": open_before, "open_starter_slots_after": open_after, "includes_roster_fit": True, "includes_remaining_picks": True},
        "counteroffer": counteroffer,
    }


def _counteroffer(give: list[dict[str, Any]], receive: list[dict[str, Any]], state: dict[str, Any], snapshot: dict[str, Any], partner: int, difference: float) -> dict[str, Any] | None:
    included = {_asset_key(asset) for asset in receive}
    candidates: list[tuple[float, dict[str, Any]]] = []
    for pick in state.get("picks") or []:
        player_id = str(pick.get("player_id") or "")
        if int(pick.get("roster_id") or 0) == partner and ("player", player_id) not in included and player_id in snapshot["players"]:
            candidates.append((_effective_player_value(snapshot["players"][player_id]), {"type": "player", "player_id": player_id}))
    for turn in state.get("turns") or []:
        key = ("pick", str(turn["pick_no"]))
        if int(turn.get("owner_roster_id") or 0) == partner and int(turn["pick_no"]) > len(state.get("picks") or []) and key not in included:
            candidates.append((_pick_value(state, snapshot["players"], int(turn["pick_no"])), {"type": "pick", "pick_no": int(turn["pick_no"])}))
    if not candidates:
        return None
    needed = max(0.0, -difference)
    _, addition = min(candidates, key=lambda item: (abs(item[0] - needed), item[0], str(item[1])))
    return {"give": give, "receive": [*receive, addition]}
