from __future__ import annotations

import math
import time
from collections import Counter
from typing import Any, Callable


FLEX_POSITIONS = {"RB", "WR", "TE"}
BENCH = {"BN", "BENCH", "IR", "TAXI"}


class InsufficientCandidates(ValueError):
    """The board cannot satisfy the five-candidate public contract."""


def _position_requirements(state: dict[str, Any]) -> Counter[str]:
    requirements: Counter[str] = Counter()
    for slot in state["league_rules"].get("roster_positions") or []:
        upper = str(slot).upper()
        if upper in BENCH:
            continue
        if "FLEX" in upper:
            requirements["FLEX"] += 1
        elif upper in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            requirements[upper] += 1
    return requirements


def _roster_positions(state: dict[str, Any], values: dict[str, Any], roster_id: int) -> Counter[str]:
    result: Counter[str] = Counter()
    roster = state.get("rosters", {}).get(str(roster_id), {})
    for player_id in roster.get("player_ids") or roster.get("drafted_player_ids") or []:
        player = values.get(str(player_id), {})
        position = player.get("position")
        if position:
            result[str(position).upper()] += 1
    return result


def _fit(position: str, requirements: Counter[str], roster: Counter[str]) -> tuple[float, str]:
    direct_open = max(0, requirements[position] - roster[position])
    flex_used = sum(max(0, roster[p] - requirements[p]) for p in FLEX_POSITIONS)
    flex_open = max(0, requirements["FLEX"] - flex_used)
    if direct_open:
        return 12.0, f"fills open {position} starter"
    if position in FLEX_POSITIONS and flex_open:
        return 9.0, "fills open FLEX starter"
    if position in {"QB", "TE"}:
        return -10.0, f"backup {position} is a soft-limit penalty"
    if position in {"K", "DEF"}:
        return -30.0, f"bench {position} is not allowed"
    return 3.0, "adds RB/WR bench depth" if position in {"RB", "WR"} else "bench depth"


def _projected_starter_ids(
    player_ids: list[Any], players: dict[str, Any], requirements: Counter[str]
) -> set[str]:
    """Fill direct slots, then FLEX slots, in roster order."""
    starters: set[str] = set()
    remaining = requirements.copy()
    flex_candidates: list[str] = []
    for raw_player_id in player_ids:
        player_id = str(raw_player_id)
        position = str(players.get(player_id, {}).get("position") or "").upper()
        if remaining[position] > 0:
            starters.add(player_id)
            remaining[position] -= 1
        elif position in FLEX_POSITIONS:
            flex_candidates.append(player_id)
    for player_id in flex_candidates[:remaining["FLEX"]]:
        starters.add(player_id)
    return starters


def _bye_week_penalty(
    bye_week: str, position: str, fit: float, roster_byes: Counter[str],
    starter_byes: Counter[str], roster_positions_by_bye: Counter[tuple[str, str]],
) -> float:
    if not bye_week:
        return 0.0
    # The fourth player sharing a bye starts to matter; each additional player
    # is progressively more costly. Three projected starters sharing a bye is
    # independently discouraged.
    total_excess = max(0, roster_byes[bye_week] + 1 - 3)
    starter_excess = max(0, starter_byes[bye_week] + (1 if fit > 3 else 0) - 2)
    penalty = -(total_excess * (total_excess + 1) / 2)
    penalty -= starter_excess * (starter_excess + 1)
    # A same-bye backup cannot cover the starter at a scarce position.
    if position in {"QB", "TE"} and fit < 0 and roster_positions_by_bye[(position, bye_week)]:
        penalty -= 4.0
    return penalty


