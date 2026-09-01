from __future__ import annotations

from src.draft_advisor.event_risk import evaluate_schedule_event_risk
from src.draft_advisor.recommend import calculate


def _risk_snapshot() -> dict:
    return {
        "players": {
            "p1": {
                "state": "available",
                "observations": [],
            },
        },
    }


def _schedule() -> dict:
    return {
        "data_quality": {"status": "complete"},
        "source": {"name": "test-schedule"},
        "league_rules": {"playoff_week_start": 16},
        "player_schedule_summaries": {
            "p1": {
                "regular_season": {"average_matchup_delta": -2.5, "weeks": [1, 2]},
                "playoffs": {"average_matchup_delta": -1.0, "weeks": [16, 17]},
            },
        },
    }


def test_evaluation_caps_schedule_and_event_adjustments_and_keeps_evidence():
    evaluation = evaluate_schedule_event_risk(
        {"p1": {"value": 100, "position": "RB"}},
        _schedule(),
        _risk_snapshot(),
        [{
            "player_id": "p1",
            "event_type": "role_change",
            "impact_tier": "severe",
            "summary": "Starting role is in doubt",
            "observed_at": 100,
            "source": "official_team",
            "evidence_url": "https://example.test/event",
        }],
        phase="baseline",
        clock=lambda: 101,
    )

    player = evaluation["players"]["p1"]
    assert player["schedule_tier"] == "severe"
    assert player["event_tier"] == "severe"
    assert player["impact_tier"] == "severe"
    assert player["combined_adjustment_pct"] == -0.1
    assert player["events"][0]["source"] == "official_team"


def test_day_of_evaluation_uses_latest_authoritative_event_and_reports_material_diff():
    baseline = evaluate_schedule_event_risk(
        {"p1": {"value": 100, "position": "RB"}},
        None,
        _risk_snapshot(),
        [{
            "player_id": "p1",
            "event_type": "role_change",
            "impact_tier": "material",
            "summary": "Role is stable",
            "observed_at": 100,
            "source": "official_team",
            "evidence_url": "https://example.test/stable",
        }],
        phase="baseline",
        clock=lambda: 101,
    )
    day_of = evaluate_schedule_event_risk(
        {"p1": {"value": 100, "position": "RB"}},
        None,
        _risk_snapshot(),
        [
            {
                "player_id": "p1",
                "event_type": "role_change",
                "impact_tier": "material",
                "summary": "Role is stable",
                "observed_at": 100,
                "source": "official_team",
                "evidence_url": "https://example.test/stable",
            },
            {
                "player_id": "p1",
                "event_type": "role_change",
                "impact_tier": "severe",
                "summary": "Role is lost",
                "observed_at": 102,
                "source": "official_team",
                "evidence_url": "https://example.test/lost",
            },
        ],
        phase="day-of",
        clock=lambda: 103,
        baseline=baseline,
    )

    assert day_of["players"]["p1"]["event_tier"] == "severe"
    assert len(day_of["players"]["p1"]["events"]) == 1
    assert day_of["changes"][0]["old_tier"] == "material"
    assert day_of["changes"][0]["new_tier"] == "severe"


def test_expired_and_untrusted_events_have_no_score_effect():
    evaluation = evaluate_schedule_event_risk(
        {"p1": {"value": 100, "position": "RB"}},
        None,
        _risk_snapshot(),
        [
            {
                "player_id": "p1",
                "event_type": "availability",
                "impact_tier": "severe",
                "summary": "Expired event",
                "observed_at": 100,
                "expires_at": 100,
                "source": "official_team",
                "evidence_url": "https://example.test/expired",
            },
            {
                "player_id": "p1",
                "event_type": "availability",
                "impact_tier": "severe",
                "summary": "Untrusted event",
                "observed_at": 100,
                "source": "rumor",
                "evidence_url": "https://example.test/rumor",
            },
        ],
        phase="baseline",
        clock=lambda: 101,
    )

    player = evaluation["players"]["p1"]
    assert player["event_tier"] == "none"
    assert player["event_adjustment_pct"] == 0.0
    assert player["events"] == []


def test_evaluation_is_consumed_by_the_normal_recommendation_path():
    players = {
        player_id: {
            "name": player_id,
            "position": "QB",
            "team": player_id,
            "status": "Active",
            "value": 100 - index,
            "adp": 1,
            "stability": 0.5,
            "upside": 0.5,
        }
        for index, player_id in enumerate(("p1", "p2", "p3", "p4", "p5"))
    }
    evaluation = evaluate_schedule_event_risk(
        players,
        None,
        _risk_snapshot(),
        [{
            "player_id": "p1",
            "event_type": "role_change",
            "impact_tier": "severe",
            "summary": "Role is lost",
            "observed_at": 100,
            "source": "official_team",
            "evidence_url": "https://example.test/lost",
        }],
        phase="baseline",
        clock=lambda: 101,
    )
    for player_id, player in players.items():
        player["event_evaluation"] = evaluation["players"][player_id]
    state = {
        "league_rules": {"roster_positions": ["QB", "BN"], "rounds": 15},
        "participant": {"roster_id": 8},
        "selected_player_ids": [],
        "picks": [],
        "current_turn": {"pick_no": 1, "round": 1},
        "participant_next_turn": {"pick_no": 1, "round": 1},
        "turns": [],
        "rosters": {"8": {"player_ids": []}},
        "updated_at": 1,
    }

    recommendation = calculate(state, {"players": players, "updated_at": 1}, clock=lambda: 101)

    p1 = next(candidate for candidate in [recommendation["calculated_pick"], *recommendation["backup_picks"]] if candidate["player_id"] == "p1")
    assert p1["event_risk_tier"] == "severe"
    assert p1["components"]["combined_risk_adjustment_pct"] == -0.08
