import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.draft_advisor.risk import apply_risk_overrides
from src.draft_advisor.service import refresh_risk, validate_risk_fixture
from src.draft_advisor.storage import Storage


class RiskIntegrationTests(unittest.TestCase):
    def test_review_override_is_published_by_authoritative_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "risk-observations.json").write_text(json.dumps({
                "observations": [{
                    "player_id": "p1",
                    "status": "OUT",
                    "kind": "rumor",
                    "observed_at": 100,
                }],
            }))
            storage = Storage(root / "runtime")
            players = {"p1": {"full_name": "Alex Example"}}
            with patch.dict(os.environ, {"DRAFT_ADVISOR_FIXTURES": str(root)}):
                validation, report = validate_risk_fixture(storage, players, clock=lambda: 101)
                self.assertEqual(report["status"], "review")
                resolved = apply_risk_overrides(
                    validation,
                    [{
                        "override_id": "o1",
                        "player_id": "p1",
                        "state": "available",
                        "source": "commissioner",
                        "reason": "verified rumor is false",
                        "expires_at": 200,
                    }],
                    now=101,
                )
                storage.write_json(storage.risk_validation_path, resolved)
                authoritative = refresh_risk(storage, players, clock=lambda: 102)

            self.assertTrue(authoritative["authoritative"])
            self.assertEqual(authoritative["players"]["p1"]["state"], "available")
            self.assertEqual(authoritative["overrides"][0]["override_id"], "o1")


if __name__ == "__main__":
    unittest.main()
