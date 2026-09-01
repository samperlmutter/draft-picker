from __future__ import annotations

from collections import Counter
from typing import Any

LEGAL_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DEF"})
FLEX_POSITIONS = frozenset({"RB", "WR", "TE"})
BENCH_POSITIONS = frozenset({"BN", "BENCH"})
OFFICIAL_ROSTER = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF", "BN", "BN", "BN", "BN", "BN")
OFFICIAL_TEAMS = 12
OFFICIAL_ROUNDS = 15
SUPPORTED_ROSTER_SLOTS = frozenset({
    "QB", "RB", "WR", "TE", "FLEX", "K", "DEF", "DST",
    "BN", "BENCH", "IR", "TAXI",
})

def canonical_position(value: Any) -> str:
    position = str(value or "").upper()
    return "DEF" if position == "DST" else position

def is_legal_position(value: Any) -> bool:
    return canonical_position(value) in LEGAL_POSITIONS

def validate_roster_config(
    roster_positions: Any,
    teams: Any = None,
    rounds: Any = None,
    *,
    official: bool = False,
) -> None:
    actual = tuple(canonical_position(slot) for slot in (roster_positions or []))
    unsupported = [slot for slot in actual if slot not in SUPPORTED_ROSTER_SLOTS]
    if unsupported:
        raise ValueError(
            "league roster contains unsupported/IDP position slots: "
            + ", ".join(sorted(set(unsupported)))
        )
    if official:
        expected = tuple(OFFICIAL_ROSTER)
        if int(teams or 0) != OFFICIAL_TEAMS or int(rounds or 0) != OFFICIAL_ROUNDS:
            raise ValueError("league must use the official 12-team, 15-round initial draft")
        if actual != expected:
            raise ValueError(f"league roster does not match official roster: expected {list(expected)}, got {list(actual)}")

def position_requirements(roster_positions: Any) -> Counter[str]:
    result: Counter[str] = Counter()
    for slot in roster_positions or []:
        position = canonical_position(slot)
        if position not in BENCH_POSITIONS:
            result["FLEX" if "FLEX" in position else position] += 1
    return result
