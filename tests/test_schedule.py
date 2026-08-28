from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from src.draft_advisor.config import Config
from src.draft_advisor.schedule import build_schedule_snapshot, validate_schedule_snapshot
from src.draft_advisor.service import ensure_schedule
from src.draft_advisor.storage import Storage


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value))


def fixture_payload() -> dict:
    return {
        "season": 2026,
        "source": "fixture-nfl-schedule",
        "source_updated_at": "2026-08-01T12:00:00Z",
        "teams": ["AAA", "BBB", "CCC"],
        "regular_season_weeks": [1, 2],
        "playoff_weeks": [3],
        "games": [
            {"game_id": "g1", "week": 1, "home_team": "AAA", "away_team": "BBB"},
            {"game_id": "g2", "week": 2, "home_team": "AAA", "away_team": "CCC"},
            {"game_id": "g3", "week": 3, "home_team": "AAA", "away_team": "BBB"},
        ],
        "opponent_ratings": {
            "AAA": {"offense": {"DEF": 1.25}},
            "BBB": {"defense": {"QB": 0.75, "RB": 0.5}},
            "CCC": {"defense": {"QB": -0.75, "RB": -0.5}},
        },
    }


def players() -> dict[str, dict[str, object]]:
    return {
        "qb-aaa": {"name": "Quarterback", "team": "AAA", "position": "QB"},
        "def-bbb": {"name": "Defense", "team": "BBB", "position": "DEF"},
    }


