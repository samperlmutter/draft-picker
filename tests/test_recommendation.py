from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_cli import cli, setup_fixture, write_json


class RecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.tmp_path = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_and_warm_recommendation_text_json_and_performance(self) -> None:
        env, _ = setup_fixture(self.tmp_path, live=True)
        prepared = cli(env, "prepare", "--json")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        result = json.loads(prepared.stdout)
        self.assertTrue(result["ready"])
        self.assertTrue(result["monitor_started"])
        self.assertEqual(result["participant"]["roster_id"], 8)
        self.assertIsNotNone(result["next_turn"])
        self.assertEqual(len(result["recommendation"]["backup_picks"]), 4)
        # Cross several controlled monitor polls; unchanged source content must
        # not republish the value snapshot or warm Recommendation.
        time.sleep(0.35)
        started = time.perf_counter()
        warm = cli(env, "recommend", "--json")
        elapsed = time.perf_counter() - started
        self.assertEqual(warm.returncode, 0, warm.stderr)
        self.assertLess(elapsed, 1.0)
        recommendation = json.loads(warm.stdout)
        self.assertEqual(recommendation, result["recommendation"])
        self.assertNotIn("confidence", warm.stdout.lower())
        text = cli(env, "recommend")
        self.assertIn("Calculated Pick:", text.stdout)
        self.assertIn("Backup Picks:", text.stdout)
        again = json.loads(cli(env, "prepare", "--json").stdout)
        self.assertFalse(again["monitor_started"])
        cli(env, "monitor", "stop")

    def test_deterministic_evidence_model_eligibility_and_primary_value(self) -> None:
        env, _ = setup_fixture(self.tmp_path, live=True)
        self.assertEqual(cli(env, "status", "--refresh").returncode, 0)
        first = json.loads(cli(env, "recommend", "--json").stdout)
        second = json.loads(cli(env, "recommend", "--json").stdout)
        self.assertEqual(first, second)
        candidates = [first["calculated_pick"], *first["backup_picks"]]
        scores = [candidate["draft_score"] for candidate in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for candidate in candidates:
            self.assertEqual(candidate["score_type"], "relative comparison")
            self.assertIn("primary_value", candidate["components"])
            self.assertIn("roster_fit", candidate)
            self.assertIn("expected_survival_to_next_turn", candidate)
            self.assertIn("relevant_opponent_needs", candidate)
            self.assertEqual(candidate["model_judgment_eligible"], candidate["draft_score"] >= scores[0] * 0.95)
        self.assertEqual(first["calculated_pick"]["player_id"], "p2")
        self.assertGreater(first["calculated_pick"]["components"]["opponent_demand"], 0)
        self.assertEqual(first["calculated_pick"]["relevant_opponent_needs"], {"WR": 1})

    def test_injuries_inactive_keepers_and_selected_players_are_respected(self) -> None:
        env, fixtures = setup_fixture(self.tmp_path, live=True)
        players_path = fixtures / "players__nfl.json"
        players = json.loads(players_path.read_text())
        players["p2"]["injury_status"] = "OUT"
        players["p3"]["status"] = "Inactive"
        write_json(players_path, players)
        detail_path = fixtures / "draft__draft-1.json"
        detail = json.loads(detail_path.read_text())
        detail["metadata"] = {"keepers": ["p4"]}
        write_json(detail_path, detail)
        # Add players so exclusions still leave five candidates.
        self._extend_players(fixtures, 4)
        fantasycalc_path = fixtures / "fantasycalc.json"
        fantasycalc = json.loads(fantasycalc_path.read_text())
        next(row for row in fantasycalc if (row.get("player") or {}).get("sleeperId") == "p2")["value"] = 200
        write_json(fantasycalc_path, fantasycalc)
        result = cli(env, "status", "--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        recommendation = json.loads(cli(env, "recommend", "--json").stdout)
        candidates = [recommendation["calculated_pick"], *recommendation["backup_picks"]]
        ids = {candidate["player_id"] for candidate in candidates}
        self.assertNotIn("p1", ids)
        self.assertNotIn("p3", ids)
        self.assertNotIn("p4", ids)
        injured = next(candidate for candidate in candidates if candidate["player_id"] == "p2")
        self.assertLess(injured["components"]["injury_penalty"], 0)
        self.assertIn("OUT", injured["injury_warning"])

    def test_matching_omissions_and_failed_refresh_preserves_atomic_snapshot(self) -> None:
        env, fixtures = setup_fixture(self.tmp_path, live=True)
        fantasycalc_path = fixtures / "fantasycalc.json"
        rows = json.loads(fantasycalc_path.read_text())
        rows.append({"player": {"name": "Unknown Twin", "maybeTeam": "ZZZ", "position": "WR"}, "value": 70})
        write_json(fantasycalc_path, rows)
        refreshed = cli(env, "status", "--refresh")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        recommendation = json.loads(cli(env, "recommend", "--json").stdout)
        self.assertTrue(any(item["name"] == "Unknown Twin" for item in recommendation["matching_omissions"]))
        values_path = Path(env["DRAFT_ADVISOR_RUNTIME_DIR"]) / "player-values.json"
        accepted = values_path.read_bytes()
        write_json(fantasycalc_path, rows[:2])
        failed = cli(env, "refresh", "--json")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("incomplete", failed.stderr)
        self.assertEqual(values_path.read_bytes(), accepted)

    def test_explicit_and_stale_external_refresh(self) -> None:
        env, fixtures = setup_fixture(self.tmp_path, live=True)
        first = cli(env, "status", "--refresh")
        self.assertEqual(first.returncode, 0, first.stderr)
        values_path = Path(env["DRAFT_ADVISOR_RUNTIME_DIR"]) / "player-values.json"
        old = json.loads(values_path.read_text())
        old["updated_at"] = 0
        write_json(values_path, old)
        refreshed = cli(env, "status", "--refresh")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertGreater(json.loads(values_path.read_text())["updated_at"], 0)
        explicit = cli(env, "refresh", "--json")
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertTrue(json.loads(explicit.stdout)["refreshed"])

    def test_early_round_excludes_kicker_and_defense_and_flex_is_open(self) -> None:
        env, fixtures = setup_fixture(self.tmp_path, live=True)
        self._extend_players(fixtures, 2, positions=("K", "DEF"), value_start=1000)
        result = cli(env, "status", "--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        recommendation = json.loads(cli(env, "recommend", "--json").stdout)
        candidates = [recommendation["calculated_pick"], *recommendation["backup_picks"]]
        self.assertFalse({"K", "DEF"} & {candidate["position"] for candidate in candidates})
        self.assertTrue(any("FLEX" in candidate["roster_fit"] for candidate in candidates if candidate["position"] in {"RB", "WR", "TE"}))

    def test_kicker_and_defense_become_eligible_only_in_final_rounds(self) -> None:
        env, fixtures = setup_fixture(self.tmp_path, live=True)
        league_path = fixtures / "league__league-1.json"
        league = json.loads(league_path.read_text())
        league["roster_positions"] = ["QB", "RB", "WR", "FLEX", "K", "DEF", "BN"]
        write_json(league_path, league)
        self._extend_players(fixtures, 2, positions=("K", "DEF"), value_start=1000)
        early = cli(env, "status", "--refresh")
        self.assertEqual(early.returncode, 0, early.stderr)
        early_candidates = json.loads(cli(env, "recommend", "--json").stdout)
        self.assertFalse({"K", "DEF"} & {item["position"] for item in [early_candidates["calculated_pick"], *early_candidates["backup_picks"]]})
        picks_path = fixtures / "draft__draft-1__picks.json"
        picks = json.loads(picks_path.read_text())
        picks.append({"pick_no": 2, "round": 1, "draft_slot": 2, "roster_id": 9, "player_id": "p2", "picked_by": "u9", "metadata": {}})
        write_json(picks_path, picks)
        late = cli(env, "status", "--refresh")
        self.assertEqual(late.returncode, 0, late.stderr)
        late_candidates = json.loads(cli(env, "recommend", "--json").stdout)
        self.assertIn(late_candidates["calculated_pick"]["position"], {"K", "DEF"})

    def _extend_players(self, fixtures: Path, count: int, positions: tuple[str, ...] = ("RB", "WR"), value_start: float = 70) -> None:
        players_path = fixtures / "players__nfl.json"
        fc_path = fixtures / "fantasycalc.json"
        adp_path = fixtures / "ffc-adp.json"
        players = json.loads(players_path.read_text())
        fc = json.loads(fc_path.read_text())
        adp = json.loads(adp_path.read_text())
        for index in range(count):
            player_id = f"extra-{index}"
            position = positions[index % len(positions)]
            player = {"full_name": f"Extra Player {index}", "team": f"X{index}", "position": position, "status": "Active"}
            players[player_id] = player
            fc.append({"player": {"sleeperId": player_id, "name": player["full_name"], "maybeTeam": player["team"], "position": position}, "value": value_start - index, "stability": 0.5, "upside": 0.8})
            adp["players"].append({"name": player["full_name"], "team": player["team"], "position": position, "adp": 100 + index})
        write_json(players_path, players)
        write_json(fc_path, fc)
        write_json(adp_path, adp)
