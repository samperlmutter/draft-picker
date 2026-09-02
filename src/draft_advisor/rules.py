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


def lineup_validation(
    roster_positions: Any,
    player_positions: Any,
    *,
    require_full_roster: bool = False,
) -> dict[str, Any]:
    """Describe whether a roster can fill its weekly starting lineup.

    FLEX players are counted only after the direct RB/WR/TE requirements have
    been satisfied.  This keeps a roster with many tight ends, for example,
    from being treated as having enough FLEX depth while it is still missing
    a required kicker or defense.
    """
    requirements = position_requirements(roster_positions)
    positions = [canonical_position(position) for position in (player_positions or [])]
    counts = Counter(positions)
    invalid_positions = sorted(position for position in counts if position not in LEGAL_POSITIONS)
    missing_direct = {
        position: max(0, requirements[position] - counts[position])
        for position in ("QB", "RB", "WR", "TE", "K", "DEF")
        if requirements[position] and counts[position] < requirements[position]
    }
    flex_available = sum(
        max(0, counts[position] - requirements[position])
        for position in FLEX_POSITIONS
    )
    missing_flex = max(0, requirements["FLEX"] - flex_available)
    expected_roster_size = len(list(roster_positions or []))
    roster_size_error = require_full_roster and len(positions) != expected_roster_size
    return {
        "valid": not invalid_positions and not missing_direct and not missing_flex and not roster_size_error,
        "counts": dict(sorted(counts.items())),
        "missing_direct": missing_direct,
        "flex_available": flex_available,
        "missing_flex": missing_flex,
        "roster_size": len(positions),
        "expected_roster_size": expected_roster_size,
        "roster_size_error": roster_size_error,
        "invalid_positions": invalid_positions,
    }


def validate_lineup(
    roster_positions: Any,
    player_positions: Any,
    *,
    require_full_roster: bool = False,
) -> dict[str, Any]:
    """Raise when the roster cannot support the configured weekly lineup."""
    result = lineup_validation(
        roster_positions,
        player_positions,
        require_full_roster=require_full_roster,
    )
    if result["valid"]:
        return result

    problems = []
    if result["missing_direct"]:
        problems.append("missing " + ", ".join(
            f"{position} x{count}" for position, count in result["missing_direct"].items()
        ))
    if result["missing_flex"]:
        problems.append(f"missing FLEX-eligible depth x{result['missing_flex']}")
    if result["invalid_positions"]:
        problems.append("unsupported positions: " + ", ".join(result["invalid_positions"]))
    if result["roster_size_error"]:
        problems.append(
            f"roster has {result['roster_size']} players; expected {result['expected_roster_size']}"
        )
    raise ValueError("roster cannot support the required weekly lineup: " + "; ".join(problems))


def lineup_completion_validation(
    roster_positions: Any,
    current_player_positions: Any,
    available_player_positions: Any,
    remaining_picks: int,
) -> dict[str, Any]:
    """Describe whether the remaining board can complete a weekly lineup."""
    requirements = position_requirements(roster_positions)
    current = Counter(canonical_position(position) for position in (current_player_positions or []))
    available = Counter(canonical_position(position) for position in (available_player_positions or []))
    direct_deficits = {
        position: max(0, requirements[position] - current[position])
        for position in ("QB", "RB", "WR", "TE", "K", "DEF")
        if requirements[position] and current[position] < requirements[position]
    }
    unavailable_direct = {
        position: count - available[position]
        for position, count in direct_deficits.items()
        if available[position] < count
    }
    current_flex = sum(
        max(0, current[position] - requirements[position])
        for position in FLEX_POSITIONS
    )
    available_flex_after_direct = sum(
        max(0, available[position] - direct_deficits.get(position, 0))
        for position in FLEX_POSITIONS
    )
    missing_flex = max(0, requirements["FLEX"] - current_flex)
    flex_deficit = max(0, missing_flex - available_flex_after_direct)
    required_picks = sum(direct_deficits.values()) + missing_flex
    remaining_picks = max(0, int(remaining_picks))
    expected_roster_size = len(list(roster_positions or []))
    roster_size_possible = sum(current.values()) + remaining_picks >= expected_roster_size
    feasible = (
        not unavailable_direct
        and flex_deficit == 0
        and required_picks <= remaining_picks
        and roster_size_possible
    )
    return {
        "feasible": feasible,
        "direct_deficits": direct_deficits,
        "unavailable_direct": unavailable_direct,
        "current_flex": current_flex,
        "available_flex_after_direct": available_flex_after_direct,
        "missing_flex": missing_flex,
        "required_picks": required_picks,
        "remaining_picks": remaining_picks,
        "roster_size_possible": roster_size_possible,
    }
