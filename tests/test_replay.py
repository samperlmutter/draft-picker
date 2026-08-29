from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.draft_advisor.replay import replay
from src.draft_advisor.risk import build_risk_snapshot
from src.draft_advisor.schedule import build_schedule_snapshot
from tests.test_cli import ROOT, write_json


PARTICIPANT = 8


def build_bundle() -> dict:
    turns = []
    for round_no in range(1, 16):
        slots = range(1, 13) if round_no % 2 else range(12, 0, -1)
        for slot in slots:
            original = slot
            owner = original
            if round_no == 5 and slot == 8:
                owner = 9
            elif round_no == 5 and slot == 9:
                owner = 8
            turns.append({"pick_no": len(turns) + 1, "round": round_no, "draft_slot": slot, "original_roster_id": original, "owner_roster_id": owner, "user_id": f"u{owner}"})

    participant_positions = iter(["QB", "RB", "RB", "WR", "WR", "TE", "RB", "WR", "RB", "WR", "RB", "WR", "RB", "K", "DEF"])
    events = []
    player_positions = {}
    participant_player_ids = []
    participant_index = 0
    for turn in turns:
        player_id = f"p{turn['pick_no']}"
        if turn["owner_roster_id"] == PARTICIPANT:
            position = next(participant_positions)
            if participant_index < 3:
                player_id = ("elite-b", "elite-a", "injured-high")[participant_index]
            participant_index += 1
            participant_player_ids.append(player_id)
        elif turn["pick_no"] in {5, 6, 7}:
            position = "WR"
        else:
            position = ("RB", "WR", "QB", "TE")[(turn["pick_no"] + turn["owner_roster_id"]) % 4]
        player_positions[player_id] = position
        events.append({
            "type": "pick", "pick_no": turn["pick_no"], "round": turn["round"],
            "draft_slot": turn["draft_slot"], "roster_id": turn["owner_roster_id"],
            "player_id": player_id, "picked_by": f"u{turn['owner_roster_id']}",
            "metadata": {"first_name": "Player", "last_name": str(turn["pick_no"]), "position": position, "team": f"T{turn['pick_no'] % 32}"},
        })

    players = {}
    for index in range(1, 221):
        player_id = f"p{index}" if index <= 180 else f"pool-{index}"
        position = player_positions.get(player_id, ("RB", "WR", "QB", "TE")[index % 4])
        players[player_id] = {
            "player_id": player_id, "name": f"Player {index}", "team": f"T{index % 32}",
            "position": position, "status": "Active", "injury_status": None,
            "value": 1000 - index * 3, "adp": float(index), "stability": 0.7, "upside": 0.7,
        }
    players["elite-a"] = {"player_id": "elite-a", "name": "Elite A", "team": "EA", "position": "RB", "status": "Active", "injury_status": None, "value": 3000, "adp": 1.0, "stability": 0.9, "upside": 0.9}
    players["elite-b"] = {"player_id": "elite-b", "name": "Elite B", "team": "EB", "position": "QB", "status": "Active", "injury_status": None, "value": 2900, "adp": 2.0, "stability": 0.9, "upside": 0.9}
    players["injured-high"] = {"player_id": "injured-high", "name": "Injured High", "team": "IH", "position": "RB", "status": "Active", "injury_status": "OUT", "value": 2800, "adp": 3.0, "stability": 0.8, "upside": 0.8}
    snapshot = {"schema_version": 1, "updated_at": 1, "format": "12-team one-QB full-PPR", "players": players, "omitted": [{"source": "fantasycalc", "name": "Ambiguous Twin", "reason": "ambiguous"}]}
    refreshed = copy.deepcopy(snapshot)
    refreshed["updated_at"] = 2
    refreshed["players"]["pool-220"]["value"] = 1500
    rosters = {str(roster_id): {"roster_id": roster_id, "owner_id": f"u{roster_id}", "players": [], "player_ids": [], "drafted_player_ids": []} for roster_id in range(1, 13)}
    roster_positions = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF", "BN", "BN", "BN", "BN", "BN"]
    state = {
        "schema_version": 1, "updated_at": 0, "league_id": "replay-league",
        "league_rules": {"name": "Replay League", "season": 2026, "teams": 12, "rounds": 15, "roster_positions": roster_positions, "scoring_settings": {"rec": 1}, "playoff_week_start": 3, "playoff_rounds": 1},
        "participant": {"username": "replay", "user_id": "u8", "roster_id": PARTICIPANT},
        "draft": {"draft_id": "replay-draft", "type": "snake", "status": "drafting", "start_time": 1, "draft_order": {f"u{i}": i for i in range(1, 13)}, "membership_complete": True},
        "picks": [], "latest_pick": None, "selected_player_ids": ["p1"], "keepers": ["p1"],
        "traded_picks": [{"round": 5, "draft_slot": 8, "owner_id": 9}, {"round": 5, "draft_slot": 9, "owner_id": 8}],
        "turns": turns, "current_turn": turns[0], "participant_next_turn": next(turn for turn in turns if turn["owner_roster_id"] == PARTICIPANT), "rosters": rosters,
    }
    early_participant = participant_player_ids[0]
    close_participant = participant_player_ids[3]
    late_participant = participant_player_ids[-1]
    trade_checks = [
        {"offer": {"confirmed": True, "give": [{"type": "player", "player_id": late_participant}], "receive": [{"type": "player", "player_id": "p2"}]}, "expected_decision": "accept"},
        {"offer": {"confirmed": True, "give": [{"type": "player", "player_id": early_participant}], "receive": [{"type": "player", "player_id": "p170"}]}, "expected_decision": "reject"},
        {"offer": {"confirmed": True, "give": [{"type": "player", "player_id": close_participant}], "receive": [{"type": "player", "player_id": "p42"}]}, "expected_decision": "close"},
        {"offer": {"confirmed": True, "give": [{"type": "player", "player_id": early_participant}], "receive": [{"type": "pick", "pick_no": 180, "season": 2027}]}, "expect_error": "future-season"},
    ]
    return {"initial_state": state, "events": events, "value_snapshots": [snapshot, refreshed], "value_refreshes": [{"before_pick": 90, "snapshot_index": 1}], "trade_checks": trade_checks}


