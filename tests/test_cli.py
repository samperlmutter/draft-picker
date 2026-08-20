from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value))


def setup_fixture(tmp_path: Path, *, live: bool = False) -> tuple[dict[str, str], Path]:
    fixtures = tmp_path / "fixtures"
    runtime = tmp_path / "runtime"
    fixtures.mkdir()
    runtime.mkdir()
    config = tmp_path / "config.json"
    write_json(config, {"sleeper_league_id": "league-1", "participant_username": "alex", "poll_interval_seconds": 0.1, "external_refresh_interval_seconds": 1800})
    write_json(fixtures / "user__alex.json", {"user_id": "u8", "username": "alex"})
    write_json(fixtures / "league__league-1.json", {"name": "Test League", "settings": {"num_teams": 2}, "scoring_settings": {"rec": 1}, "roster_positions": ["QB", "RB", "WR", "FLEX", "BN"]})
    write_json(fixtures / "league__league-1__users.json", [{"user_id": "u8"}] if not live else [{"user_id": "u8"}, {"user_id": "u9"}])
    write_json(fixtures / "league__league-1__rosters.json", [{"roster_id": 8, "owner_id": "u8", "players": []}, {"roster_id": 9, "owner_id": "u9", "players": []}])
    draft = {"draft_id": "draft-1", "created": 1, "status": "drafting" if live else "pre_draft"}
    write_json(fixtures / "league__league-1__drafts.json", [draft])
    detail = {**draft, "type": "snake", "start_time": 1234 if live else None, "settings": {"teams": 2, "rounds": 3}, "draft_order": {"u8": 1, "u9": 2} if live else None, "slot_to_roster_id": {"1": 8, "2": 9} if live else {}, "metadata": {}}
    write_json(fixtures / "draft__draft-1.json", detail)
    picks = [{"pick_no": 1, "round": 1, "draft_slot": 1, "roster_id": 8, "player_id": "p1", "picked_by": "u8", "metadata": {"first_name": "Ada", "last_name": "Runner"}}] if live else []
    write_json(fixtures / "draft__draft-1__picks.json", picks)
    write_json(fixtures / "draft__draft-1__traded_picks.json", [{"round": 2, "draft_slot": 2, "owner_id": 8, "roster_id": 9, "previous_owner_id": 9}] if live else [])
    players = {
        "p1": {"full_name": "Ada Runner", "team": "AAA", "position": "RB", "status": "Active"},
        "p2": {"full_name": "Bea Catcher", "team": "BBB", "position": "WR", "status": "Active"},
        "p3": {"full_name": "Cal Thrower", "team": "CCC", "position": "QB", "status": "Active"},
        "p4": {"full_name": "Dee Blocker", "team": "DDD", "position": "TE", "status": "Active"},
        "p5": {"full_name": "Eli Runner", "team": "EEE", "position": "RB", "status": "Active"},
        "p6": {"full_name": "Fox Catcher", "team": "FFF", "position": "WR", "status": "Active"},
        "p7": {"full_name": "Gia Runner", "team": "GGG", "position": "RB", "status": "Active"},
        "p8": {"full_name": "Hal Catcher", "team": "HHH", "position": "WR", "status": "Active"},
    }
    write_json(fixtures / "players__nfl.json", players)
    write_json(fixtures / "fantasycalc.json", [{"player": {"sleeperId": player_id, "name": player["full_name"], "maybeTeam": player["team"], "position": player["position"]}, "value": 100 - index * 5, "stability": 0.8, "upside": 0.6} for index, (player_id, player) in enumerate(players.items())])
    write_json(fixtures / "ffc-adp.json", {"players": [{"name": player["full_name"], "team": player["team"], "position": player["position"], "adp": index + 1} for index, player in enumerate(players.values())]})
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(ROOT / "src"), "DRAFT_ADVISOR_CONFIG": str(config), "DRAFT_ADVISOR_FIXTURES": str(fixtures), "DRAFT_ADVISOR_RUNTIME_DIR": str(runtime)})
    return env, fixtures


def cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "draft_advisor", *args], cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.tmp_path = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_pre_draft_status_text_and_json(self) -> None:
        env, _ = setup_fixture(self.tmp_path)
        result = cli(env, "status", "--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Start time: unset", result.stdout)
        self.assertIn("Draft order: unset", result.stdout)
        self.assertIn("Membership: incomplete", result.stdout)
        self.assertIn("Keepers: unset", result.stdout)
        state = json.loads(cli(env, "status", "--json").stdout)
        self.assertEqual(state["draft"]["status"], "pre_draft")
        self.assertIsNone(state["draft"]["draft_order"])
        self.assertGreaterEqual(state["state_age_seconds"], 0)

    def test_pick_rosters_keeper_and_traded_turn_ownership(self) -> None:
        env, fixtures = setup_fixture(self.tmp_path, live=True)
        result = cli(env, "status", "--refresh", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["selected_player_ids"], ["p1"])
        self.assertEqual(state["rosters"]["8"]["drafted_player_ids"], ["p1"])
        self.assertEqual(state["current_turn"]["owner_roster_id"], 9)
        self.assertEqual(state["participant_next_turn"]["pick_no"], 3)
        event_path = Path(env["DRAFT_ADVISOR_RUNTIME_DIR"]) / "pick-events.jsonl"
        self.assertEqual(json.loads(event_path.read_text().splitlines()[0])["type"], "pick")
        detail_path = fixtures / "draft__draft-1.json"
        detail = json.loads(detail_path.read_text())
        detail["metadata"] = {"keepers": ["kept-1"]}
        write_json(detail_path, detail)
        refreshed = json.loads(cli(env, "status", "--refresh", "--json").stdout)
        self.assertIn("kept-1", refreshed["selected_player_ids"])
        self.assertEqual(refreshed["turns"][2]["owner_roster_id"], 8)
        self.assertEqual(len(event_path.read_text().splitlines()), 1)

    def test_monitor_duplicate_start_and_stop(self) -> None:
        env, _ = setup_fixture(self.tmp_path, live=True)
        first = cli(env, "monitor", "start")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("started", first.stdout)
        second = cli(env, "monitor", "start")
        self.assertEqual(second.returncode, 0)
        self.assertIn("already running", second.stdout)
        self.assertEqual(first.stdout.rsplit(" ", 1)[-1], second.stdout.rsplit(" ", 1)[-1])
        stopped = cli(env, "monitor", "stop")
        self.assertEqual(stopped.returncode, 0)
        self.assertIn("stopped", stopped.stdout)

    def test_monitor_polls_and_stops_on_complete(self) -> None:
        env, fixtures = setup_fixture(self.tmp_path, live=True)
        process = subprocess.Popen([sys.executable, "-m", "draft_advisor", "monitor", "run"], cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        runtime = Path(env["DRAFT_ADVISOR_RUNTIME_DIR"])
        deadline = time.monotonic() + 3
        while not (runtime / "draft-state.json").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        picks_path = fixtures / "draft__draft-1__picks.json"
        picks = json.loads(picks_path.read_text())
        picks.append({"pick_no": 2, "round": 1, "draft_slot": 2, "roster_id": 9, "player_id": "p2", "picked_by": "u9", "metadata": {}})
        write_json(picks_path, picks)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and len(json.loads((runtime / "draft-state.json").read_text())["picks"]) != 2:
            time.sleep(0.02)
        self.assertEqual(len(json.loads((runtime / "draft-state.json").read_text())["picks"]), 2)
        deadline = time.monotonic() + 3
        while True:
            recommendation = json.loads((runtime / "recommendation.json").read_text())
            candidate_ids = {recommendation["calculated_pick"]["player_id"], *(pick["player_id"] for pick in recommendation["backup_picks"])}
            if "p2" not in candidate_ids or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        self.assertNotIn("p2", candidate_ids)
        detail_path = fixtures / "draft__draft-1.json"
        detail = json.loads(detail_path.read_text())
        detail["status"] = "complete"
        write_json(detail_path, detail)
        process.wait(timeout=3)
        _, stderr = process.communicate()
        self.assertEqual(process.returncode, 0, stderr)
        self.assertFalse((runtime / "monitor.pid").exists())

    def test_clear_failure_is_nonzero(self) -> None:
        env, _ = setup_fixture(self.tmp_path)
        result = cli(env, "status")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no Draft State", result.stderr)


if __name__ == "__main__":
    unittest.main()