def calculate(state: dict[str, Any], snapshot: dict[str, Any], clock: Callable[[], float] = time.time) -> dict[str, Any]:
    available = {
        player_id: player for player_id, player in snapshot["players"].items()
        if player_id not in set(state.get("selected_player_ids") or [])
        and str(player.get("status") or "Active").lower() not in {"inactive", "retired"}
    }
    if len(available) < 5:
        raise InsufficientCandidates("fewer than five eligible players remain")
    participant_id = int(state["participant"]["roster_id"])
    roster = _roster_positions(state, snapshot["players"], participant_id)
    participant_roster = state.get("rosters", {}).get(str(participant_id), {})
    roster_player_ids = participant_roster.get("player_ids") or participant_roster.get("drafted_player_ids") or []
    roster_teams = Counter(str(snapshot["players"].get(str(player_id), {}).get("team") or "") for player_id in roster_player_ids)
    roster_byes = Counter(str(snapshot["players"].get(str(player_id), {}).get("bye_week") or "") for player_id in roster_player_ids)
    requirements = _position_requirements(state)
    starter_ids = _projected_starter_ids(roster_player_ids, snapshot["players"], requirements)
    starter_byes = Counter(str(snapshot["players"].get(player_id, {}).get("bye_week") or "") for player_id in starter_ids)
    roster_positions_by_bye = Counter(
        (str(snapshot["players"].get(str(player_id), {}).get("position") or "").upper(),
         str(snapshot["players"].get(str(player_id), {}).get("bye_week") or ""))
        for player_id in roster_player_ids
    )
    total_rounds = int(state["league_rules"].get("rounds") or 15)
    current_turn = state.get("current_turn") or {}
    current_round = int(current_turn.get("round") or 1)
    next_turn = state.get("participant_next_turn") or current_turn
    next_pick_no = int((next_turn or {}).get("pick_no") or len(state.get("picks") or []) + 1)
    picks_until_next = max(0, next_pick_no - (len(state.get("picks") or []) + 1))
    max_value = max(float(player["value"]) for player in available.values()) or 1.0
    by_position: dict[str, list[float]] = {}
    for player in available.values():
        by_position.setdefault(str(player.get("position") or ""), []).append(float(player["value"]))
    for values in by_position.values():
        values.sort(reverse=True)

    intervening = [turn for turn in state.get("turns") or [] if len(state.get("picks") or []) + 1 <= int(turn["pick_no"]) < next_pick_no]
    opponent_rosters = {int(turn["owner_roster_id"]) for turn in intervening if turn.get("owner_roster_id") != participant_id}
    opponent_needs: Counter[str] = Counter()
    for roster_id in opponent_rosters:
        positions = _roster_positions(state, snapshot["players"], roster_id)
        for position in ("QB", "RB", "WR", "TE"):
            if positions[position] < requirements[position]:
                opponent_needs[position] += 1
    recent_positions = [str((pick.get("metadata") or {}).get("position") or "").upper() for pick in (state.get("picks") or [])[-3:]]
    recent_run_position = recent_positions[0] if len(recent_positions) == 3 and len(set(recent_positions)) == 1 else None

    candidates = []
    for player_id, player in available.items():
        position = str(player.get("position") or "").upper()
        if not position:
            continue
        if position in {"K", "DEF"} and (roster[position] >= requirements[position] or current_round < max(1, total_rounds - 1)):
            continue
        quality = 70.0 * float(player["value"]) / max_value
        fit, fit_text = _fit(position, requirements, roster)
        position_values = by_position.get(position, [])
        replacement_index = min(len(position_values) - 1, max(1, picks_until_next))
        replacement = position_values[replacement_index] if position_values else 0
        scarcity = min(8.0, max(0.0, (float(player["value"]) - replacement) / max_value * 12))
        adp = player.get("adp")
        if adp is None:
            expected_survival = 0.5
            wait_cost = 0.0
        else:
            margin = float(adp) - next_pick_no
            expected_survival = 1 / (1 + math.exp(-margin / 4))
            wait_cost = min(7.0, max(0.0, (next_pick_no - float(adp)) / 3))
        need_count = opponent_needs[position]
        run_pressure = 0.2 if position == recent_run_position else 0.0
        demand = min(5.0, need_count * 1.5 + run_pressure * 5)
        expected_survival = max(0.02, expected_survival - min(0.35, need_count * 0.1) - run_pressure)
        stage = min(1.0, max(0.0, (current_round - 1) / max(1, total_rounds - 1)))
        stability = float(player.get("stability", 0.5))
        upside = float(player.get("upside", 0.5))
        round_strategy = 4.0 * ((1 - stage) * stability + stage * upside)
        injury = str(player.get("injury_status") or "").upper()
        injury_penalty = -28.0 if injury in {"OUT", "IR", "PUP"} else 0.0
        team = str(player.get("team") or "")
        bye_week = str(player.get("bye_week") or "")
        team_tiebreaker = -0.01 * roster_teams[team] if team else 0.0
        bye_week_penalty = _bye_week_penalty(
            bye_week, position, fit, roster_byes, starter_byes, roster_positions_by_bye
        )
        diversity_tiebreaker = team_tiebreaker + bye_week_penalty
        score = quality + fit + scarcity + wait_cost + demand + round_strategy + injury_penalty + diversity_tiebreaker
        components = {
            "primary_value": round(quality, 3), "roster_fit": round(fit, 3),
            "positional_scarcity": round(scarcity, 3), "wait_cost": round(wait_cost, 3),
            "opponent_demand": round(demand, 3), "round_strategy": round(round_strategy, 3),
            "injury_penalty": injury_penalty,
            "bye_week_penalty": round(bye_week_penalty, 3),
            "diversity_tiebreaker": round(diversity_tiebreaker, 3),
        }
        candidates.append({
            "player_id": player_id, "name": player.get("name"), "team": player.get("team"), "position": position,
            "draft_score": round(score, 3), "score_type": "relative comparison", "components": components,
            "roster_fit": fit_text, "injury_status": injury or None,
            "injury_warning": f"{injury} designation materially reduces this score" if injury in {"OUT", "IR", "PUP"} else None,
            "scarcity": round(scarcity, 3), "expected_survival_to_next_turn": round(expected_survival, 3),
            "relevant_opponent_needs": {position: need_count} if need_count else {},
            "position_run_survival_penalty": run_pressure,
            "adp": adp,
        })
    candidates.sort(key=lambda item: (-item["draft_score"], -float(available[item["player_id"]]["value"]), item["name"] or "", item["player_id"]))
    if len(candidates) < 5:
        raise InsufficientCandidates("fewer than five strategy-eligible players remain")
    candidates = candidates[:5]
    leader = candidates[0]["draft_score"]
    for candidate in candidates:
        candidate["model_judgment_eligible"] = candidate["draft_score"] >= leader * 0.95
    return {
        "schema_version": 1, "updated_at": clock(), "draft_state_updated_at": state["updated_at"],
        "value_snapshot_updated_at": snapshot["updated_at"], "calculated_pick": candidates[0],
        "backup_picks": candidates[1:], "matching_omissions": snapshot.get("omitted") or [],
    }
