from src.draft_advisor.risk import validate_risk


def test_invalid_rows_and_statuses_are_reported_without_aborting_ingestion():
    snapshot, report = validate_risk(
        {"p1": {"full_name": "Alex Example"}},
        [
            None,
            {"player_id": "p1", "status": "questionable-but-playing", "observed_at": 100},
            {"player_id": "p1", "status": "active", "observed_at": "not-a-date"},
        ],
        clock=lambda: 101,
    )

    assert snapshot["players"]["p1"]["state"] == "unknown"
    assert report["malformed_count"] == 2
    assert report["unknown_status_count"] == 1
    assert {item["reason"] for item in report["review"]} >= {
        "malformed_observation", "unknown_status", "invalid_timestamp"
    }


def test_conflicting_aliases_are_not_silently_assigned():
    snapshot, report = validate_risk(
        {
            "p1": {"full_name": "Alex Example", "gsis_id": "g1"},
            "p2": {"full_name": "Jordan Example", "gsis_id": "g2"},
        },
        [{"gsis_id": "g1", "player_id": "p2", "status": "out", "observed_at": 100}],
        clock=lambda: 101,
    )

    assert all(not player["observations"] for player in snapshot["players"].values())
    assert report["ambiguous_count"] == 1
    assert report["review"][0]["reason"] == "conflicting_identity"


def test_newer_correction_wins_even_when_it_is_not_a_penalty():
    snapshot, _ = validate_risk(
        {"p1": {"full_name": "Alex Example"}},
        [
            {"player_id": "p1", "status": "out", "observed_at": 100},
            {"player_id": "p1", "status": "active", "observed_at": 200, "effective_at": 200},
        ],
        clock=lambda: 201,
    )

    assert snapshot["players"]["p1"]["state"] == "available"


def test_fresh_evidence_prevents_an_older_observation_from_making_player_stale():
    snapshot, _ = validate_risk(
        {"p1": {"full_name": "Alex Example"}},
        [
            {"player_id": "p1", "status": "out", "observed_at": 1},
            {"player_id": "p1", "status": "active", "observed_at": 100_000_000},
        ],
        clock=lambda: 100_000_001,
    )

    assert snapshot["players"]["p1"]["state"] == "available"


def test_week_scoped_availability_retains_latest_state_per_week():
    snapshot, _ = validate_risk(
        {"p1": {"full_name": "Alex Example"}},
        [
            {"player_id": "p1", "status": "out", "week": 1, "observed_at": 100},
            {"player_id": "p1", "status": "active", "week": 1, "observed_at": 200},
            {"player_id": "p1", "status": "limited", "week": 2, "observed_at": 200},
        ],
        clock=lambda: 201,
    )

    assert snapshot["players"]["p1"]["weekly_availability"] == {
        "1": "available",
        "2": "limited",
    }
