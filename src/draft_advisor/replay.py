from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Any

from .recommend import calculate
from .schedule import league_rules_identity, validate_schedule_snapshot
from .trade import evaluate
from .values import validate_value_snapshot
from .risk import risk_injury_status, validate_authoritative_risk_snapshot
from .rules import LEGAL_POSITIONS, validate_roster_config, canonical_position, position_requirements


class ReplayFailure(ValueError):
    def __init__(self, stage: str, message: str, **context: Any):
        super().__init__(message)
        self.stage = stage
        self.context = context


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    components = candidate.get("components") or {}
    schedule_evidence = candidate.get("schedule_evidence") or {}
    collision = schedule_evidence.get("roster_collision") or {}
    return {
        key: candidate[key] for key in (
            "player_id", "name", "position", "draft_score", "model_judgment_eligible",
            "injury_warning", "expected_survival_to_next_turn", "position_run_survival_penalty",
            "risk_state", "risk_visible",
        )
    } | {
        "risk_evidence": copy.deepcopy(candidate.get("risk_evidence", [])),
        "risk_freshness": copy.deepcopy(candidate.get("risk_freshness", {})),
        "risk_provenance": copy.deepcopy(candidate.get("risk_provenance", [])),
        "event_risk_tier": candidate.get("event_risk_tier", "none"),
        "schedule_risk_tier": candidate.get("schedule_risk_tier", "none"),
        "combined_risk_adjustment_pct": candidate.get("combined_risk_adjustment_pct", 0.0),
        "schedule_data_quality": candidate.get("schedule_data_quality", "unavailable"),
        "regular_season_matchup": components.get("regular_season_matchup", 0.0),
        "playoff_matchup": components.get("playoff_matchup", 0.0),
        "schedule_adjustment": components.get("schedule_adjustment", 0.0),
        "roster_collision": components.get("roster_collision", 0.0),
        "playoff_weight_applied": bool(schedule_evidence.get("playoff_weight_applied")),
        "candidate_is_projected_starter": bool(collision.get("candidate_is_projected_starter")),
        "collision_weeks": collision.get("collision_weeks") or [],
    }


def _recommendation_summary(
    recommendation: dict[str, Any], pick_no: int, snapshot: dict[str, Any]
) -> dict[str, Any]:
    # ``calculate`` intentionally returns a compact recommendation. Replay is
    # the audit boundary, so restore the source metadata here instead of
    # making the live recommendation contract carry raw evidence.
    for candidate in [recommendation["calculated_pick"], *recommendation["backup_picks"]]:
        risk = snapshot.get("players", {}).get(str(candidate.get("player_id")), {})
        candidate["risk_evidence"] = copy.deepcopy(risk.get("risk_evidence", risk.get("observations", [])))
        candidate["risk_freshness"] = copy.deepcopy(risk.get("risk_freshness", risk.get("freshness", {})))
        candidate["risk_provenance"] = copy.deepcopy(risk.get("risk_provenance", risk.get("provenance", [])))
    return {
        "pick_no": pick_no,
        "calculated_pick": _candidate_summary(recommendation["calculated_pick"]),
        "backup_picks": [_candidate_summary(candidate) for candidate in recommendation["backup_picks"]],
    }


def _advance_turns(state: dict[str, Any]) -> None:
    next_pick = len(state["picks"]) + 1
    state["current_turn"] = next((turn for turn in state["turns"] if int(turn["pick_no"]) == next_pick), None)
    participant = int(state["participant"]["roster_id"])
    state["participant_next_turn"] = next((turn for turn in state["turns"] if int(turn["pick_no"]) >= next_pick and int(turn["owner_roster_id"]) == participant), None)


