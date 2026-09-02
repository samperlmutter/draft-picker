from __future__ import annotations

from unittest.mock import patch

from src.draft_advisor.values import build_value_snapshot, validate_value_snapshot


class FakeSleeperClient:
    def __init__(self, players: dict[str, dict[str, object]]) -> None:
        self._players = players

    def players(self) -> dict[str, dict[str, object]]:
        return self._players


def _player(name: str, team: str, position: str) -> dict[str, object]:
    return {
        "full_name": name,
        "team": team,
        "position": position,
        "status": "Active",
    }


def test_adp_fallback_keeps_kicker_and_defense_on_the_value_board() -> None:
    players = {
        "qb": _player("Quarter Back", "AAA", "QB"),
        "rb": _player("Running Back", "BBB", "RB"),
        "wr": _player("Wide Receiver", "CCC", "WR"),
        "te": _player("Tight End", "DDD", "TE"),
        "rb2": _player("Running Back Two", "EEE", "RB"),
        "k": _player("Reliable Kicker", "FFF", "K"),
        "def": _player("Strong Defense", "GGG", "DEF"),
    }
    fantasycalc = [
        {"player": {"sleeperId": player_id, "name": player["full_name"], "maybeTeam": player["team"], "position": player["position"]}, "value": 100 - index * 5}
        for index, player_id in enumerate(("qb", "rb", "wr", "te", "rb2"))
        for player in (players[player_id],)
    ]
    adp = {
        "players": [
            {"name": players[player_id]["full_name"], "team": players[player_id]["team"], "position": players[player_id]["position"], "adp": adp_value}
            for player_id, adp_value in (
                ("qb", 1), ("rb", 2), ("wr", 3), ("te", 4), ("rb2", 5),
                ("def", 150), ("k", 160),
            )
        ]
    }

    with patch(
        "src.draft_advisor.values._fixture_or_url",
        side_effect=[fantasycalc, adp],
    ):
        snapshot = build_value_snapshot(FakeSleeperClient(players), clock=lambda: 1.0)

    validate_value_snapshot(snapshot)
    assert snapshot["players"]["k"]["value_source"] == "ffc_adp_fallback"
    assert snapshot["players"]["def"]["value_source"] == "ffc_adp_fallback"
    assert snapshot["players"]["k"]["value"] == 6.0
    assert snapshot["players"]["def"]["value"] == 6.0
