from __future__ import annotations

import unittest
from collections import Counter

from src.draft_advisor.recommend import calculate
from src.draft_advisor.replay import _check_roster
from src.draft_advisor.rules import OFFICIAL_ROSTER, validate_roster_config
from src.draft_advisor.values import validate_value_snapshot


class RuleTests(unittest.TestCase):
    def test_official_roster_is_accepted_and_idp_slots_are_rejected(self) -> None:
        validate_roster_config(OFFICIAL_ROSTER, 12, 15, official=True)
        with self.assertRaisesRegex(ValueError, "IDP|unsupported"):
            validate_roster_config([*OFFICIAL_ROSTER[:-1], "DL", "BN"], 12, 15)

    def test_idp_players_are_not_recommended_or_accepted_in_snapshots(self) -> None:
        players = {
            f"wr-{index}": {
                "name": f"Receiver {index}", "position": "WR", "value": 100 - index,
                "status": "Active", "team": f"T{index}",
            }
            for index in range(5)
        }
        players["idp"] = {
            "name": "Individual Defender", "position": "LB", "value": 1000,
            "status": "Active", "team": "DEF",
        }
        state = {
            "league_rules": {"roster_positions": ["QB", "BN"], "rounds": 15},
            "participant": {"roster_id": 8}, "selected_player_ids": [], "picks": [],
            "current_turn": {"pick_no": 1, "round": 1},
            "participant_next_turn": {"pick_no": 1, "round": 1},
            "turns": [], "rosters": {"8": {"player_ids": []}}, "updated_at": 1,
        }
        recommendation = calculate(state, {"players": players, "updated_at": 1})
        self.assertNotIn("idp", {item["player_id"] for item in [recommendation["calculated_pick"], *recommendation["backup_picks"]]})
        with self.assertRaisesRegex(ValueError, "unsupported position"):
            validate_value_snapshot({"schema_version": 1, "players": players, "omitted": []})

    def test_kicker_and_defense_are_targeted_in_rounds_13_to_15(self) -> None:
        players = {
            f"off-{index}": {
                "name": f"Offense {index}", "position": "WR", "value": 50 - index,
                "status": "Active", "team": f"O{index}", "adp": 200 + index,
            }
            for index in range(5)
        }
        for player_id, position in (("k", "K"), ("def", "DEF")):
            players[player_id] = {
                "name": player_id.upper(), "position": position, "value": 90,
                "status": "Active", "team": player_id, "adp": 145,
            }
        state = {
            "league_rules": {
                "roster_positions": list(OFFICIAL_ROSTER), "rounds": 15,
            },
            "participant": {"roster_id": 8}, "selected_player_ids": [], "picks": [],
            "participant_next_turn": {"pick_no": 145, "round": 12},
            "rosters": {"8": {"player_ids": []}}, "updated_at": 1,
        }
        early = dict(state, current_turn={"pick_no": 133, "round": 12})
        early["participant_next_turn"] = {"pick_no": 133, "round": 12}
        early["turns"] = [{"pick_no": 133, "owner_roster_id": 8}]
        early_result = calculate(early, {"players": players, "updated_at": 1})
        self.assertNotIn("K", {item["position"] for item in [early_result["calculated_pick"], *early_result["backup_picks"]]})
        self.assertNotIn("DEF", {item["position"] for item in [early_result["calculated_pick"], *early_result["backup_picks"]]})

        late = dict(state, current_turn={"pick_no": 145, "round": 13})
        late["participant_next_turn"] = {"pick_no": 145, "round": 13}
        late["turns"] = [{"pick_no": 145, "owner_roster_id": 8}]
        late_result = calculate(late, {"players": players, "updated_at": 1})
        late_positions = {item["position"] for item in [late_result["calculated_pick"], *late_result["backup_picks"]]}
        self.assertIn("K", late_positions)
        self.assertIn("DEF", late_positions)

    def test_kicker_and_defense_are_legal_bench_contents(self) -> None:
        positions = ["QB", "RB", "RB", "WR", "WR", "TE", "RB", "WR", "K", "DEF", "K", "DEF", "DEF", "DEF", "DEF"]
        players = {f"p{index}": {"position": position} for index, position in enumerate(positions)}
        state = {
            "rosters": {"8": {"player_ids": list(players)}},
        }
        self.assertEqual(
            _check_roster(state, {"players": players}, 8, final=True),
            dict(sorted(Counter(positions).items())),
        )


if __name__ == "__main__":
    unittest.main()