def state() -> dict[str, object]:
    return {
        "league_rules": {
            "name": "Fixture League",
            "season": 2026,
            "teams": 2,
            "rounds": 15,
            "roster_positions": ["QB", "DEF", "BN"],
            "scoring_settings": {},
        }
    }


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temporary.name)
        self.fixtures = self.root / "fixtures"
        self.fixtures.mkdir()
        self.runtime = self.root / "runtime"
        self.env = os.environ.copy()
        self.env["DRAFT_ADVISOR_FIXTURES"] = str(self.fixtures)
        self.config = Config(
            sleeper_league_id="league-1",
            participant_username="alex",
            season=2026,
            schedule_refresh_interval_seconds=100,
        )
        self.storage = Storage(self.runtime)
        self.snapshot = {"players": players()}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fixture_preparation_derives_schedule_layers_and_metadata(self) -> None:
        write_json(self.fixtures / "schedule.json", fixture_payload())
        previous = os.environ.get("DRAFT_ADVISOR_FIXTURES")
        os.environ["DRAFT_ADVISOR_FIXTURES"] = str(self.fixtures)
        try:
            prepared, changed = ensure_schedule(
                self.config, self.storage, state(), self.snapshot, force=True, clock=lambda: 100.0
            )
        finally:
            if previous is None:
                os.environ.pop("DRAFT_ADVISOR_FIXTURES", None)
            else:
                os.environ["DRAFT_ADVISOR_FIXTURES"] = previous
        self.assertTrue(changed)
        assert prepared is not None
        self.assertEqual(validate_schedule_snapshot(prepared), prepared)
        self.assertEqual(prepared["season"], 2026)
        self.assertEqual(prepared["regular_season_weeks"], [1, 2])
        self.assertEqual(prepared["playoff_weeks"], [3])
        self.assertEqual(prepared["team_schedule"]["BBB"]["1"]["opponent"], "AAA")
        self.assertEqual(prepared["bye_weeks"]["BBB"], [2])
        self.assertEqual(prepared["team_collisions"]["AAA|BBB"], [1, 3])
        self.assertEqual(prepared["player_matchups"]["qb-aaa"]["1"]["matchup_delta"], 0.75)
        self.assertEqual(prepared["player_matchups"]["qb-aaa"]["2"]["matchup_delta"], -0.75)
        self.assertEqual(prepared["player_matchups"]["def-bbb"]["1"]["matchup_delta"], 1.25)
        self.assertEqual(prepared["player_schedule_summaries"]["qb-aaa"]["regular_season"]["byes"], 0)
        self.assertEqual(prepared["player_schedule_summaries"]["def-bbb"]["regular_season"]["byes"], 1)
        self.assertEqual(prepared["data_quality"]["status"], "complete")
        self.assertEqual(prepared["source"]["name"], "fixture-nfl-schedule")
        self.assertTrue(prepared["input_checksum"])
        self.assertTrue(prepared["league_rules_identity"])
        self.assertEqual(json.loads(self.storage.schedule_path.read_text()), prepared)

    def test_identical_inputs_reuse_fresh_cache_without_refetching(self) -> None:
        class CountingClient:
            calls = 0

            def schedule(self, season: int) -> dict:
                self.calls += 1
                return fixture_payload()

        client = CountingClient()
        first, changed = ensure_schedule(
            self.config, self.storage, state(), self.snapshot, client, force=True, clock=lambda: 100.0
        )
        second, reused_changed = ensure_schedule(
            self.config, self.storage, state(), self.snapshot, client, clock=lambda: 101.0
        )
        self.assertTrue(changed)
        self.assertFalse(reused_changed)
        self.assertEqual(client.calls, 1)
        self.assertEqual(second, first)

    def test_changed_league_rules_do_not_reuse_a_different_cache_key(self) -> None:
        class CountingClient:
            calls = 0

            def schedule(self, season: int) -> dict:
                self.calls += 1
                return fixture_payload()

        client = CountingClient()
        first, _ = ensure_schedule(
            self.config, self.storage, state(), self.snapshot, client, force=True, clock=lambda: 100.0
        )
        changed_state = deepcopy(state())
        changed_state["league_rules"]["playoff_week_start"] = 3
        second, changed = ensure_schedule(
            self.config, self.storage, changed_state, self.snapshot, client, clock=lambda: 101.0
        )
        self.assertTrue(changed)
        self.assertEqual(client.calls, 2)
        self.assertNotEqual(second["league_rules_identity"], first["league_rules_identity"])

    def test_invalid_refresh_preserves_last_valid_snapshot_atomically(self) -> None:
        class FixtureClient:
            def __init__(self) -> None:
                self.payload: object = fixture_payload()

            def schedule(self, season: int) -> object:
                return self.payload

        client = FixtureClient()
        first, _ = ensure_schedule(
            self.config, self.storage, state(), self.snapshot, client, force=True, clock=lambda: 100.0
        )
        accepted = self.storage.schedule_path.read_bytes()
        client.payload = {"season": 2026, "games": []}
        reused, changed = ensure_schedule(
            self.config, self.storage, state(), self.snapshot, client, clock=lambda: 1000.0
        )
        self.assertFalse(changed)
        self.assertEqual(reused, first)
        self.assertEqual(self.storage.schedule_path.read_bytes(), accepted)

    def test_partial_refresh_preserves_valid_cache_and_has_neutral_fallback(self) -> None:
        class FixtureClient:
            def __init__(self) -> None:
                self.payload: object = fixture_payload()

            def schedule(self, season: int) -> object:
                return self.payload

        client = FixtureClient()
        first, _ = ensure_schedule(
            self.config, self.storage, state(), self.snapshot, client, force=True, clock=lambda: 100.0
        )
        accepted = self.storage.schedule_path.read_bytes()
        partial = fixture_payload()
        del partial["opponent_ratings"]["BBB"]["defense"]["QB"]
        client.payload = partial
        preserved, changed = ensure_schedule(
            self.config, self.storage, state(), self.snapshot, client, force=True, clock=lambda: 1000.0
        )
        self.assertFalse(changed)
        self.assertEqual(preserved, first)
        self.assertEqual(self.storage.schedule_path.read_bytes(), accepted)

        self.storage.schedule_path.unlink()
        fallback, changed = ensure_schedule(
            self.config, self.storage, state(), self.snapshot, client, force=True, clock=lambda: 1001.0
        )
        self.assertIsNone(fallback)
        self.assertFalse(changed)

    def test_changed_player_inputs_invalidate_schedule_cache(self) -> None:
        class CountingClient:
            calls = 0

            def schedule(self, season: int) -> dict:
                self.calls += 1
                payload = fixture_payload()
                payload["opponent_ratings"]["AAA"]["defense"] = {"QB": 0.0}
                return payload

        client = CountingClient()
        first, _ = ensure_schedule(
            self.config, self.storage, state(), self.snapshot, client, force=True, clock=lambda: 100.0
        )
        changed_snapshot = deepcopy(self.snapshot)
        changed_snapshot["players"]["qb-aaa"]["team"] = "CCC"
        second, changed = ensure_schedule(
            self.config, self.storage, state(), changed_snapshot, client, clock=lambda: 101.0
        )
        self.assertTrue(changed)
        self.assertEqual(client.calls, 2)
        self.assertNotEqual(second["input_checksum"], first["input_checksum"])
        self.assertTrue(second["player_matchups"]["qb-aaa"]["1"]["bye"])

    def test_build_is_deterministic_for_identical_fixture_inputs(self) -> None:
        first = build_schedule_snapshot(
            fixture_payload(), players(), state()["league_rules"], season=2026, clock=lambda: 100.0
        )
        second = build_schedule_snapshot(
            fixture_payload(), players(), state()["league_rules"], season=2026, clock=lambda: 100.0
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
