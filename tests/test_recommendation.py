from __future__ import annotations

import json
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path

from src.draft_advisor.recommend import _bye_week_penalty
from src.draft_advisor.recommend import calculate
from src.draft_advisor.schedule import build_schedule_snapshot
from tests.test_cli import cli, setup_fixture, write_json


def schedule_fixture(position: str = "QB", *, extreme: bool = False, playoff_only: bool = False) -> dict:
    week_one_other = {"home_team": "EEE", "away_team": "BBB"} if playoff_only else {"home_team": "EEE", "away_team": "FFF"}
    games = [
        {"game_id": "g1", "week": 1, "home_team": "AAA", "away_team": "FFF" if playoff_only else "BBB"},
        {"game_id": "g2", "week": 2, "home_team": "AAA", "away_team": "BBB"},
        {"game_id": "g3", "week": 3, "home_team": "AAA", "away_team": "BBB"},
        {"game_id": "g4", "week": 1, "home_team": "CCC", "away_team": "DDD"},
        {"game_id": "g5", "week": 2, "home_team": "CCC", "away_team": "DDD"},
        {"game_id": "g6", "week": 3, "home_team": "CCC", "away_team": "DDD"},
        {"game_id": "g7", "week": 1, **week_one_other},
        {"game_id": "g8", "week": 2, "home_team": "EEE", "away_team": "FFF"},
        {"game_id": "g9", "week": 3, "home_team": "EEE", "away_team": "FFF"},
    ]
    favorable = 100.0 if extreme else 2.0
    unfavorable = -100.0 if extreme else -2.0
    unit = "offense" if position == "DEF" else "defense"
    return {
        "season": 2026,
        "source": "fixture-recommendation-schedule",
        "teams": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"],
        "regular_season_weeks": [1] if playoff_only else [1, 2],
        "playoff_weeks": [3],
        "games": games,
        "opponent_ratings": {
            "AAA": {unit: {position: 0.0}},
            "BBB": {unit: {position: favorable}},
            "DDD": {unit: {position: unfavorable}},
            "EEE": {unit: {position: 0.0}},
            "FFF": {unit: {position: 0.0}},
        },
    }


def recommendation_players(position: str = "QB") -> dict[str, dict[str, object]]:
    teams = ["AAA", "CCC", "EEE", "FFF", "EEE"]
    return {
        player_id: {
            "player_id": player_id,
            "name": name,
            "team": team,
            "position": position,
            "status": "Active",
            "value": 100.0,
            "adp": 1.0,
            "stability": 0.5,
            "upside": 0.5,
        }
        for player_id, name, team in zip(
            ("fav", "bad", "neutral-a", "neutral-b", "neutral-c"),
            ("Favorable", "Unfavorable", "Neutral A", "Neutral B", "Neutral C"),
            teams,
        )
    }


def recommendation_state(position: str = "QB", *, playoff_window: bool = True) -> dict[str, object]:
    rules: dict[str, object] = {
        "name": "Fixture Recommendation League",
        "season": 2026,
        "teams": 2,
        "rounds": 15,
        "roster_positions": [position, "BN"],
        "scoring_settings": {},
    }
    if playoff_window:
        rules.update({"playoff_week_start": 3, "playoff_rounds": 1})
    return {
        "schema_version": 1,
        "updated_at": 1.0,
        "league_rules": rules,
        "participant": {"roster_id": 8},
        "selected_player_ids": [],
        "picks": [],
        "current_turn": {"pick_no": 1, "round": 14 if position == "DEF" else 1},
        "participant_next_turn": {"pick_no": 1, "round": 14 if position == "DEF" else 1},
        "turns": [],
        "rosters": {"8": {"player_ids": []}},
    }


def prepared_recommendation_schedule(position: str = "QB", *, extreme: bool = False, playoff_only: bool = False) -> dict[str, object]:
    players = recommendation_players(position)
    return build_schedule_snapshot(
        schedule_fixture(position, extreme=extreme, playoff_only=playoff_only),
        players,
        recommendation_state(position)["league_rules"],
        season=2026,
        clock=lambda: 2.0,
    )


class RecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.tmp_path = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_bye_week_penalty_builds_only_after_concentration(self) -> None:
        positions = Counter({("WR", "8"): 3, ("QB", "8"): 1})
        self.assertEqual(_bye_week_penalty("8", "WR", 3, Counter({"8": 2}), Counter({"8": 1}), positions), 0)
        self.assertEqual(_bye_week_penalty("8", "WR", 3, Counter({"8": 3}), Counter({"8": 1}), positions), -1)
        self.assertEqual(_bye_week_penalty("8", "WR", 12, Counter({"8": 3}), Counter({"8": 2}), positions), -3)
        self.assertEqual(_bye_week_penalty("8", "WR", 12, Counter({"8": 4}), Counter({"8": 3}), positions), -9)
        self.assertEqual(_bye_week_penalty("8", "QB", -10, Counter({"8": 1}), Counter({"8": 1}), positions), -4)
        self.assertEqual(_bye_week_penalty("", "QB", -10, Counter({"": 9}), Counter({"": 9}), positions), 0)

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

    def test_cached_schedule_improves_favorable_offensive_matchup(self) -> None:
        players = recommendation_players()
        state = recommendation_state()
        snapshot = {"updated_at": 1.0, "players": players}
        schedule = prepared_recommendation_schedule()

        recommendation = calculate(state, snapshot, clock=lambda: 3.0, schedule=schedule)
        candidates = {candidate["player_id"]: candidate for candidate in [
            recommendation["calculated_pick"], *recommendation["backup_picks"]
        ]}

        self.assertGreater(
            candidates["fav"]["components"]["schedule_adjustment"],
            candidates["bad"]["components"]["schedule_adjustment"],
        )
        self.assertEqual(candidates["fav"]["schedule_data_quality"], "complete")
        self.assertEqual(candidates["fav"]["schedule_evidence"]["weekly_matchups"][0]["week"], 1)
        self.assertIn("regular_season_matchup", candidates["fav"]["components"])
        self.assertIn("playoff_matchup", candidates["fav"]["components"])

    def test_cached_schedule_uses_opposing_offense_for_defense(self) -> None:
        players = recommendation_players("DEF")
        state = recommendation_state("DEF")
        schedule = prepared_recommendation_schedule("DEF")

        recommendation = calculate(state, {"updated_at": 1.0, "players": players}, clock=lambda: 3.0, schedule=schedule)
        candidates = {candidate["player_id"]: candidate for candidate in [
            recommendation["calculated_pick"], *recommendation["backup_picks"]
        ]}

        self.assertGreater(
            candidates["fav"]["components"]["schedule_adjustment"],
            candidates["bad"]["components"]["schedule_adjustment"],
        )
        self.assertEqual(
            candidates["fav"]["schedule_evidence"]["regular_season"]["average_matchup_delta"],
            2.0,
        )

    def test_playoff_value_is_separate_and_requires_league_playoff_window(self) -> None:
        players = recommendation_players()
        snapshot = {"updated_at": 1.0, "players": players}
        schedule = prepared_recommendation_schedule(playoff_only=True)
        with_playoffs = calculate(
            recommendation_state(), snapshot, clock=lambda: 3.0, schedule=schedule
        )
        without_playoffs = calculate(
            recommendation_state(playoff_window=False), snapshot, clock=lambda: 3.0, schedule=schedule
        )
        with_candidate = next(
            candidate for candidate in [with_playoffs["calculated_pick"], *with_playoffs["backup_picks"]]
            if candidate["player_id"] == "fav"
        )
        without_candidate = next(
            candidate for candidate in [without_playoffs["calculated_pick"], *without_playoffs["backup_picks"]]
            if candidate["player_id"] == "fav"
        )

        self.assertEqual(with_candidate["components"]["regular_season_matchup"], 0.0)
        self.assertGreater(with_candidate["components"]["playoff_matchup"], 0.0)
        self.assertTrue(with_candidate["schedule_evidence"]["playoff_weight_applied"])
        self.assertEqual(without_candidate["components"]["playoff_matchup"], 0.0)
        self.assertFalse(without_candidate["schedule_evidence"]["playoff_weight_applied"])

    def test_incomplete_schedule_is_neutral_but_explained(self) -> None:
        players = recommendation_players()
        schedule = prepared_recommendation_schedule()
        schedule["data_quality"] = {"status": "partial", "missing_ratings": [{"week": 2}]}
        recommendation = calculate(
            recommendation_state(), {"updated_at": 1.0, "players": players}, clock=lambda: 3.0, schedule=schedule
        )

        for candidate in [recommendation["calculated_pick"], *recommendation["backup_picks"]]:
            self.assertEqual(candidate["components"]["schedule_adjustment"], 0.0)
            self.assertEqual(candidate["schedule_data_quality"], "partial")

    def test_schedule_adjustment_is_bounded(self) -> None:
        players = recommendation_players()
        schedule = prepared_recommendation_schedule(extreme=True)
        recommendation = calculate(
            recommendation_state(), {"updated_at": 1.0, "players": players}, clock=lambda: 3.0, schedule=schedule
        )

        for candidate in [recommendation["calculated_pick"], *recommendation["backup_picks"]]:
            adjustment = candidate["components"]["schedule_adjustment"]
            self.assertLessEqual(abs(adjustment), 6.0)
            self.assertEqual(adjustment, candidate["schedule_evidence"]["schedule_adjustment"])

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
