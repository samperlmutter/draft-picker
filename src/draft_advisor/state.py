from __future__ import annotations

import time
from typing import Any, Callable

from .config import Config
from .sleeper import SleeperClient


def _rules(league: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    settings = league.get("settings") or {}
    scoring = league.get("scoring_settings") or {}
    roster_positions = league.get("roster_positions") or []
    return {
        "name": league.get("name"),
        "teams": settings.get("num_teams") or draft.get("settings", {}).get("teams"),
        "rounds": draft.get("settings", {}).get("rounds"),
        "roster_positions": roster_positions,
        "scoring_settings": scoring,
    }


def _pick_event(pick: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "pick",
        "pick_no": pick.get("pick_no"),
        "round": pick.get("round"),
        "draft_slot": pick.get("draft_slot"),
        "roster_id": pick.get("roster_id"),
        "player_id": pick.get("player_id"),
        "picked_by": pick.get("picked_by"),
        "metadata": pick.get("metadata") or {},
    }


def _turns(draft: dict[str, Any], traded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settings = draft.get("settings") or {}
    teams, rounds = int(settings.get("teams") or 0), int(settings.get("rounds") or 0)
    order = draft.get("draft_order") or {}
    slot_to_user = {int(slot): user_id for user_id, slot in order.items()}
    slot_to_roster = {
        int(slot): int(roster_id)
        for slot, roster_id in (draft.get("slot_to_roster_id") or {}).items()
    }
    ownership = {(int(p["round"]), int(p["draft_slot"])): int(p["owner_id"]) for p in traded if p.get("round") and p.get("draft_slot") and p.get("owner_id")}
    result = []
    for round_no in range(1, rounds + 1):
        slots = range(1, teams + 1) if round_no % 2 else range(teams, 0, -1)
        for slot in slots:
            original_roster = slot_to_roster.get(slot)
            owner = ownership.get((round_no, slot), original_roster)
            result.append({
                "pick_no": len(result) + 1,
                "round": round_no,
                "draft_slot": slot,
                "original_roster_id": original_roster,
                "owner_roster_id": owner,
                "user_id": slot_to_user.get(slot),
            })
    return result


def fetch_state(config: Config, client: SleeperClient, previous: dict[str, Any] | None = None, clock: Callable[[], float] = time.time) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    user = client.user(config.participant_username)
    league = client.league(config.sleeper_league_id)
    users = client.league_users(config.sleeper_league_id)
    rosters = client.rosters(config.sleeper_league_id)
    summary = client.current_draft(config.sleeper_league_id)
    draft_id = str(summary.get("draft_id") or "")
    if not draft_id:
        raise ValueError("Sleeper returned a draft without a draft_id")
    draft = client.draft(draft_id)
    picks = sorted(client.picks(draft_id), key=lambda pick: int(pick.get("pick_no") or 0))
    traded = client.traded_picks(draft_id)
    participant_roster = next((r for r in rosters if str(r.get("owner_id")) == str(user["user_id"])), None)
    if participant_roster is None:
        raise ValueError(f"participant {config.participant_username} has no roster in league")
    membership_complete = len([u for u in users if u.get("user_id")]) >= int((league.get("settings") or {}).get("num_teams") or 0)
    schedule = _turns(draft, traded)
    current_pick_no = len(picks) + 1
    participant_roster_id = int(participant_roster["roster_id"])
    next_turn = next((turn for turn in schedule if turn["pick_no"] >= current_pick_no and turn["owner_roster_id"] == participant_roster_id), None)
    keeper_ids = list((draft.get("metadata") or {}).get("keepers") or [])
    if not keeper_ids:
        keeper_ids = [str(p["player_id"]) for p in picks if (p.get("is_keeper") or (p.get("metadata") or {}).get("is_keeper")) and p.get("player_id")]
    previous_count = len((previous or {}).get("picks") or [])
    new_events = [_pick_event(pick) for pick in picks[previous_count:]]
    rosters_by_id = {str(r["roster_id"]): dict(r) for r in rosters}
    for roster in rosters_by_id.values():
        roster["drafted_player_ids"] = []
    for pick in picks:
        roster = rosters_by_id.get(str(pick.get("roster_id")))
        if roster is not None and pick.get("player_id"):
            roster["drafted_player_ids"].append(str(pick["player_id"]))
    for roster in rosters_by_id.values():
        roster["player_ids"] = list(dict.fromkeys(
            [str(player_id) for player_id in (roster.get("players") or [])]
            + roster["drafted_player_ids"]
        ))
    status = draft.get("status") or summary.get("status") or "pre_draft"
    state = {
        "schema_version": 1,
        "updated_at": clock(),
        "league_id": config.sleeper_league_id,
        "league_rules": _rules(league, draft),
        "participant": {"username": config.participant_username, "user_id": str(user["user_id"]), "roster_id": participant_roster_id},
        "draft": {"draft_id": draft_id, "type": draft.get("type"), "status": status, "start_time": draft.get("start_time"), "draft_order": draft.get("draft_order") or None, "membership_complete": membership_complete},
        "picks": picks,
        "latest_pick": picks[-1] if picks else None,
        "selected_player_ids": sorted({str(p["player_id"]) for p in picks if p.get("player_id")} | set(keeper_ids)),
        "keepers": keeper_ids or None,
        "traded_picks": traded,
        "turns": schedule,
        "current_turn": schedule[current_pick_no - 1] if current_pick_no <= len(schedule) else None,
        "participant_next_turn": next_turn,
        "rosters": rosters_by_id,
    }
    return state, new_events
