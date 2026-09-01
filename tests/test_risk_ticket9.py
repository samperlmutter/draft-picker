import json

import pytest

from src.draft_advisor.service import read_risk, refresh_risk, validate_risk_fixture
from src.draft_advisor.storage import Storage


def _fixture(tmp_path, status="OUT", observed_at=100):
    (tmp_path / "risk-observations.json").write_text(json.dumps({
        "observations": [{"player_id": "p1", "status": status, "observed_at": observed_at}],
    }))


def test_refresh_requires_validation_for_the_same_player_universe(monkeypatch, tmp_path):
    _fixture(tmp_path)
    monkeypatch.setenv("DRAFT_ADVISOR_FIXTURES", str(tmp_path))
    storage = Storage(tmp_path / "runtime")
    players = {"p1": {"full_name": "Alex Example"}}
    validate_risk_fixture(storage, players, clock=lambda: 100)

    _fixture(tmp_path, status="active", observed_at=101)
    refreshed = refresh_risk(storage, players, clock=lambda: 102)
    assert refreshed["players"]["p1"]["state"] == "available"


def test_refresh_rejects_empty_source_without_replacing_previous_snapshot(monkeypatch, tmp_path):
    _fixture(tmp_path)
    monkeypatch.setenv("DRAFT_ADVISOR_FIXTURES", str(tmp_path))
    storage = Storage(tmp_path / "runtime")
    players = {"p1": {"full_name": "Alex Example"}}
    validate_risk_fixture(storage, players, clock=lambda: 100)
    first = refresh_risk(storage, players, clock=lambda: 101)
    previous = storage.risk_path.read_bytes()

    (tmp_path / "risk-observations.json").write_text(json.dumps({"observations": []}))
    with pytest.raises(ValueError, match="unavailable or incomplete"):
        refresh_risk(storage, players, clock=lambda: 102)
    assert storage.risk_path.read_bytes() == previous
    assert read_risk(storage, clock=lambda: 102) == first


def test_read_risk_rejects_stale_snapshot(monkeypatch, tmp_path):
    _fixture(tmp_path)
    monkeypatch.setenv("DRAFT_ADVISOR_FIXTURES", str(tmp_path))
    storage = Storage(tmp_path / "runtime")
    players = {"p1": {"full_name": "Alex Example"}}
    validate_risk_fixture(storage, players, clock=lambda: 100)
    refresh_risk(storage, players, clock=lambda: 101)

    assert read_risk(storage, clock=lambda: 1902) is None
