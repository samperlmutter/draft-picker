from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from .config import load_config
from .monitor import monitor_pid, refresh, run, start, stop
from .storage import Storage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="draft-advisor")
    parser.add_argument("--config", help="path to draft-advisor.json")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="show the current Draft State")
    status.add_argument("--json", action="store_true", dest="json_output")
    status.add_argument("--refresh", action="store_true", help="fetch Sleeper before reporting")
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        storage = Storage.from_environment()
        if args.command == "status":
            state = refresh(config, storage) if args.refresh else storage.read_state()
            state = dict(state)
            state["state_age_seconds"] = max(0.0, time.time() - float(state["updated_at"]))
            state["monitor_running"] = monitor_pid(storage) is not None
            print(json.dumps(state, sort_keys=True) if args.json_output else _text(state, state["monitor_running"]))
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