def _apply_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    required = ("type", "pick_no", "round", "draft_slot", "roster_id", "player_id", "picked_by", "metadata")
    missing = [field for field in required if field not in event]
    if missing:
        raise ReplayFailure("pick", f"pick event is missing {', '.join(missing)}", event=event)
    expected = len(state["picks"]) + 1
    if event["type"] != "pick" or int(event["pick_no"]) != expected:
        raise ReplayFailure("pick", f"expected ordered pick event #{expected}", pick_no=event.get("pick_no"), event=event)
    turn = next((turn for turn in state["turns"] if int(turn["pick_no"]) == expected), None)
    if turn is None or int(turn["owner_roster_id"]) != int(event["roster_id"]):
        raise ReplayFailure("pick", "pick owner does not match live turn ownership", pick_no=expected, expected_turn=turn, event=event)
    player_id = str(event["player_id"])
    already_selected = player_id in set(state.get("selected_player_ids") or [])
    keeper_first_event = player_id in set(map(str, state.get("keepers") or [])) and not any(str(pick.get("player_id")) == player_id for pick in state["picks"])
    if already_selected and not keeper_first_event:
        raise ReplayFailure("pick", "player was already unavailable", pick_no=expected, player_id=player_id)
    state["picks"].append(copy.deepcopy(event))
    state.setdefault("selected_player_ids", []).append(player_id)
    state["selected_player_ids"] = sorted(set(map(str, state["selected_player_ids"])))
    roster = state["rosters"].setdefault(str(event["roster_id"]), {"roster_id": int(event["roster_id"]), "player_ids": [], "drafted_player_ids": []})
    for field in ("player_ids", "drafted_player_ids"):
        if player_id not in roster.setdefault(field, []):
            roster[field].append(player_id)
    state["latest_pick"] = copy.deepcopy(event)
    _advance_turns(state)


