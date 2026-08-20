from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_cli import cli, setup_fixture, write_json


class TradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.tmp_path = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def setup_trade(self, p1_value: float = 100, p2_value: float = 95):
        env, fixtures = setup_fixture(self.tmp_path, live=True)
        picks_path = fixtures / "draft__draft-1__picks.json"
        picks = json.loads(picks_path.read_text())
        picks.append({"pick_no": 2, "round": 1, "draft_slot": 2, "roster_id": 9, "player_id": "p2", "picked_by": "u9", "metadata": {}})
        write_json(picks_path, picks)
        fc_path = fixtures / "fantasycalc.json"
        rows = json.loads(fc_path.read_text())
        for row in rows:
            player_id = row["player"]["sleeperId"]
            if player_id == "p1":
                row["value"] = p1_value
            elif player_id == "p2":
                row["value"] = p2_value
        write_json(fc_path, rows)
        initialized = cli(env, "status", "--refresh")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        return env

    def evaluate(self, env, offer, json_output=True):
        path = self.tmp_path / "offer.json"
        write_json(path, offer)
        args = ["trade", "--offer-file", str(path)]
        if json_output:
            args.append("--json")
        return cli(env, *args)

    def test_accepts_player_trade_for_better_value_and_roster_fit(self) -> None:
        env = self.setup_trade(50, 100)
        result = self.evaluate(env, {"confirmed": True, "give": [{"type": "player", "player_id": "p1"}], "receive": [{"type": "player", "player_id": "p2"}]})
        self.assertEqual(result.returncode, 0, result.stderr)
        evaluation = json.loads(result.stdout)
        self.assertEqual(evaluation["decision"], "accept")
        self.assertIsNone(evaluation["counteroffer"])
        self.assertTrue(evaluation["evaluation"]["includes_roster_fit"])
        self.assertTrue(evaluation["evaluation"]["includes_remaining_picks"])

    def test_rejects_bad_trade_and_proposes_current_draft_counteroffer(self) -> None:
        env = self.setup_trade(100, 50)
        offer = {"confirmed": True, "give": [{"type": "player", "player_id": "p1"}], "receive": [{"type": "player", "player_id": "p2"}]}
        result = self.evaluate(env, offer)
        self.assertEqual(result.returncode, 0, result.stderr)
        evaluation = json.loads(result.stdout)
        self.assertEqual(evaluation["decision"], "reject")
        self.assertIsNotNone(evaluation["counteroffer"])
        self.assertEqual(evaluation["counteroffer"]["receive"][-1], {"type": "pick", "pick_no": 6})
        text = self.evaluate(env, offer, json_output=False)
        self.assertIn("Trade: REJECT", text.stdout)
        self.assertIn("Counteroffer:", text.stdout)

    def test_close_player_trade_and_current_draft_pick_support(self) -> None:
        env = self.setup_trade(100, 95)
        players = self.evaluate(env, {"confirmed": True, "give": [{"type": "player", "player_id": "p1"}], "receive": [{"type": "player", "player_id": "p2"}]})
        self.assertEqual(json.loads(players.stdout)["decision"], "close")
        picks = self.evaluate(env, {"confirmed": True, "give": [{"type": "pick", "pick_no": 3}], "receive": [{"type": "pick", "pick_no": 6}]})
        self.assertEqual(picks.returncode, 0, picks.stderr)
        self.assertEqual(json.loads(picks.stdout)["give"][0]["pick_no"], 3)

    def test_requires_confirmation_and_rejects_future_or_invalid_assets(self) -> None:
        env = self.setup_trade()
        unconfirmed = self.evaluate(env, {"confirmed": False, "give": [{"type": "player", "player_id": "p1"}], "receive": [{"type": "player", "player_id": "p2"}]})
        self.assertNotEqual(unconfirmed.returncode, 0)
        self.assertIn("confirmed", unconfirmed.stderr)
        future = self.evaluate(env, {"confirmed": True, "give": [{"type": "player", "player_id": "p1"}], "receive": [{"type": "pick", "pick_no": 6, "season": 2027}]})
        self.assertNotEqual(future.returncode, 0)
        self.assertIn("future-season", future.stderr)
        undrafted = self.evaluate(env, {"confirmed": True, "give": [{"type": "player", "player_id": "p1"}], "receive": [{"type": "player", "player_id": "p8"}]})
        self.assertNotEqual(undrafted.returncode, 0)
        self.assertIn("not drafted", undrafted.stderr)
        malformed = self.evaluate(env, ["not", "an", "offer"])
        self.assertNotEqual(malformed.returncode, 0)
        self.assertIn("JSON object", malformed.stderr)

    def test_skill_is_discoverable_thin_and_contains_acceptance_guardrails(self) -> None:
        path = Path(__file__).parents[1] / ".agents" / "skills" / "draft-advisor" / "SKILL.md"
        content = path.read_text()
        self.assertIn("name: draft-advisor", content)
        for phrase in ("get ready", "who should I pick", "evaluate this trade", "$draft-advisor"):
            self.assertIn(phrase, content)
        self.assertLess(len(content.splitlines()), 80)
        self.assertLess(content.index("Calculated Pick followed by all four"), content.index("Final Recommendation:"))
        self.assertIn("model_judgment_eligible", content)
        self.assertIn("Do not run Trade Evaluation before an explicit confirmation", content)
        self.assertIn("never add confidence labels", content)
        metadata = (path.parent / "agents" / "openai.yaml").read_text()
        self.assertIn('display_name: "Draft Advisor"', metadata)
        self.assertIn('default_prompt: "Use $draft-advisor', metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)


if __name__ == "__main__":
    unittest.main()
