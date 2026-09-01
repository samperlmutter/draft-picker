import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from src.draft_advisor.cli import main


class RiskTicket10CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime = Path(self.tempdir.name)
        self.environment = patch.dict(os.environ, {"DRAFT_ADVISOR_RUNTIME_DIR": str(self.runtime)})
        self.environment.start()
        self.snapshot = {
            "schema_version": 1,
            "phase": "validation",
            "authoritative": False,
            "generated_at": 100,
            "players": {"p1": {"player_id": "p1", "state": "unknown", "observations": []}},
            "data_quality": {"status": "review", "review": [{"player_id": "p1", "reason": "conflicting_evidence"}]},
        }
        self.report = {"status": "review", "review_count": 1, "review": [{"player_id": "p1", "reason": "conflicting_evidence"}]}
        self._write(self.runtime / "risk-validation.json", self.snapshot)
        self._write(self.runtime / "risk-validation-report.json", self.report)

    def tearDown(self) -> None:
        self.environment.stop()
        self.tempdir.cleanup()

    @staticmethod
    def _write(path: Path, value: object) -> None:
        path.write_text(json.dumps(value))

    def test_review_prints_diagnostics_and_returns_failure_while_pending(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = main(["risk", "review"])
        self.assertEqual(result, 1)
        self.assertIn("p1: conflicting_evidence", output.getvalue())

    def test_override_is_source_linked_and_keeps_snapshot_non_authoritative(self) -> None:
        override = self.runtime / "override.json"
        self._write(override, {"override_id": "o1", "player_id": "p1", "state": "limited", "source": "commissioner", "reason": "verified", "expires_at": 4102444800})
        output = StringIO()
        with redirect_stdout(output):
            result = main(["risk", "override", "--input", str(override), "--json"])
        self.assertEqual(result, 0)
        saved = json.loads((self.runtime / "risk-validation.json").read_text())
        self.assertFalse(saved["authoritative"])
        self.assertEqual(saved["players"]["p1"]["state"], "limited")
        self.assertIn("run risk refresh", output.getvalue())


if __name__ == "__main__":
    unittest.main()
