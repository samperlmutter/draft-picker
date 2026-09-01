from __future__ import annotations

from src.draft_advisor.risk import read_risk_source, validate_risk


class FakeSleeper:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def players(self):
        self.calls += 1
        return self.payload


def test_live_sleeper_payload_is_normalized_without_network(monkeypatch):
    monkeypatch.delenv("DRAFT_ADVISOR_FIXTURES", raising=False)
    client = FakeSleeper({
        "100": {"full_name": "Out Player", "status": "Active", "injury_status": "Out"},
        "200": {"full_name": "Healthy Player", "status": "Active"},
        "300": {"full_name": "No Designation"},
    })

    observations, source = read_risk_source(client)

    assert client.calls == 1
    assert source["kind"] == "sleeper"
    assert {row["player_id"] for row in observations} == {"100", "200"}
    assert observations[0]["source"] == "sleeper"
    assert observations[0]["evidence_kind"] == "status"
    assert observations[0]["evidence_url"].endswith("/players/nfl")
    assert all(row["observed_at"] > 0 for row in observations)


def test_fixture_mode_does_not_call_sleeper(monkeypatch, tmp_path):
    fixture = tmp_path / "risk-observations.json"
    fixture.write_text('{"observations": [{"player_id": "p1", "status": "OUT", "observed_at": 100}]}')
    monkeypatch.setenv("DRAFT_ADVISOR_FIXTURES", str(tmp_path))
    client = FakeSleeper({"100": {"status": "Active"}})

    observations, source = read_risk_source(client)

    assert client.calls == 0
    assert source["kind"] == "fixture"
    assert observations[0]["player_id"] == "p1"


def test_malformed_live_player_response_is_rejected(monkeypatch):
    monkeypatch.delenv("DRAFT_ADVISOR_FIXTURES", raising=False)
    client = FakeSleeper({"100": None})

    try:
        read_risk_source(client)
    except ValueError as exc:
        assert "malformed player" in str(exc)
    else:
        raise AssertionError("malformed Sleeper player data must be rejected")


def test_current_sleeper_status_vocabulary_passes_validation(monkeypatch):
    monkeypatch.delenv("DRAFT_ADVISOR_FIXTURES", raising=False)
    statuses = {
        "ir": {"status": "Active", "injury_status": "IR"},
        "pup": {"status": "Active", "injury_status": "PUP"},
        "na": {"status": "Active", "injury_status": "NA"},
        "sus": {"status": "Active", "injury_status": "Sus"},
        "dnr": {"status": "Active", "injury_status": "DNR"},
        "cov": {"status": "Active", "injury_status": "COV"},
        "nfi": {"status": "Active", "injury_status": "Non Football Injury"},
        "practice": {"status": "Practice Squad"},
    }
    observations, _ = read_risk_source(FakeSleeper(statuses))

    snapshot, report = validate_risk({pid: {} for pid in statuses}, observations, clock=lambda: 1)

    assert report["status"] == "pass"
    assert snapshot["players"]["ir"]["state"] == "unavailable"
    assert snapshot["players"]["pup"]["state"] == "unavailable"
    assert snapshot["players"]["na"]["state"] == "available"
    assert snapshot["players"]["sus"]["state"] == "suspended"
    assert snapshot["players"]["dnr"]["state"] == "under_review"
    assert snapshot["players"]["cov"]["state"] == "under_review"
    assert snapshot["players"]["nfi"]["state"] == "under_review"
    assert snapshot["players"]["practice"]["state"] == "unavailable"