def _validate_shape(bundle: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    if not isinstance(bundle, dict):
        raise ReplayFailure("input", "replay input must be a JSON object")
    state = copy.deepcopy(bundle.get("initial_state"))
    events = bundle.get("events")
    snapshots = bundle.get("value_snapshots")
    if not isinstance(state, dict) or not isinstance(events, list) or not isinstance(snapshots, list) or not snapshots:
        raise ReplayFailure("input", "replay requires initial_state, events, and value_snapshots")
    rules = state.get("league_rules") or {}
    try:
        validate_roster_config(
            rules.get("roster_positions"), rules.get("teams"), rules.get("rounds"), official=True
        )
    except (TypeError, ValueError) as exc:
        raise ReplayFailure("input", "replay must be a 12-team, 15-round draft")
    if len(events) != 180:
        raise ReplayFailure("input", "replay must contain exactly 180 pick events", event_count=len(events))
    if state.get("picks"):
        raise ReplayFailure("input", "initial replay Draft State must be pre-draft with no picks")
    if set(map(str, state.get("selected_player_ids") or [])) != set(map(str, state.get("keepers") or [])):
        raise ReplayFailure("input", "initial selected Players must contain only keepers")
    validated_snapshots = [validate_value_snapshot(copy.deepcopy(snapshot)) for snapshot in snapshots]
    raw_risk = bundle.get("risk_snapshot")
    risk = None
    if raw_risk is not None:
        try:
            risk = validate_authoritative_risk_snapshot(copy.deepcopy(raw_risk))
        except (TypeError, ValueError) as exc:
            raise ReplayFailure("risk", str(exc)) from exc
        freshness = risk.get("freshness")
        if not isinstance(freshness, dict) or freshness.get("observed_at") is None:
            raise ReplayFailure("risk", "risk snapshot freshness metadata is incomplete")
        try:
            max_age = float(freshness.get("max_age_seconds"))
        except (TypeError, ValueError) as exc:
            raise ReplayFailure("risk", "risk snapshot freshness max age is invalid") from exc
        if max_age < 0:
            raise ReplayFailure("risk", "risk snapshot freshness max age cannot be negative")
        if not isinstance(risk.get("source"), dict) or not isinstance(risk.get("parser"), dict):
            raise ReplayFailure("risk", "risk snapshot provenance metadata is incomplete")
        if not isinstance(risk.get("players"), dict):
            raise ReplayFailure("risk", "risk snapshot players must be an object")
        for snapshot in validated_snapshots:
            for pid, item in risk["players"].items():
                player = snapshot["players"].get(str(pid))
                if player is None:
                    continue
                if not isinstance(item, dict):
                    raise ReplayFailure("risk", "risk snapshot player entries must be objects", player_id=str(pid))
                # Missing/neutral states must never manufacture an injury
                # designation during replay. In particular, stale and
                # unknown evidence is visible audit metadata, not a penalty.
                risk_state = item.get("state", "unknown")
                if risk_state not in {"available", "limited", "unavailable", "suspended", "exempt", "under_review", "unknown", "stale"}:
                    risk_state = "unknown"
                player["risk_state"] = risk_state
                player["risk_evidence"] = item.get("observations", [])
                injury_status = risk_injury_status(risk_state)
                if injury_status:
                    player["injury_status"] = injury_status
                player["risk_freshness"] = copy.deepcopy(freshness)
                player["risk_provenance"] = item.get("provenance", [])
                if isinstance(item.get("event_evaluation"), dict):
                    player["event_evaluation"] = copy.deepcopy(item["event_evaluation"])
    raw_schedule = bundle.get("schedule_snapshot")
    if raw_schedule is None and "schedule" in bundle:
        raw_schedule = bundle["schedule"]
    schedule = None
    if raw_schedule is not None:
        try:
            schedule = validate_schedule_snapshot(copy.deepcopy(raw_schedule))
        except (TypeError, ValueError) as exc:
            raise ReplayFailure("schedule", str(exc)) from exc
        rules = state.get("league_rules") or {}
        expected_identity = league_rules_identity(rules)
        if schedule["league_rules_identity"] != expected_identity:
            raise ReplayFailure(
                "schedule",
                "schedule snapshot League Rules identity does not match initial Draft State",
                expected_identity=expected_identity,
                schedule_identity=schedule["league_rules_identity"],
            )
        if rules.get("season") is not None and int(rules["season"]) != int(schedule["season"]):
            raise ReplayFailure(
                "schedule",
                "schedule snapshot season does not match initial Draft State",
                expected_season=int(rules["season"]),
                schedule_season=int(schedule["season"]),
            )
    return state, events, validated_snapshots, schedule


def _roster_counts(state: dict[str, Any], snapshot: dict[str, Any], roster_id: int) -> Counter[str]:
    roster = state["rosters"][str(roster_id)]
    return Counter(str(snapshot["players"][player_id]["position"]).upper() for player_id in roster["player_ids"] if player_id in snapshot["players"])


def _check_roster(state: dict[str, Any], snapshot: dict[str, Any], roster_id: int, final: bool = False) -> dict[str, int]:
    counts = _roster_counts(state, snapshot, roster_id)
    total = sum(counts.values())
    if total > 15 or any(position not in LEGAL_POSITIONS for position in counts):
        raise ReplayFailure("roster", "Participant roster became illegal", pick_no=len(state["picks"]), counts=dict(counts), total=total)
    if final:
        skill = counts["RB"] + counts["WR"] + counts["TE"]
        required = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
        missing = {position: amount for position, amount in required.items() if counts[position] < amount}
        if missing or skill < 7 or total != 15:
            raise ReplayFailure("roster", "final Participant roster does not fill all starters and bench capacity", counts=dict(counts), missing=missing, total=total)
        bench_positions = []
        direct = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
        flex_remaining = 2
        for position, count in counts.items():
            surplus = max(0, count - direct.get(position, 0))
            if position in {"RB", "WR", "TE"}:
                used = min(surplus, flex_remaining)
                surplus -= used
                flex_remaining -= used
            bench_positions.extend([position] * surplus)
        if len(bench_positions) != 5:
            raise ReplayFailure("roster", "final roster must contain exactly five bench players", counts=dict(counts), bench_positions=bench_positions)
    return dict(sorted(counts.items()))


def replay(bundle: dict[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    report: dict[str, Any] = {"schema_version": 1, "passed": False, "input_digest": digest, "first_failure": None}
    try:
        state, events, snapshots, schedule = _validate_shape(bundle)
        state["picks"] = []
        _advance_turns(state)
        active_snapshot = snapshots[0]
        refresh_items = bundle.get("value_refreshes") or []
        refreshes = {int(item["before_pick"]): int(item["snapshot_index"]) for item in refresh_items}
        if len(refreshes) != len(refresh_items):
            raise ReplayFailure("refresh", "only one value refresh may occur before a pick")
        applied_refresh_indexes: list[int] = []
        participant = int(state["participant"]["roster_id"])
        recommendations = []
        injured_warning_seen = False
        position_run_seen = False
        close_eligible_seen = False
        outside_limit_seen = False
        favorable_qb_matchup_seen = False
        unfavorable_rb_matchup_seen = False
        playoff_weight_seen = False
        roster_collision_seen = False
        flex_collision_seen = False
        keeper_ids = set(map(str, state.get("keepers") or []))
        for event in events:
            pick_no = int(event["pick_no"])
            if pick_no in refreshes:
                index = refreshes[pick_no]
                if index <= 0 or index >= len(snapshots):
                    raise ReplayFailure("refresh", "value refresh references an invalid snapshot", pick_no=pick_no, snapshot_index=index)
                active_snapshot = snapshots[index]
                applied_refresh_indexes.append(index)
            turn = state.get("current_turn")
            if turn and int(turn["owner_roster_id"]) == participant:
                try:
                    recommendation = calculate(state, active_snapshot, clock=lambda: 0.0, schedule=schedule)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ReplayFailure("recommendation", str(exc), pick_no=pick_no, participant_roster_id=participant) from exc
                candidates = [recommendation["calculated_pick"], *recommendation["backup_picks"]]
                ids = [candidate["player_id"] for candidate in candidates]
                if len(ids) != 5 or len(set(ids)) != 5 or set(ids) & set(state.get("selected_player_ids") or []) or set(ids) & keeper_ids:
                    raise ReplayFailure("recommendation", "Recommendation contains unavailable or duplicate Players", pick_no=pick_no, candidate_ids=ids)
                if str(event["player_id"]) not in ids:
                    raise ReplayFailure("recommendation", "Participant selection was not one of the five recommended Players", pick_no=pick_no, selected_player_id=event["player_id"], candidate_ids=ids)
                recommendations.append(_recommendation_summary(recommendation, pick_no, active_snapshot))
                for candidate in candidates:
                    components = candidate.get("components") or {}
                    evidence = candidate.get("schedule_evidence") or {}
                    collision = evidence.get("roster_collision") or {}
                    regular_matchup = float(components.get("regular_season_matchup", 0.0))
                    favorable_qb_matchup_seen |= candidate.get("position") == "QB" and regular_matchup > 0
                    unfavorable_rb_matchup_seen |= candidate.get("position") == "RB" and regular_matchup < 0
                    playoff_weight_seen |= (
                        bool(evidence.get("playoff_weight_applied"))
                        and float(components.get("playoff_matchup", 0.0))
                        > abs(float(components.get("regular_season_matchup", 0.0)))
                    )
                    has_collision = bool(collision.get("collision_weeks"))
                    roster_collision_seen |= has_collision
                    # The fixture's p80 is the first extra RB after direct RB
                    # slots are filled, so this assertion covers FLEX projection.
                    flex_collision_seen |= has_collision and str(candidate.get("player_id")) == "p80"
                injured_warning_seen |= any(candidate.get("injury_warning") for candidate in candidates)
                position_run_seen |= any(candidate.get("position_run_survival_penalty", 0) > 0 for candidate in candidates)
                close_eligible_seen |= any(candidate["model_judgment_eligible"] for candidate in candidates[1:])
                outside_limit_seen |= any(not candidate["model_judgment_eligible"] for candidate in candidates[1:])
            _apply_event(state, event)
            if int(event["roster_id"]) == participant:
                _check_roster(state, active_snapshot, participant)
        state["draft"]["status"] = "complete"
        final_counts = _check_roster(state, active_snapshot, participant, final=True)
        trades = []
        decisions = set()
        counteroffer_seen = False
        future_rejected = False
        for index, check in enumerate(bundle.get("trade_checks") or []):
            try:
                result = evaluate(check["offer"], state, active_snapshot)
                if check.get("expect_error"):
                    raise ReplayFailure("trade", "Trade Evaluation unexpectedly succeeded", evaluation_index=index, result=result)
                if result["decision"] != check.get("expected_decision"):
                    raise ReplayFailure("trade", "Trade Evaluation returned an unexpected decision", evaluation_index=index, expected=check.get("expected_decision"), result=result)
                decisions.add(result["decision"])
                counteroffer_seen |= result.get("counteroffer") is not None
                trades.append(result)
            except ReplayFailure:
                raise
            except ValueError as exc:
                if check.get("expect_error") and check["expect_error"] in str(exc):
                    future_rejected |= "future-season" in str(exc)
                    trades.append({"error": str(exc), "offer": check["offer"]})
                else:
                    raise ReplayFailure("trade", str(exc), evaluation_index=index, offer=check.get("offer")) from exc
        participant_events = [event for event in events if int(event["roster_id"]) == participant]
        rounds_by_special = {str((event.get("metadata") or {}).get("position")): int(event["round"]) for event in participant_events if (event.get("metadata") or {}).get("position") in {"K", "DEF"}}
        traded_turn_seen = any(turn.get("original_roster_id") != turn.get("owner_roster_id") for turn in state["turns"])
        checks = {
            "all_180_picks": len(state["picks"]) == 180,
            "all_15_participant_turns": len(recommendations) == 15 and len(participant_events) == 15,
            "keeper_excluded": bool(keeper_ids),
            "traded_pick_ownership": traded_turn_seen,
            "position_run_changed_survival": position_run_seen,
            "injured_player_warning": injured_warning_seen,
            "ambiguous_match_rejected": any(item.get("reason") == "ambiguous" for snapshot in snapshots for item in snapshot.get("omitted") or []),
            "external_refresh_applied": bool(applied_refresh_indexes) and active_snapshot is snapshots[applied_refresh_indexes[-1]],
            "model_judgment_bounds": close_eligible_seen and outside_limit_seen,
            "trade_decisions": decisions == {"accept", "reject", "close"},
            "useful_counteroffer": counteroffer_seen,
            "future_pick_rejected": future_rejected,
            "k_def_final_rounds": set(rounds_by_special) == {"K", "DEF"} and min(rounds_by_special.values()) >= 13,
            "schedule_context_replayed": schedule is None or all(
                candidate["schedule_data_quality"] == (schedule.get("data_quality") or {}).get("status")
                for item in recommendations
                for candidate in [item["calculated_pick"], *item["backup_picks"]]
            ),
            "schedule_matchup_direction": schedule is None or (favorable_qb_matchup_seen and unfavorable_rb_matchup_seen),
            "schedule_playoff_weighting": schedule is None or not schedule.get("playoff_weeks") or playoff_weight_seen,
            "schedule_roster_collision": schedule is None or roster_collision_seen,
            "schedule_flex_collision": schedule is None or flex_collision_seen,
        }
        failed_check = next((name for name, passed in checks.items() if not passed), None)
        if failed_check:
            raise ReplayFailure("coverage", f"required replay check failed: {failed_check}", check=failed_check, checks=checks)
        report.update({
            "passed": True,
            "summary": {
                "picks_processed": 180,
                "participant_turns": 15,
                "final_roster": final_counts,
                "value_refreshes": len(refreshes),
                "trade_evaluations": len(trades),
                "schedule_context": {
                    "provided": schedule is not None,
                    "data_quality": (schedule.get("data_quality") or {}).get("status") if schedule else "unavailable",
                    "updated_at": schedule.get("updated_at") if schedule else None,
                },
            },
            "checks": checks,
            "recommendations": recommendations,
            "trade_results": trades,
        })
    except ReplayFailure as exc:
        report["first_failure"] = {"stage": exc.stage, "message": str(exc), **exc.context}
    except (KeyError, TypeError, ValueError) as exc:
        report["first_failure"] = {"stage": "input", "message": str(exc)}
    return report
