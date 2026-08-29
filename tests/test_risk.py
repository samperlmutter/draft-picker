import json
from pathlib import Path

from src.draft_advisor.risk import validate_risk


def test_risk_validation_prefers_ids_normalizes_and_deduplicates_with_provenance():
    players = {"p1": {"full_name": "Alex Example", "gsis_id": "g1"}, "p2": {"full_name": "Alex Example"}}
    snapshot, report = validate_risk(players, [
        {"player_id": "p1", "status": "OUT", "source": "team", "observed_at": "2026-08-29T10:00:00Z", "url": "https://team/a"},
        {"player_id": "p1", "status": "OUT", "source": "wire", "observed_at": "2026-08-29T10:00:00Z", "url": "https://team/a"},
        {"name": "Alex Example", "status": "active", "source": "news", "observed_at": "2026-08-29T10:00:00Z"},
    ], clock=lambda: 42.0)
    assert snapshot["authoritative"] is False
    assert snapshot["players"]["p1"]["state"] == "unavailable"
    assert len(snapshot["players"]["p1"]["observations"]) == 1
    assert snapshot["players"]["p1"]["provenance"] == ["team"]
    assert report["ambiguous_count"] == 1
    assert report["review_count"] == 1


def test_risk_validation_keeps_unknown_players_without_penalty():
    snapshot, report = validate_risk({"p1": {"full_name": "No Report"}}, [], clock=lambda: 1.0)
    assert snapshot["players"]["p1"]["state"] == "unknown"
    assert report["matched_count"] == 0