def build_replay_schedule(bundle: dict, *, without_playoffs: bool = False) -> dict:
    """Build a complete, source-free schedule context for the replay fixture."""
    state = bundle["initial_state"]
    players = bundle["value_snapshots"][0]["players"]
    players["elite-a"]["team"] = "SCHEDULE-A"
    players["elite-b"]["team"] = "SCHEDULE-B"
    players["injured-high"]["team"] = "SCHEDULE-D"
    players["p80"]["team"] = "SCHEDULE-C"
    players["p80"]["value"] = 820
    payload = {
        "season": 2026,
        "source": "fixture-replay-schedule",
        "regular_season_weeks": [1, 2, 3] if without_playoffs else [1, 2],
        "playoff_weeks": [] if without_playoffs else [3],
        "games": [
            {"game_id": "fixture-1", "week": 1, "home_team": "SCHEDULE-A", "away_team": "SCHEDULE-B"},
            {"game_id": "fixture-2", "week": 2, "home_team": "SCHEDULE-A", "away_team": "SCHEDULE-B"},
            {"game_id": "fixture-3", "week": 3, "home_team": "SCHEDULE-A", "away_team": "SCHEDULE-B"},
            {"game_id": "fixture-4", "week": 1, "home_team": "SCHEDULE-C", "away_team": "SCHEDULE-D"},
            {"game_id": "fixture-5", "week": 2, "home_team": "SCHEDULE-C", "away_team": "SCHEDULE-D"},
            {"game_id": "fixture-6", "week": 3, "home_team": "SCHEDULE-C", "away_team": "SCHEDULE-D"},
        ],
        "opponent_ratings": {
            "SCHEDULE-A": {"defense": {"QB": 1.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}, "offense": {"DEF": 0.0}},
            "SCHEDULE-B": {"defense": {"QB": 0.0, "RB": -1.0, "WR": 0.0, "TE": 0.0}, "offense": {"DEF": 0.0}},
            "SCHEDULE-C": {"defense": {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}, "offense": {"DEF": 0.0}},
            "SCHEDULE-D": {"defense": {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 0.0}, "offense": {"DEF": 0.0}},
        },
    }
    return build_schedule_snapshot(
        payload,
        players,
        state["league_rules"],
        season=2026,
        clock=lambda: 17.0,
    )


class ReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.tmp_path = Path(self.temporary.name)
        self.input_path = self.tmp_path / "complete-replay.json"
        self.env = os.environ.copy()
        self.env.update({"PYTHONPATH": str(ROOT / "src"), "DRAFT_ADVISOR_CONFIG": str(self.tmp_path / "must-not-be-read-config.json"), "DRAFT_ADVISOR_RUNTIME_DIR": str(self.tmp_path / "runtime"), "DRAFT_ADVISOR_FIXTURES": str(self.tmp_path / "must-not-be-read")})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_replay(self, json_output=True):
        args = [sys.executable, "-m", "draft_advisor", "replay", "--input", str(self.input_path)]
        if json_output:
            args.append("--json")
        return subprocess.run(args, cwd=ROOT, env=self.env, text=True, capture_output=True, timeout=20)

    def test_complete_180_pick_replay_is_deterministic_and_network_free(self) -> None:
        write_json(self.input_path, build_bundle())
        first = self.run_replay()
        self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
        second = self.run_replay()
        self.assertEqual(second.returncode, 0, second.stderr or second.stdout)
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["summary"]["picks_processed"], 180)
        self.assertEqual(result["summary"]["participant_turns"], 15)
        self.assertEqual(len(result["recommendations"]), 15)
        self.assertTrue(all(len(item["backup_picks"]) == 4 for item in result["recommendations"]))
        self.assertTrue(all(result["checks"].values()))
        self.assertTrue(all(candidate["schedule_data_quality"] == "unavailable" for item in result["recommendations"] for candidate in [item["calculated_pick"], *item["backup_picks"]]))
        self.assertTrue(all(candidate["schedule_adjustment"] == 0.0 for item in result["recommendations"] for candidate in [item["calculated_pick"], *item["backup_picks"]]))
        before_refresh = [item for item in result["recommendations"] if item["pick_no"] < 90]
        after_refresh = [item for item in result["recommendations"] if item["pick_no"] >= 90]
        self.assertFalse(any(candidate["player_id"] == "pool-220" for item in before_refresh for candidate in [item["calculated_pick"], *item["backup_picks"]]))
        self.assertTrue(any(candidate["player_id"] == "pool-220" for item in after_refresh for candidate in [item["calculated_pick"], *item["backup_picks"]]))
        self.assertEqual({item.get("decision") for item in result["trade_results"] if item.get("decision")}, {"accept", "reject", "close"})
        self.assertFalse((self.tmp_path / "runtime").exists())
        text = self.run_replay(json_output=False)
        self.assertEqual(text.returncode, 0)
        self.assertIn("Replay PASSED: 180 picks, 15 Participant turns", text.stdout)

    def test_replay_summary_preserves_risk_metadata(self) -> None:
        bundle = build_bundle()
        risk_snapshot = build_risk_snapshot(bundle["value_snapshots"][0]["players"], clock=lambda: 17.0)
        bundle["risk_snapshot"] = risk_snapshot

        result = replay(bundle)

        self.assertTrue(result["passed"], result["first_failure"])
        candidates = [
            candidate
            for item in result["recommendations"]
            for candidate in [item["calculated_pick"], *item["backup_picks"]]
        ]
        self.assertTrue(candidates)
        self.assertTrue(all(candidate["risk_state"] == "unknown" for candidate in candidates))
        self.assertTrue(all(candidate["risk_visible"] is True for candidate in candidates))

    def test_prepared_schedule_context_is_replayed_without_source_requests(self) -> None:
        bundle = build_bundle()
        bundle["schedule_snapshot"] = build_replay_schedule(bundle)
        write_json(self.input_path, bundle)
        with patch("urllib.request.urlopen", side_effect=AssertionError("replay must not fetch sources")):
            direct = replay(bundle)
        self.assertTrue(direct["passed"], direct["first_failure"])
        first = self.run_replay()
        second = self.run_replay()
        self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
        self.assertEqual(second.returncode, 0, second.stderr or second.stdout)
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertTrue(result["passed"])
        self.assertTrue(result["checks"]["schedule_context_replayed"])
        self.assertEqual(result["summary"]["schedule_context"]["data_quality"], "complete")
        self.assertTrue(result["summary"]["schedule_context"]["provided"])
        for item in result["recommendations"]:
            candidates = [item["calculated_pick"], *item["backup_picks"]]
            self.assertTrue(all(candidate["schedule_data_quality"] == "complete" for candidate in candidates))
        self.assertTrue(any(item["calculated_pick"]["schedule_adjustment"] != 0.0 for item in result["recommendations"]))
        self.assertTrue(result["checks"]["schedule_matchup_direction"])
        self.assertTrue(result["checks"]["schedule_playoff_weighting"])
        self.assertTrue(result["checks"]["schedule_roster_collision"])
        self.assertTrue(result["checks"]["schedule_flex_collision"])
        flex_candidates = [candidate for item in result["recommendations"] for candidate in [item["calculated_pick"], *item["backup_picks"]] if candidate["player_id"] == "p80"]
        self.assertTrue(any(candidate["candidate_is_projected_starter"] and candidate["collision_weeks"] for candidate in flex_candidates))

    def test_schedule_without_playoff_weeks_replays_successfully(self) -> None:
        bundle = build_bundle()
        bundle["schedule_snapshot"] = build_replay_schedule(bundle, without_playoffs=True)

        result = replay(bundle)

        self.assertTrue(result["passed"], result["first_failure"])
        self.assertTrue(result["checks"]["schedule_context_replayed"])
        self.assertTrue(result["checks"]["schedule_matchup_direction"])
        self.assertTrue(result["checks"]["schedule_playoff_weighting"])

    def test_replay_rejects_incompatible_schedule_cache_with_context(self) -> None:
        bundle = build_bundle()
        schedule = build_replay_schedule(bundle)
        schedule["league_rules_identity"] = "stale-cache"
        bundle["schedule_snapshot"] = schedule
        write_json(self.input_path, bundle)
        failed = self.run_replay()
        self.assertNotEqual(failed.returncode, 0)
        result = json.loads(failed.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["first_failure"]["stage"], "schedule")
        self.assertEqual(result["first_failure"]["schedule_identity"], "stale-cache")
        self.assertIn("League Rules identity", result["first_failure"]["message"])

    def test_failure_reports_first_pick_with_context(self) -> None:
        bundle = build_bundle()
        bundle["events"][41]["pick_no"] = 99
        write_json(self.input_path, bundle)
        failed = self.run_replay()
        self.assertNotEqual(failed.returncode, 0)
        result = json.loads(failed.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["first_failure"]["stage"], "pick")
        self.assertEqual(result["first_failure"]["pick_no"], 99)
        self.assertIn("expected ordered pick event #42", result["first_failure"]["message"])
        text = self.run_replay(json_output=False)
        self.assertIn("Replay FAILED at pick", text.stdout)
        self.assertIn("pick_no", text.stdout)

    def test_trade_failure_reports_evaluation_context(self) -> None:
        bundle = build_bundle()
        bundle["trade_checks"][0]["expected_decision"] = "reject"
        write_json(self.input_path, bundle)
        failed = self.run_replay()
        self.assertNotEqual(failed.returncode, 0)
        result = json.loads(failed.stdout)
        self.assertEqual(result["first_failure"]["stage"], "trade")
        self.assertEqual(result["first_failure"]["evaluation_index"], 0)
        self.assertEqual(result["first_failure"]["expected"], "reject")
        self.assertEqual(result["first_failure"]["result"]["decision"], "accept")


if __name__ == "__main__":
    unittest.main()
