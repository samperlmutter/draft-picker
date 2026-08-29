import json

import pytest

from src.draft_advisor.risk import (
    apply_risk_overrides,
    build_risk_snapshot,
    risk_injury_status,
    validate_authoritative_risk_snapshot,
    validate_risk,
)
from src.draft_advisor.service import refresh_risk, validate_risk_fixture
from src.draft_advisor.storage import Storage


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
    assert snapshot["players"]["p1"]["provenance"] == ["team", "wire"]
    assert report["ambiguous_count"] == 1
    assert report["review_count"] == 1


def test_risk_validation_keeps_unknown_players_without_penalty():
    snapshot, report = validate_risk({"p1": {"full_name": "No Report"}}, [], clock=lambda: 1.0)
    assert snapshot["players"]["p1"]["state"] == "unknown"
    assert report["matched_count"] == 0


def test_risk_refresh_builds_authoritative_snapshot_from_fixture(monkeypatch, tmp_path):
    fixture = tmp_path / "risk-observations.json"
    fixture.write_text(json.dumps({"observations": [{"player_id": "p1", "status": "OUT", "observed_at": "2026-08-29T10:00:00Z"}]}))
    monkeypatch.setenv("DRAFT_ADVISOR_FIXTURES", str(tmp_path))
    snapshot = build_risk_snapshot({"p1": {"full_name": "A"}}, clock=lambda: 42.0)
    assert validate_authoritative_risk_snapshot(snapshot)["phase"] == "authoritative"
    assert snapshot["players"]["p1"]["state"] == "unavailable"
    assert snapshot["parser"]["name"] == "draft-advisor-risk"


def test_risk_queue_preserves_syndicated_provenance_and_flags_weak_conflict():
    snapshot, report = validate_risk({"p1": {"full_name": "Alex Example"}}, [
        {"player_id": "p1", "status": "active", "source": "team", "observed_at": 100, "url": "https://x"},
        {"player_id": "p1", "status": "active", "source": "wire", "observed_at": 100, "url": "https://x", "kind": "rumor"},
        {"player_id": "p1", "status": "out", "source": "reporter", "observed_at": 100},
    ], clock=lambda: 101)
    evidence = next(
        observation
        for observation in snapshot["players"]["p1"]["observations"]
        if set(observation["sources"]) == {"team", "wire"}
    )
    assert evidence["sources"] == ["team", "wire"]
    assert any(item["reason"] == "conflicting_evidence" for item in report["review"])
    assert any(item["reason"] == "weak_or_disciplinary_evidence" for item in report["review"])


def test_overrides_are_dated_auditable_and_weak_discipline_is_rejected():
    snapshot, _ = validate_risk({"p1": {"full_name": "Alex Example"}}, [], clock=lambda: 100)
    applied = apply_risk_overrides(snapshot, [{"override_id": "o1", "player_id": "p1", "state": "limited", "source": "commissioner", "reason": "verified", "expires_at": 200}], now=101)
    assert applied["players"]["p1"]["state"] == "limited"
    assert applied["overrides"][0]["override_id"] == "o1"
    with pytest.raises(ValueError):
        apply_risk_overrides(snapshot, [{"override_id": "o2", "player_id": "p1", "state": "suspended", "source": "blog", "reason": "rumor", "evidence_kind": "rumor", "expires_at": 200}], now=101)


def test_name_only_evidence_is_reviewed_without_assignment():
    snapshot, report = validate_risk(
        {"p1": {"full_name": "Alex Example"}},
        [{"name": "Alex Example", "status": "OUT", "source": "news", "observed_at": 100}],
        clock=lambda: 101,
    )
    assert snapshot["players"]["p1"]["state"] == "unknown"
    assert report["unmatched_count"] == 1
    assert any(item["reason"] == "name_only" for item in report["review"])


def test_iso_timestamp_staleness_and_weak_evidence_are_neutral():
    stale, _ = validate_risk(
        {"p1": {"full_name": "Alex Example"}},
        [{"player_id": "p1", "status": "OUT", "observed_at": "2020-01-01T00:00:00Z"}],
        clock=lambda: 2_000_000_000,
    )
    weak, _ = validate_risk(
        {"p1": {"full_name": "Alex Example"}},
        [{"player_id": "p1", "status": "OUT", "kind": "rumor", "observed_at": 100}],
        clock=lambda: 101,
    )
    assert stale["players"]["p1"]["state"] == "stale"
    assert weak["players"]["p1"]["state"] == "unknown"
    assert risk_injury_status("stale") is None
    assert risk_injury_status("under_review") is None
    assert risk_injury_status("suspended") == "OUT"


def test_refresh_rereads_changed_source_and_preserves_last_valid_snapshot(monkeypatch, tmp_path):
    fixture = tmp_path / "risk-observations.json"
    fixture.write_text(json.dumps({"observations": [{"player_id": "p1", "status": "OUT", "observed_at": 100}]}))
    monkeypatch.setenv("DRAFT_ADVISOR_FIXTURES", str(tmp_path))
    storage = Storage(tmp_path / "runtime")
    players = {"p1": {"full_name": "Alex Example"}}
    _, report = validate_risk_fixture(storage, players, clock=lambda: 101)
    assert report["status"] == "pass"
    first = refresh_risk(storage, players, clock=lambda: 102)
    assert first["players"]["p1"]["state"] == "unavailable"

    fixture.write_text(json.dumps({"observations": [{"player_id": "p1", "status": "active", "observed_at": 103}]}))
    second = refresh_risk(storage, players, clock=lambda: 104)
    assert second["players"]["p1"]["state"] == "available"
    previous = storage.risk_path.read_bytes()

    fixture.write_text("not-json")
    with pytest.raises(ValueError):
        refresh_risk(storage, players, clock=lambda: 105)
    assert storage.risk_path.read_bytes() == previous
