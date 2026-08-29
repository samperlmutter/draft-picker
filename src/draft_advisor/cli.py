from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from .config import load_config
from .monitor import monitor_pid, refresh, run, start, stop
from .service import ensure_values, read_recommendation, recalculate, validate_risk_fixture
from .sleeper import SleeperClient
from .storage import Storage
from .trade import evaluate
from .replay import replay


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="draft-advisor")
    parser.add_argument("--config", help="path to draft-advisor.json")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="show the current Draft State")
    status.add_argument("--json", action="store_true", dest="json_output")
    status.add_argument("--refresh", action="store_true", help="fetch Sleeper before reporting")
    for name, help_text in (("prepare", "prepare and warm a current recommendation"), ("recommend", "show the warm recommendation"), ("refresh", "refresh external player values")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--json", action="store_true", dest="json_output")
    trade = sub.add_parser("trade", help="evaluate a structured, confirmed Trade Offer")
    trade.add_argument("--offer-file", required=True, help="confirmed JSON offer path, or - for stdin")
    trade.add_argument("--json", action="store_true", dest="json_output")
    replay_command = sub.add_parser("replay", help="replay and verify a complete recorded draft")
    replay_command.add_argument("--input", required=True, help="self-contained replay JSON file")
    replay_command.add_argument("--json", action="store_true", dest="json_output")
    risk = sub.add_parser("risk", help="validate player-risk source data")
    risk_sub = risk.add_subparsers(dest="risk_command", required=True)
    risk_validate = risk_sub.add_parser("validate", help="validate fixture-backed risk observations")
    risk_validate.add_argument("--json", action="store_true", dest="json_output")
    monitor = sub.add_parser("monitor", help="manage the local monitor")
    monitor_sub = monitor.add_subparsers(dest="monitor_command", required=True)
    for name in ("start", "stop", "run"):
        monitor_sub.add_parser(name)
    return parser


def _text(state: dict[str, Any], running: bool) -> str:
    draft = state["draft"]
    participant = state["participant"]
    rules = state["league_rules"]
    age = max(0.0, time.time() - float(state["updated_at"]))
    latest = state.get("latest_pick")
    next_turn = state.get("participant_next_turn")
    order = draft.get("draft_order")
    lines = [
        f"Draft: {draft['status']} ({draft.get('type') or 'type unset'})",
        f"League Rules: {rules.get('teams') or 'unset'} teams, {rules.get('rounds') or 'unset'} rounds; roster {', '.join(rules.get('roster_positions') or []) or 'unset'}",
        f"Participant: {participant['username']} (user {participant['user_id']}, roster {participant['roster_id']})",
        f"Monitor: {'running' if running else 'stopped'}; state age {age:.1f}s",
        f"Start time: {draft.get('start_time') or 'unset'}",
        f"Draft order: {json.dumps(order, sort_keys=True) if order else 'unset'}",
        f"Membership: {'complete' if draft.get('membership_complete') else 'incomplete'}",
        f"Keepers: {', '.join(map(str, state.get('keepers') or [])) if state.get('keepers') else 'unset'}",
        f"Latest pick: #{latest.get('pick_no')} {latest.get('metadata', {}).get('first_name', '')} {latest.get('metadata', {}).get('last_name', '')} ({latest.get('player_id')})" if latest else "Latest pick: none",
        f"Next turn: pick #{next_turn['pick_no']} (round {next_turn['round']}, slot {next_turn['draft_slot']})" if next_turn else "Next turn: unset",
    ]
    roster = state.get("rosters", {}).get(str(participant["roster_id"]), {})
    lines.append("Participant roster: " + (", ".join(roster.get("player_ids") or []) or "empty"))
    return "\n".join(lines)


def _recommendation_text(recommendation: dict[str, Any]) -> str:
    pick = recommendation["calculated_pick"]
    lines = [f"Calculated Pick: {pick['name']} ({pick['position']}, score {pick['draft_score']:.3f})"]
    lines.append(f"Evidence: {pick['roster_fit']}; survival {pick['expected_survival_to_next_turn']:.0%}; scarcity {pick['scarcity']:.3f}")
    components = pick.get("components") or {}
    lines.append(
        "Schedule: "
        f"{pick.get('schedule_data_quality', 'unavailable')}; "
        f"regular {float(components.get('regular_season_matchup', 0.0)):+.3f}; "
        f"playoffs {float(components.get('playoff_matchup', 0.0)):+.3f}; "
        f"collision {float(components.get('roster_collision', 0.0)):+.3f}"
    )
    if pick.get("injury_warning"):
        lines.append(f"Warning: {pick['injury_warning']}")
    lines.append("Backup Picks:")
    for index, backup in enumerate(recommendation["backup_picks"], 1):
        warning = f"; WARNING {backup['injury_warning']}" if backup.get("injury_warning") else ""
        lines.append(f"{index}. {backup['name']} ({backup['position']}, score {backup['draft_score']:.3f}){warning}")
    if recommendation.get("matching_omissions"):
        lines.append(f"Player matches omitted: {len(recommendation['matching_omissions'])}")
    return "\n".join(lines)


def _trade_text(result: dict[str, Any]) -> str:
    lines = [f"Trade: {result['decision'].upper()} — {result['reason']}"]
    if result.get("counteroffer"):
        lines.append("Counteroffer: " + json.dumps(result["counteroffer"], sort_keys=True, separators=(",", ":")))
    return "\n".join(lines)


def _replay_text(result: dict[str, Any]) -> str:
    if not result["passed"]:
        failure = result["first_failure"]
        context = {key: value for key, value in failure.items() if key not in {"stage", "message"}}
        suffix = f" Context: {json.dumps(context, sort_keys=True)}" if context else ""
        return f"Replay FAILED at {failure['stage']}: {failure['message']}.{suffix}"
    summary = result["summary"]
    return f"Replay PASSED: {summary['picks_processed']} picks, {summary['participant_turns']} Participant turns, {summary['trade_evaluations']} trade checks; final roster {json.dumps(summary['final_roster'], sort_keys=True)}."


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "replay":
            with open(args.input) as handle:
                result = replay(json.load(handle))
            print(json.dumps(result, sort_keys=True) if args.json_output else _replay_text(result))
            return 0 if result["passed"] else 1
        if args.command == "risk" and args.risk_command == "validate":
            storage = Storage.from_environment()
            snapshot, report = validate_risk_fixture(storage, SleeperClient().players())
            print(json.dumps({"snapshot": snapshot, "report": report}, sort_keys=True) if args.json_output else f"Risk validation {report['status']}: {report['player_count']} players, {report['observation_count']} observations, {report['matched_count']} matched, {report['unmatched_count']} unmatched, {report['ambiguous_count']} ambiguous; review {report['review_count']}.\nSnapshot: {storage.risk_validation_path}\nReport: {storage.risk_validation_report_path}")
            return 0 if report["status"] == "pass" else 1
        config = load_config(args.config)
        storage = Storage.from_environment()
        if args.command == "status":
            state = refresh(config, storage) if args.refresh else storage.read_state()
            state = dict(state)
            state["state_age_seconds"] = max(0.0, time.time() - float(state["updated_at"]))
            state["monitor_running"] = monitor_pid(storage) is not None
            print(json.dumps(state, sort_keys=True) if args.json_output else _text(state, state["monitor_running"]))
        elif args.command == "recommend":
            recommendation = read_recommendation(storage)
            print(json.dumps(recommendation, sort_keys=True) if args.json_output else _recommendation_text(recommendation))
        elif args.command == "refresh":
            with storage.publication_lock():
                snapshot, _ = ensure_values(config, storage, force=True)
                recommendation = recalculate(storage, snapshot=snapshot)
            result = {"refreshed": True, "player_count": len(snapshot["players"]), "omitted": snapshot.get("omitted") or [], "recommendation": recommendation}
            print(json.dumps(result, sort_keys=True) if args.json_output else f"External values refreshed for {result['player_count']} players.\n{_recommendation_text(recommendation)}")
        elif args.command == "prepare":
            pid, created = start(args.config, storage, config)
            state = refresh(config, storage)
            with storage.publication_lock():
                snapshot, _ = ensure_values(config, storage, force=True)
                # A monitor poll may have accepted a pick after the forced board
                # fetch and before this publication lock. Always bind the warm
                # Recommendation and readiness result to the newest state.
                state = storage.read_state()
                recommendation = recalculate(storage, state, snapshot)
            result = {"ready": True, "monitor_started": created, "monitor_pid": pid, "participant": state["participant"], "next_turn": state.get("participant_next_turn"), "recommendation": recommendation}
            if args.json_output:
                print(json.dumps(result, sort_keys=True))
            else:
                next_turn = result["next_turn"]
                turn_text = f"pick #{next_turn['pick_no']}" if next_turn else "unset"
                print(f"Ready: roster {state['participant']['roster_id']}; next turn {turn_text}; monitor {'started' if created else 'already running'}.\n{_recommendation_text(recommendation)}")
        elif args.command == "trade":
            if args.offer_file == "-":
                offer = json.load(sys.stdin)
            else:
                with open(args.offer_file) as handle:
                    offer = json.load(handle)
            with storage.publication_lock():
                result = evaluate(offer, storage.read_state(), ensure_values(config, storage)[0])
            print(json.dumps(result, sort_keys=True) if args.json_output else _trade_text(result))
        elif args.monitor_command == "start":
            pid, created = start(args.config, storage, config)
            print(f"Monitor {'started' if created else 'already running'} (pid {pid}).")
        elif args.monitor_command == "stop":
            print("Monitor stopped." if stop(storage) else "Monitor was not running.")
        else:
            run(config, storage)
        return 0
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
