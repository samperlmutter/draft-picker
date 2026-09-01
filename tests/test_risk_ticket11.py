import unittest
from unittest.mock import patch

from src.draft_advisor.replay import replay
from src.draft_advisor.risk import build_risk_snapshot
from tests.test_replay import build_bundle


class RiskReplayTicket11Tests(unittest.TestCase):
    def _risk_snapshot(self, bundle):
        source = (
            [{"player_id": "p1", "status": "active", "observed_at": 1}],
            {"kind": "fixture", "parser": "draft-advisor-risk", "parser_version": "1"},
        )
        with patch("src.draft_advisor.risk.read_risk_source", return_value=source):
            return build_risk_snapshot(bundle["value_snapshots"][0]["players"], clock=lambda: 17.0)

    def test_authoritative_snapshot_metadata_survives_replay_summary(self):
        bundle = build_bundle()
        risk = self._risk_snapshot(bundle)
        risk["players"]["elite-a"].update({
            "state": "stale",
            "observations": [{"observation_id": "obs-1", "source": "fixture", "raw_status": "questionable"}],
            "provenance": ["fixture"],
        })
        bundle["risk_snapshot"] = risk

        result = replay(bundle)

        self.assertTrue(result["passed"], result["first_failure"])
        elite = [
            candidate for item in result["recommendations"]
            for candidate in [item["calculated_pick"], *item["backup_picks"]]
            if candidate["player_id"] == "elite-a"
        ]
        self.assertTrue(elite)
        self.assertTrue(all(candidate["risk_state"] == "stale" for candidate in elite))
        self.assertTrue(all(candidate["risk_visible"] for candidate in elite))
        self.assertTrue(all(candidate["risk_evidence"] == risk["players"]["elite-a"]["observations"] for candidate in elite))
        self.assertTrue(all(candidate["risk_provenance"] == ["fixture"] for candidate in elite))
        self.assertTrue(all(candidate["injury_warning"] is None for candidate in elite))

    def test_missing_freshness_does_not_fail_before_recommendation(self):
        bundle = build_bundle()
        risk = self._risk_snapshot(bundle)
        risk.pop("freshness", None)
        bundle["risk_snapshot"] = risk

        result = replay(bundle)

        self.assertTrue(result["passed"], result["first_failure"])

    def test_replay_never_reads_risk_sources(self):
        bundle = build_bundle()
        bundle["risk_snapshot"] = self._risk_snapshot(bundle)
        with patch("src.draft_advisor.risk.read_risk_source", side_effect=AssertionError("replay must not read sources")):
            result = replay(bundle)
        self.assertTrue(result["passed"], result["first_failure"])


if __name__ == "__main__":
    unittest.main()
